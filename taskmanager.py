#!/usr/bin/env python3
"""
SUDARSHAN V16.9 — Task Manager Toolkit (taskmanager.py)

This is NOT an orchestration engine. The LLM orchestrates via SUDARSHAN.md.
This is a set of callable, stdlib-only CLI tools that the LLM and human
can invoke on demand — same pattern as safe_edit.py and dag_validator.py.

Usage:
    python3 taskmanager.py --init "Build an AI dating platform"
    python3 taskmanager.py --resume
    python3 taskmanager.py --check-gate 1
    python3 taskmanager.py --status
    python3 taskmanager.py --abort
    python3 taskmanager.py --record-strike grunt_SETUP "npm install failed"
    python3 taskmanager.py --invoice
    python3 taskmanager.py --cleanup-ports

Each command runs, prints output, exits. No daemon. No event loop.
The prompt is the orchestrator. These are the power tools on the factory floor.

Dependencies: Python 3.8+ stdlib only (zero external packages).
"""

import os, sys, json, time, hashlib, subprocess, shutil, argparse, re, tempfile, uuid
from datetime import datetime, timezone
import urllib.request
from urllib.error import URLError
from enum import Enum

from protocol_assets import install_required_templates, load_template_json, load_version
from safe_edit import acquire_lock, release_lock

# Fix Windows PowerShell encoding crash — emoji chars fail on charmap
def ensure_utf8_stdio():
    """Fix Windows console encoding at CLI runtime without mutating import-time streams."""
    if sys.platform != "win32":
        return
    import io
    if hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "buffer"):
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


# ═══════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════
PROTOCOL_VERSION = load_version()

WORKSPACE_ROOT = os.environ.get("SUDARSHAN_WORKSPACE", os.getcwd())
ENTERPRISE_STATE = os.path.join(WORKSPACE_ROOT, "enterprise_state")
ISOLATED_TASKS = os.path.join(WORKSPACE_ROOT, "isolated_tasks")

SWARM_LOCK = os.path.join(WORKSPACE_ROOT, ".swarm_lock")
RESUME_LOCK = os.path.join(WORKSPACE_ROOT, ".resume_lock")
JIRA_DAG = os.path.join(ENTERPRISE_STATE, "JIRA_DAG.json")
STRIKE_LEDGER = os.path.join(ENTERPRISE_STATE, "STRIKE_LEDGER.json")
BATON_STATE = os.path.join(ENTERPRISE_STATE, "BATON_STATE.json")
BLACKBOARD = os.path.join(ENTERPRISE_STATE, "BLACKBOARD_STATUS.json")
ARCHITECTURE_STATE = os.path.join(ENTERPRISE_STATE, "ARCHITECTURE_STATE.md")
RESEARCH_MANIFEST = os.path.join(ENTERPRISE_STATE, "RESEARCH_MANIFEST.json")
RESEARCH_VERDICT = os.path.join(ENTERPRISE_STATE, "RESEARCH_VERDICT.json")
SUPER_PROMPT_MUTATIONS = os.path.join(ENTERPRISE_STATE, "SUPER_PROMPT_MUTATIONS.json")
SCOPE_MANIFEST = os.path.join(ENTERPRISE_STATE, "SCOPE_MANIFEST.json")
UI_SPEC = os.path.join(ENTERPRISE_STATE, "UI_SPEC.json")
PM_AUDIT_REPORT = os.path.join(ENTERPRISE_STATE, "PM_AUDIT_REPORT.json")
HUMAN_INPUT = os.path.join(ISOLATED_TASKS, "HUMAN_INPUT.txt")
LIVE_STATUS = os.path.join(ISOLATED_TASKS, "live_status.json")

MAX_STRIKES_PER_GRUNT = 3
MAX_STAFF_INTERVENTIONS = 4
ZOMBIE_TIMEOUT_SECONDS = 900

# V16.9: Phase 0 Research Limits
MIN_SOURCES = 10
MAX_SOURCES = 40
MAX_SEARCH_QUERIES = 40
MAX_WEB_FETCH_CALLS = 30
MAX_PHASE_0_DURATION_SECONDS = 3600


# ═══════════════════════════════════════════════════════════════
# PHASE DEFINITIONS (Canonical — single source of truth)
# The string values here ARE the values stored in .swarm_lock["phase"].
# No other phase strings are valid anywhere in this codebase.
# ═══════════════════════════════════════════════════════════════
class Phase(Enum):
    PHASE_0_RESEARCH   = "phase_0_research"
    PHASE_1_CONTRACT   = "phase_1_contract"
    PHASE_2_EXECUTION  = "phase_2_execution"
    PHASE_3_CICD       = "phase_3_cicd"
    PHASE_4_INTEGRATION = "phase_4_integration"
    PHASE_5_DELIVERY   = "phase_5_delivery"
    COMPLETED           = "completed"
    HALTED              = "halted"


# ═══════════════════════════════════════════════════════════════
# STATE MANAGEMENT (Atomic JSON read/write)
# ═══════════════════════════════════════════════════════════════
class StateManager:
    @staticmethod
    def read_json(path, default=None):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return default if default is not None else {}

    @staticmethod
    def _write_json_unlocked(path, data):
        parent = os.path.dirname(os.path.abspath(path))
        os.makedirs(parent, exist_ok=True)
        tmp_fd, tmp_path = tempfile.mkstemp(dir=parent, suffix=".json.tmp")
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp_path, path)
        finally:
            try:
                os.remove(tmp_path)
            except FileNotFoundError:
                pass

    @staticmethod
    def write_json(path, data):
        """Atomically write JSON while serializing competing writers."""
        worker_id = f"state-write-{os.getpid()}-{uuid.uuid4().hex}"
        lock_id = acquire_lock(path, worker_id)
        try:
            StateManager._write_json_unlocked(path, data)
        finally:
            release_lock(path, worker_id, lock_id)

    @staticmethod
    def update_json(path, mutator, default=None):
        """Apply one read-modify-write transaction under a cross-process lock."""
        worker_id = f"state-{os.getpid()}-{uuid.uuid4().hex}"
        lock_id = acquire_lock(path, worker_id)
        try:
            state = StateManager.read_json(path, default=default)
            updated = mutator(state)
            if updated is None:
                updated = state
            StateManager._write_json_unlocked(path, updated)
            return updated
        finally:
            release_lock(path, worker_id, lock_id)

    @staticmethod
    def iso_now():
        return datetime.now(timezone.utc).isoformat()


def write_live_status(status, message, phase=None, extra=None):
    payload = {
        "timestamp": int(time.time()),
        "iso_timestamp": StateManager.iso_now(),
        "status": status,
        "phase": phase or (StateManager.read_json(SWARM_LOCK, default={}).get("phase") or "idle"),
        "message": message,
    }
    if extra:
        payload.update(extra)
    StateManager.write_json(LIVE_STATUS, payload)


# ═══════════════════════════════════════════════════════════════
# GATE VALIDATORS (Callable checks — exit code 0 = PASS)
#   Usage: python3 taskmanager.py --check-gate 1
#   The LLM gets a deterministic binary answer instead of
#   self-assessing whether the gate passes (which is probabilistic).
# ═══════════════════════════════════════════════════════════════
class GateValidator:
    @staticmethod
    def check_gate_0():
        """Phase 0 exit: Validates RESEARCH_VERDICT.json from Judge Probe.
        Exit 0 = LOCK_PHASE_0, Exit 1 = EXPAND_RESEARCH/malformed, Exit 2 = ESCALATE_TO_L1."""
        verdict_data = StateManager.read_json(RESEARCH_VERDICT, default={})
        verdict = verdict_data.get("verdict")
        sources = verdict_data.get("sources_consulted", 0)
        ambiguities = verdict_data.get("ambiguities_remaining") or []
        coverage_gaps = verdict_data.get("coverage_gaps") or []

        results = []
        results.append(("RESEARCH_VERDICT.json exists", verdict is not None))
        results.append((f"Sources consulted: {sources} (min: {MIN_SOURCES})", sources >= MIN_SOURCES))
        results.append((f"Ambiguities remaining: {len(ambiguities)}", len(ambiguities) == 0))
        results.append((f"Coverage gaps: {len(coverage_gaps)}", len(coverage_gaps) == 0))

        # Also check SCOPE_MANIFEST exists
        scope = StateManager.read_json(SCOPE_MANIFEST, default={})
        results.append(("SCOPE_MANIFEST.json populated", len(scope.get("core") or []) > 0))

        # Also check STRICT_CONSTRAINTS.json exists for large payloads
        path = os.path.join(WORKSPACE_ROOT, "STRICT_CONSTRAINTS.json")
        results.append(("STRICT_CONSTRAINTS.json exists", os.path.exists(path)))

        if verdict == "LOCK_PHASE_0":
            results.append(("Judge verdict: LOCK_PHASE_0", True))
        elif verdict == "ESCALATE_TO_L1":
            results.append(("Judge verdict: ESCALATE_TO_L1 (HaaS required)", False))
            # Print all results, then exit 2 for HaaS
            for desc, passed in results:
                sym = "✅" if passed else "❌"
                print(f"  {sym} {desc}")
            print("  GATE_0_HAAS: Research saturated but ambiguities unresolvable. HaaS required.")
            sys.exit(2)
        elif verdict == "EXPAND_RESEARCH":
            results.append(("Judge verdict: EXPAND_RESEARCH (more research needed)", False))
        else:
            results.append(("Judge verdict: missing or malformed", False))

        return results

    @staticmethod
    def check_gate_1():
        """Phase 1 Gate 1: Git foundation + state files initialized."""
        return [
            (".gitignore exists",
             os.path.exists(os.path.join(WORKSPACE_ROOT, ".gitignore"))),
            ("enterprise_state/ exists",
             os.path.isdir(ENTERPRISE_STATE)),
            ("STRIKE_LEDGER.json initialized",
             StateManager.read_json(STRIKE_LEDGER).get("ledger_version") is not None),
            ("ARCHITECTURE_STATE.md exists",
             os.path.exists(ARCHITECTURE_STATE)),
        ]

    @staticmethod
    def check_gate_2():
        """Phase 1 Gate 2: Pre-Mortem (written by PM, not Orchestrator) + DAG_RATIONALE.md + EXECUTION_PLAN_V2.md."""
        dag = StateManager.read_json(JIRA_DAG)
        nodes = dag.get("nodes", dag.get("tasks", []))
        n = len(nodes) if isinstance(nodes, (list, dict)) else 0
        results = []
        if n > 2:
            results.append(("PRE_MORTEM.md required (>2 DAG nodes)",
                     os.path.exists(os.path.join(WORKSPACE_ROOT, "PRE_MORTEM.md"))))
        else:
            results.append(("PRE_MORTEM.md not required (simple project)", True))
        results.append(("DAG_RATIONALE.md exists",
                 os.path.exists(os.path.join(WORKSPACE_ROOT, "DAG_RATIONALE.md"))))
        results.append(("EXECUTION_PLAN_V2.md exists",
                 os.path.exists(os.path.join(WORKSPACE_ROOT, "EXECUTION_PLAN_V2.md"))))
        return results

    @staticmethod
    def check_gate_3():
        """Phase 1 Gate 3: PM Architecture Audit via PM_AUDIT_REPORT.json (AA1-AA5)."""
        report = StateManager.read_json(PM_AUDIT_REPORT, default={})
        results = []
        required_steps = ["AA1", "AA2", "AA3", "AA4", "AA5"]
        missing = [s for s in required_steps if s not in report]
        results.append((f"PM_AUDIT_REPORT.json has all steps (missing: {missing})", len(missing) == 0))

        # Check each step result
        for step in required_steps:
            step_data = report.get(step, {})
            result = step_data.get("result")
            if result == "FAIL":
                results.append((f"{step} ({step_data.get('step', '?')}): FAIL", False))
            elif result in ("PASS", "WARN"):
                results.append((f"{step} ({step_data.get('step', '?')}): {result}", True))
            else:
                results.append((f"{step}: result missing or invalid", False))

        # Check overall verdict
        overall = report.get("overall_verdict")
        results.append((f"Overall verdict: {overall}", overall == "APPROVE"))

        # Also check PM audit rejections < 3
        ledger = StateManager.read_json(STRIKE_LEDGER)
        count = len(ledger.get("pm_audit_rejections") or [])
        results.append((f"PM audit rejections ({count}) < 3", count < 3))

        return results

    @staticmethod
    def check_gate_4(frontend_only=False):
        """Phase 1 Gate 4: Spectral lint on openapi.yaml must return exit 0."""
        if frontend_only:
            return [("Contract gate skipped (frontend-only MVP)", True)]

        openapi = os.path.join(WORKSPACE_ROOT, "openapi.yaml")
        if not os.path.exists(openapi):
            return [("openapi.yaml exists", False)]

        cmd = shutil.which("spectral")
        if not cmd:
            cmd = shutil.which("npx")

        if not cmd:
            return [("openapi.yaml exists", True),
                    ("Spectral CLI available", False)]

        try:
            lint_cmd = [cmd, "lint", openapi] if cmd == "spectral" \
                else ["npx", "@stoplight/spectral-cli", "lint", openapi]
            r = subprocess.run(lint_cmd,
                               capture_output=True, text=True, timeout=30)
            return [("openapi.yaml exists", True),
                    ("Spectral lint exit 0", r.returncode == 0)]
        except Exception as e:
            return [("openapi.yaml exists", True),
                    ("Spectral CLI available", False)]

    @staticmethod
    def check_dag():
        """Phase 2 entry: DAG must pass mathematical validation."""
        if not os.path.exists(JIRA_DAG):
            return [("JIRA_DAG.json exists", False)]

        validator = os.path.join(WORKSPACE_ROOT, "dag_validator.py")
        if not os.path.exists(validator):
            validator = os.path.join(ISOLATED_TASKS, "dag_validator.py")
        if not os.path.exists(validator):
            return [("JIRA_DAG.json exists", True),
                    ("dag_validator.py exists", False)]
        try:
            r = subprocess.run([sys.executable, validator, JIRA_DAG],
                               capture_output=True, text=True, timeout=10)
            return [("JIRA_DAG.json exists", True),
                    ("DAG mathematical validation", r.returncode == 0)]
        except Exception as e:
            return [("DAG validator error", False)]

    @staticmethod
    def check_ui_spec():
        """Phase 1 Gate 4b: Validate UI_SPEC.json schema completeness."""
        spec = StateManager.read_json(UI_SPEC, default={})
        results = []

        # Delta-Debate enforcement (V16.9): if debate happened, ruling must exist
        delta_ruling_path = os.path.join(WORKSPACE_ROOT, "DELTA_RULING.json")
        delta_critique1 = os.path.join(WORKSPACE_ROOT, "DELTA_CRITIQUE_1.json")
        debate_happened = os.path.exists(delta_critique1)
        if debate_happened:
            ruling = StateManager.read_json(delta_ruling_path, default=None)
            ruling_valid = ruling is not None and ruling.get("verdict") is not None
            results.append(("DELTA_RULING.json exists with verdict", ruling_valid))
            if ruling_valid:
                valid_verdicts = {"ACCEPT", "ESCALATE_TO_ORCHESTRATOR", "ACCEPT_WITH_REVISIONS"}
                results.append(("DELTA_RULING verdict is valid",
                                ruling.get("verdict") in valid_verdicts))
        else:
            results.append(("DELTA-Debate: skipped (no critique files)", True))

        results.append(("UI_SPEC.json exists", bool(spec)))
        results.append(("Pages defined", len(spec.get("pages") or []) > 0))
        ds = spec.get("design_system", {})
        results.append(("Color system populated",
                        ds.get("colors", {}).get("primary") is not None))
        results.append(("Typography defined",
                        ds.get("typography", {}).get("font_family") is not None))
        results.append(("Component library selected",
                        spec.get("component_library") is not None))
        results.append(("Responsive breakpoints defined",
                        len(spec.get("responsive_breakpoints") or []) > 0))

        # Cross-check: components in pages should be valid
        known_libs = {
            "shadcn/ui": ["Button", "Input", "Card", "Table", "Dialog",
                         "Select", "Badge", "Separator", "Tabs", "Sheet",
                         "Avatar", "Dropdown", "Popover", "Toast", "Form"],
            "chakra-ui": ["Box", "Flex", "Text", "Button", "Input",
                         "Modal", "Table", "Stack", "Grid"],
            "mantine": ["Button", "TextInput", "Card", "Table", "Modal",
                       "Select", "Badge", "Tabs", "AppShell"],
        }
        lib = spec.get("component_library", "")
        available = known_libs.get(lib, []) + (spec.get("custom_components") or [])
        comp_errors = []
        for page in spec.get("pages") or []:
            for comp in page.get("components") or []:
                if available and comp not in available:
                    comp_errors.append(f"Page '{page.get('name', '?')}': '{comp}' not in {lib}")
        if comp_errors:
            for e in comp_errors:
                results.append((e, False))
        else:
            results.append(("All page components valid", True))

        return results

    @staticmethod
    def check_ports():
        """Phase 5: Check that dev ports are clean."""
        import socket
        results = []
        # Port 8080 excluded — reserved for SearXNG (must be IN USE)
        for port in [3000, 3001, 5173, 8000, 5000]:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(1)
                clean = s.connect_ex(('127.0.0.1', port)) != 0
                s.close()
                results.append((f"Port {port} {'clean' if clean else 'IN USE'}", clean))
            except Exception:
                results.append((f"Port {port} check", True))
        return results


# ═══════════════════════════════════════════════════════════════
# STRIKE LEDGER (Callable tool — deterministic failure tracking)
#   Usage: python3 taskmanager.py --record-strike grunt_SETUP "build failed"
# ═══════════════════════════════════════════════════════════════
class StrikeLedger:
    @staticmethod
    def _default():
        return {
            "ledger_version": PROTOCOL_VERSION,
            "total_strikes": 0,
            "total_staff_engineer_interventions": 0,
            "total_session_cost_usd": 0,
            "strikes": [],
            "staff_interventions": [],
            "pm_audit_rejections": [],
            "token_usage": [],
            "metadata": {"last_updated_at": StateManager.iso_now()},
        }

    @staticmethod
    def _ensure():
        StateManager.update_json(
            STRIKE_LEDGER,
            lambda ledger: ledger,
            default=StrikeLedger._default(),
        )

    @staticmethod
    def record_strike(worker_id, description):
        def mutate(ledger):
            ledger["total_strikes"] = ledger.get("total_strikes", 0) + 1
            ledger.setdefault("strikes", []).append({
                "worker_id": worker_id,
                "description": description,
                "timestamp": StateManager.iso_now(),
            })
            ledger.setdefault("metadata", {})["last_updated_at"] = StateManager.iso_now()
            return ledger

        ledger = StateManager.update_json(
            STRIKE_LEDGER,
            mutate,
            default=StrikeLedger._default(),
        )

        worker_strikes = len([s for s in ledger["strikes"]
                              if s["worker_id"] == worker_id])
        total = ledger["total_strikes"]
        staff = ledger.get("total_staff_engineer_interventions", 0)

        print(f"STRIKE RECORDED: {worker_id} — {description}")
        print(f"  Worker strikes: {worker_strikes}/{MAX_STRIKES_PER_GRUNT}")
        print(f"  Total strikes:  {total}")
        if worker_strikes >= MAX_STRIKES_PER_GRUNT:
            print(f"  [SYSTEM: ESCALATE_TO_STAFF_ENGINEER] {worker_id}")
        if staff >= MAX_STAFF_INTERVENTIONS:
            print(f"  [SYSTEM: 12_STRIKE_CEILING_HIT]")

    @staticmethod
    def record_staff_intervention(summary):
        def mutate(ledger):
            ledger["total_staff_engineer_interventions"] = (
                ledger.get("total_staff_engineer_interventions", 0) + 1
            )
            ledger.setdefault("staff_interventions", []).append({
                "summary": summary,
                "timestamp": StateManager.iso_now(),
            })
            return ledger

        ledger = StateManager.update_json(
            STRIKE_LEDGER,
            mutate,
            default=StrikeLedger._default(),
        )
        count = ledger["total_staff_engineer_interventions"]
        print(f"STAFF INTERVENTION #{count}: {summary}")
        if count >= MAX_STAFF_INTERVENTIONS:
            print("[SYSTEM: HAAS_REQUEST] — 12_STRIKE_CEILING_HIT. Swarm should halt.")

    @staticmethod
    def record_pm_rejection(reason):
        def mutate(ledger):
            ledger.setdefault("pm_audit_rejections", []).append({
                "reason": reason,
                "timestamp": StateManager.iso_now(),
            })
            return ledger

        ledger = StateManager.update_json(
            STRIKE_LEDGER,
            mutate,
            default=StrikeLedger._default(),
        )
        count = len(ledger["pm_audit_rejections"])
        print(f"PM REJECTION #{count}: {reason}")
        if count >= 3:
            print("[SYSTEM: HAAS_REQUEST] — PM rejected architecture 3 times.")


# ═══════════════════════════════════════════════════════════════
# COST TRACKER (Dynamic Pricing — Phase 0 live rates → static fallback)
#   Usage: python3 taskmanager.py --record-cost phase_2 grunt_SETUP 5000 2000
#          python3 taskmanager.py --invoice
# ═══════════════════════════════════════════════════════════════
class CostTracker:
    # API Costs per 1M tokens (USD) - Dynamic map based on User Stipulation 1
    MODEL_PRICING = {
        "claude-3-5-sonnet": {"in": 3.00, "out": 15.00, "name": "Claude 3.5 Sonnet"},
        "claude-3-5-haiku": {"in": 0.25, "out": 1.25, "name": "Claude 3.5 Haiku"},
        "gpt-4o": {"in": 5.00, "out": 15.00, "name": "GPT-4o"},
        "gpt-4o-mini": {"in": 0.15, "out": 0.60, "name": "GPT-4o Mini"},
        "gemini-1.5-pro": {"in": 3.50, "out": 10.50, "name": "Gemini 1.5 Pro"},
        "gemini-1.5-flash": {"in": 0.35, "out": 1.05, "name": "Gemini 1.5 Flash"},
        "deepseek-coder-v2": {"in": 0.14, "out": 0.28, "name": "DeepSeek Coder V2"},
        "default": {"in": 3.00, "out": 15.00, "name": "Default / Unknown"}
    }

    @staticmethod
    def _get_pricing():
        """Priority 1: Live pricing from Phase 0 dynamic search.
        Priority 2: Static fallback from --model arg or hardcoded dict."""
        bb = StateManager.read_json(BLACKBOARD)
        meta = bb.get("metadata", {})
        live = meta.get("model_pricing")
        if live and isinstance(live, dict) and "in" in live and "out" in live:
            try:
                return {"in": float(live["in"]), "out": float(live["out"]),
                        "name": live.get("name", "Dynamic (Phase 0)")}
            except (ValueError, TypeError):
                pass
        model = meta.get("model", "default")
        return CostTracker.MODEL_PRICING.get(model, CostTracker.MODEL_PRICING["default"])

    @staticmethod
    def record(phase, role, input_tokens, output_tokens):
        pricing = CostTracker._get_pricing()

        # Calculate cost based on per 1M token rate
        cost = round(
            (input_tokens / 1_000_000) * pricing["in"] +
            (output_tokens / 1_000_000) * pricing["out"], 6)

        def mutate(ledger):
            ledger["total_session_cost_usd"] = round(
                ledger.get("total_session_cost_usd", 0) + cost, 4
            )
            ledger.setdefault("token_usage", []).append({
                "phase": phase,
                "role": role,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cost_usd": cost,
                "timestamp": StateManager.iso_now(),
            })
            return ledger

        ledger = StateManager.update_json(
            STRIKE_LEDGER,
            mutate,
            default=StrikeLedger._default(),
        )
        print(f"COST: +${cost} ({role} in {phase} | Model: {pricing['name']}) — "
              f"Total: ${ledger['total_session_cost_usd']}")

    @staticmethod
    def invoice():
        ledger = StateManager.read_json(STRIKE_LEDGER)
        total = ledger.get("total_session_cost_usd", 0)
        usage = ledger.get("token_usage", [])
        by_phase, by_role = {}, {}
        for e in usage:
            p = e.get("phase", "?")
            r = e.get("role", "?")
            c = e.get("cost_usd", 0)
            by_phase[p] = round(by_phase.get(p, 0) + c, 4)
            by_role[r] = round(by_role.get(r, 0) + c, 4)

        print(f"\n{'='*50}")
        print(f" SUDARSHAN V{PROTOCOL_VERSION} — Execution Invoice")
        print(f"{'='*50}")
        print(f"  Total USD:  ${total}")
        if by_phase:
            print(f"  By Phase:")
            for phase, cost in by_phase.items():
                print(f"    {phase}: ${cost}")
        if by_role:
            print(f"  By Role:")
            for role, cost in sorted(by_role.items(), key=lambda x: -x[1]):
                print(f"    {role}: ${cost}")
        print(f"  Entries:    {len(usage)}")
        print(f"{'='*50}\n")
        return {"total_cost_usd": total,
                "cost_by_phase": by_phase, "cost_by_role": by_role}


# ═══════════════════════════════════════════════════════════════
# SUPER PROMPT COMPILER
#   Usage: python3 taskmanager.py --init "Build AI dating platform"
#   Outputs the exact boot payload string to pass to the Orchestrator.
# ═══════════════════════════════════════════════════════════════
def compile_super_prompt(directive, frontend_only_override=False, model_id="default"):
    """Expand raw directive into structured Super Prompt.
    The Main Thread MUST NOT pass the raw prompt to the Swarm.

    Context-aware: detects complexity signals in the directive to
    auto-configure gates, Pre-Mortem requirements, and scope flags."""
    dl = directive.lower()

    # ── Detect complexity signals ──
    has_backend = bool(re.search(
        r'\b(api|backend|server|microservice|database|postgres|mongo|prisma'
        r'|graphql|rest|endpoint|auth|jwt|oauth|webhook)\b', dl))
    has_frontend = bool(re.search(
        r'\b(frontend|ui|ux|react|next|vue|svelte|tailwind|landing|dashboard'
        r'|component|page|layout|responsive)\b', dl))
    is_workflow = bool(re.search(
        r'\b(n8n|workflow|automation|pipeline|zapier|make\.com|cron|scheduler)\b', dl))
    is_massive = bool(re.search(
        r'\b(microservice|multi.?service|warehouse|distributed|monorepo'
        r'|platform|enterprise|protocol|rebuild|commerce)\b', dl))
    references_spec = bool(re.search(
        r'\b(beckn|openapi|swagger|rfc|specification|protocol|standard)\b', dl))
    is_frontend_only = frontend_only_override or (has_frontend and not has_backend)

    # ── Build context-aware Super Prompt ──
    sections = [f"# SUPER PROMPT (Compiled by TaskManager)\n## Directive\n{directive}"]

    # Auto-detected scope
    scope_flags = []
    if is_frontend_only:
        scope_flags.append("FRONTEND_ONLY_MVP=true (Gate 4 Spectral lint skipped)")
    if has_backend:
        scope_flags.append("HAS_BACKEND=true (openapi.yaml + data contract artifact required)")
    if is_massive:
        scope_flags.append("HIGH_COMPLEXITY=true (Pre-Mortem REQUIRED in Phase 1)")
    if is_workflow:
        scope_flags.append("WORKFLOW_MODE=true (lighter DAG, may skip Playwright)")
    if references_spec:
        scope_flags.append("SPEC_REFERENCE=true (Phase 0 MUST deep-research the referenced spec)")

    if scope_flags:
        sections.append("## Auto-Detected Scope\n" + "\n".join(f"- {f}" for f in scope_flags))

    # [User Req 2] Inject Dynamic Pricing Search Directive
    sections.append(
        "## Special Directive: Dynamic Model Pricing Check\n"
        f"Your absolute FIRST action in Phase 0 MUST be to execute: "
        f"`node skills/os_search/search.js \"{model_id} API pricing per 1 million tokens USD 2025\"`\n"
        "Extract the raw input and output cost per 1M tokens in USD. Then, write this exact JSON object into the `metadata` block of `enterprise_state/BLACKBOARD_STATUS.json`:\n"
        "`\"model_pricing\": {\"in\": [input_cost], \"out\": [output_cost], \"name\": \"[Model Name]\"}`\n"
        "This ensures the Phase-Watcher computes accurate invoices."
    )

    # Technical constraints (always present)
    constraints = [
        "Write code ONLY via safe_edit.py (ACI mandate)",
        "Context trimming via dag_subgraph.py (hallucinating BANNED)",
        "Research via node skills/os_search/search.js (web_search BANNED)",
        "web_fetch on localhost:8080 BANNED (RAG poisoning)",
        "Sequential Dev Booting until Phase 4",
        "Docker Desktop BANNED — use Native Docker / OrbStack",
        "Playwright browser.close() immediately after screenshots",
    ]
    if not is_frontend_only:
        constraints.append("Frontend mocking via Prism off openapi.yaml until Phase 4")
    if has_backend:
        constraints.append("Gate check: python3 taskmanager.py --check-gate 4 must exit 0")
    sections.append("## Technical Constraints\n" + "\n".join(f"- {c}" for c in constraints))

    # Success criteria
    criteria = [
        "All DAG nodes DONE with Red Team GREEN LIGHT",
        "Port-based cleanup (npx kill-port) in Phase 5",
        "COMPLETION_REPORT.md generated with invoice",
    ]
    if has_backend:
        criteria.insert(1, "Spectral lint exit 0 on openapi.yaml")
    if not is_workflow:
        criteria.insert(-1, "E2E Playwright QA passes full user journey in Phase 4")
    sections.append("## Success Criteria\n" + "\n".join(f"- {c}" for c in criteria))

    # Gate check reminders (the killer feature)
    sections.append(
        "## Gate Verification Commands\n"
        "Use these for deterministic binary checks (exit 0 = PASS):\n"
        "- `python3 taskmanager.py --check-gate 0` → Judge Probe verdict + scope validation\n"
        "- `python3 taskmanager.py --check-gate 1` → Git foundation + state files\n"
        "- `python3 taskmanager.py --check-gate 2` → Pre-Mortem + DAG_RATIONALE.md\n"
        "- `python3 taskmanager.py --check-gate 3` → PM_AUDIT_REPORT.json AA1-AA5\n"
        + ("- `python3 taskmanager.py --check-gate 4` → Spectral lint on openapi.yaml\n" if has_backend else "")
        + "- `python3 taskmanager.py --check-gate-ui-spec` → UI_SPEC.json validation (Gate 4b)\n"
        "- `python3 taskmanager.py --check-gate dag` → DAG mathematical validation\n"
        "- `python3 taskmanager.py --check-gate ports` → Dev ports clean (Phase 5)\n"
        "- `python3 taskmanager.py --record-search` → Track Phase 0 search count\n"
        "- `python3 taskmanager.py --tag-phase N` → Create phase boundary git tag\n"
        "- `python3 taskmanager.py --update-phase phase_N` → Update swarm phase to prevent timeout"
    )

    super_prompt = "\n\n".join(sections) + "\n"
    prompt_hash = hashlib.sha256(super_prompt.encode()).hexdigest()[:16]
    return super_prompt, prompt_hash, is_frontend_only


# ═══════════════════════════════════════════════════════════════
# CLI COMMANDS
# ═══════════════════════════════════════════════════════════════
def cmd_init(directive, frontend_only=False, model_id="default"):
    """One-time workspace bootstrap. Run BEFORE spawning the Swarm.
    This is the one non-bypassable window — no LLM is involved yet."""

    print(f"\n{'='*60}")
    print(f" SUDARSHAN V{PROTOCOL_VERSION} — Workspace Bootstrap")
    print(f"{'='*60}\n")

    # 1. Create directory structure
    for d in [ENTERPRISE_STATE, ISOLATED_TASKS]:
        os.makedirs(d, exist_ok=True)
        print(f"  ✅ Created: {d}")

    research_cache = os.path.join(WORKSPACE_ROOT, "RESEARCH_CACHE")
    os.makedirs(research_cache, exist_ok=True)
    print(f"  ✅ Created: {research_cache}")

    # 2. Install required templates from the canonical templates/ directory.
    template_results = install_required_templates(WORKSPACE_ROOT, overwrite=False)
    for relative_path, created in sorted(template_results.items()):
        base = os.path.basename(relative_path)
        if created:
            print(f"  ✅ Initialized from template: {base}")
        else:
            print(f"  ⏭️  Exists: {base}")

    if not os.path.exists(HUMAN_INPUT):
        with open(HUMAN_INPUT, "w", encoding="utf-8") as f:
            f.write("")
        print(f"  ✅ Created: HUMAN_INPUT.txt")

    # 2b. Merge dynamic runtime metadata into templated state files.
    ledger = StateManager.read_json(STRIKE_LEDGER, default=load_template_json("enterprise_state/STRIKE_LEDGER.json"))
    if ledger.get("metadata") is None:
        ledger["metadata"] = {}
    if ledger["metadata"].get("initialized_at") is None:
        ledger["metadata"]["initialized_at"] = StateManager.iso_now()
    ledger["metadata"]["last_updated_at"] = StateManager.iso_now()
    StateManager.write_json(STRIKE_LEDGER, ledger)

    bb = StateManager.read_json(BLACKBOARD, default=load_template_json("enterprise_state/BLACKBOARD_STATUS.json"))
    if "metadata" not in bb:
        bb["metadata"] = {}
    if "budget" not in bb["metadata"]:
        bb["metadata"]["budget"] = load_template_json("enterprise_state/BLACKBOARD_STATUS.json")["metadata"]["budget"]
    bb["blackboard_version"] = PROTOCOL_VERSION
    bb["metadata"]["last_updated_at"] = StateManager.iso_now()
    bb["metadata"]["model"] = model_id
    StateManager.write_json(BLACKBOARD, bb)
    print(f"  ✅ Updated: BLACKBOARD_STATUS.json (runtime metadata merged)")

    baton = StateManager.read_json(BATON_STATE, default=load_template_json("enterprise_state/BATON_STATE.json"))
    if "metadata" not in baton:
        baton["metadata"] = {}
    baton["baton_version"] = PROTOCOL_VERSION
    baton["metadata"]["last_serialized_at"] = baton["metadata"].get("last_serialized_at") or StateManager.iso_now()
    StateManager.write_json(BATON_STATE, baton)
    print(f"  ✅ Updated: BATON_STATE.json (runtime metadata merged)")

    # 3. Compile Super Prompt (context-aware)
    super_prompt, prompt_hash, detected_frontend_only = compile_super_prompt(
        directive, frontend_only_override=frontend_only, model_id=model_id)
    if detected_frontend_only and not frontend_only:
        print(f"  ℹ️  Auto-detected: frontend-only MVP (Gate 4 will be skipped)")
        frontend_only = True
    print(f"\n  Super Prompt compiled (hash: {prompt_hash})")

    # 4. Acquire .swarm_lock
    StateManager.write_json(SWARM_LOCK, {
        "last_active_timestamp": int(time.time()),
        "created_at": int(time.time()),  # [M3] Static anchor for Phase 0 timeout (never refreshed by heartbeat)
        "session_id": f"session_{int(time.time())}",
        "phase": Phase.PHASE_0_RESEARCH.value,  # Must match Phase enum exactly
        "directive_hash": prompt_hash
    })

    # 4b. Inject model into blackboard for CostTracker
    bb = StateManager.read_json(BLACKBOARD)
    if "metadata" not in bb: bb["metadata"] = {}
    bb["metadata"]["model"] = model_id
    StateManager.write_json(BLACKBOARD, bb)
    print(f"  ✅ .swarm_lock acquired")

    # 5. Output the boot payload
    boot_payload = (
        f"BOOT SEQUENCE: Read SUDARSHAN.md immediately. "
        f"You are the Orchestrator. Your directive is this compiled "
        f"Super Prompt:\n\n{super_prompt}\n\n"
        f"Execute Phase 0 (Recon Engine), then proceed through all gates."
    )

    print(f"\n{'='*60}")
    print(f" BOOT PAYLOAD (pass this to your Orchestrator spawn):")
    print(f"{'='*60}")
    print(boot_payload)
    print(f"{'='*60}\n")

    print(f"**Task Manager Protocol: Acknowledged.**")
    print(f"- **Objective:** {directive[:120]}")
    print(f"- **Super Prompt Generated:** Yes (hash: {prompt_hash})")
    print(f"- **Frontend Only:** {frontend_only}")
    print(f"- **Workspace:** {WORKSPACE_ROOT}")

    # Store dynamic model if specified (from wrapper)
    bb = StateManager.read_json(BLACKBOARD)
    pricing = CostTracker._get_pricing()
    print(f"- **Pricing Map:** {pricing['name']}")

    print(f"*Ready to spawn Swarm.*\n")
    write_live_status(
        "BOOTSTRAPPED",
        f"Workspace bootstrapped for directive: {directive[:80]}",
        phase=Phase.PHASE_0_RESEARCH.value,
        extra={
            "frontend_only": frontend_only,
            "workspace": WORKSPACE_ROOT,
            "directive_hash": prompt_hash,
        },
    )


def cmd_status():
    """Print current system state. Human-readable dashboard."""
    lock = StateManager.read_json(SWARM_LOCK) if os.path.exists(SWARM_LOCK) else None
    baton = StateManager.read_json(BATON_STATE)
    ledger = StateManager.read_json(STRIKE_LEDGER)
    bb = StateManager.read_json(BLACKBOARD)
    live = StateManager.read_json(LIVE_STATUS) if os.path.exists(LIVE_STATUS) else None

    print(f"\n{'='*50}")
    print(f" SUDARSHAN V16.9 — System Status")
    print(f"{'='*50}")
    print(f"  Swarm Lock:     {'ACTIVE' if lock else 'NONE'}")
    if lock:
        age = int(time.time()) - lock.get("last_active_timestamp", 0)
        print(f"    Phase:        {lock.get('phase', '?')}")
        print(f"    Age:          {age}s")
        if age > ZOMBIE_TIMEOUT_SECONDS:
            print(f"    ⚠️  ZOMBIE (>{ZOMBIE_TIMEOUT_SECONDS}s)")
    print(f"  Blackboard:     {bb.get('status', 'IDLE')}")
    print(f"  Strikes:        {ledger.get('total_strikes', 0)}")
    print(f"  Staff Intrvns:  {ledger.get('total_staff_engineer_interventions', 0)}")
    print(f"  PM Rejections:  {len(ledger.get('pm_audit_rejections') or [])}")
    print(f"  Session Cost:   ${ledger.get('total_session_cost_usd', 0)}")
    print(f"  Relay Count:    {baton.get('relay_count', 0)}")
    if live:
        print(f"  Last Status:    {live.get('message', 'N/A')}")
    # ── DAG Progress ──
    dag_path = os.path.join(WORKSPACE_ROOT, "enterprise_state", "JIRA_DAG.json")
    if os.path.exists(dag_path):
        try:
            dag_data = StateManager.read_json(dag_path)
            dag_nodes = dag_data.get("nodes", dag_data.get("tasks", dag_data)) if isinstance(dag_data, dict) else dag_data
            if isinstance(dag_nodes, (list, dict)):
                items = dag_nodes if isinstance(dag_nodes, list) else [v if isinstance(v, dict) else {"status": "PENDING"} for v in dag_nodes.values()]
                total = len(items)
                done = sum(1 for n in items if isinstance(n, dict) and n.get("status", "").upper() in ("COMPLETE", "DONE", "COMPLETED"))
                wip = sum(1 for n in items if isinstance(n, dict) and n.get("status", "").upper() in ("IN_PROGRESS", "WIP", "ACTIVE"))
                failed = sum(1 for n in items if isinstance(n, dict) and n.get("status", "").upper() in ("FAILED", "BLOCKED"))
                pending = total - done - wip - failed
                print(f"  DAG Progress:   {done}/{total} complete, {wip} in progress, {failed} failed, {pending} pending")
        except Exception:
            pass
    print(f"{'='*50}\n")


def cmd_abort():
    """Force-kill: delete .swarm_lock, reset blackboard completely."""
    if os.path.exists(SWARM_LOCK):
        os.remove(SWARM_LOCK)
        print("✅ .swarm_lock deleted.")
    else:
        print("ℹ️  No .swarm_lock to delete.")
    StateManager.write_json(BLACKBOARD, {
        "blackboard_version": PROTOCOL_VERSION,
        "status": "IDLE",
        "blocker_type": None,
        "blocker_description": None,
        "blocked_since": None,
        "awaiting": None,
        "observer_attempts": 0,
        "escalated_to_l1": False,
        "resolution": None,
        "metadata": {"last_updated_at": StateManager.iso_now()}
    })
    write_live_status("ABORTED", "Swarm aborted and blackboard reset", phase=Phase.HALTED.value)
    print("✅ Blackboard fully reset to IDLE.")


def cmd_check_gate(gate_num, frontend_only=False):
    """Run a specific gate validator. Exit code 0 = PASS, 1 = FAIL.
    On PASS, auto-bumps .swarm_lock phase to prevent HEARTBEAT timeout sabotage."""
    gates = {
        0: GateValidator.check_gate_0,
        1: GateValidator.check_gate_1,
        2: GateValidator.check_gate_2,
        3: GateValidator.check_gate_3,
        4: lambda: GateValidator.check_gate_4(frontend_only),
        "dag": GateValidator.check_dag,
        "ports": GateValidator.check_ports,
        "ui-spec": GateValidator.check_ui_spec,
    }
    # Phase auto-bump map: gate → new .swarm_lock phase string on PASS
    # Values MUST match Phase enum exactly (Phase.XXX.value)
    phase_bump = {
        0:     Phase.PHASE_1_CONTRACT.value,   # Phase 0 passed → Phase 1 contract
        3:     Phase.PHASE_1_CONTRACT.value,   # Gate 3 (PM Audit) keeps in Phase 1
        "dag": Phase.PHASE_2_EXECUTION.value,  # DAG validated → Phase 2 execution
        "ports": Phase.PHASE_5_DELIVERY.value, # Ports clean → Phase 5 delivery
    }
    fn = gates.get(gate_num)
    if not fn:
        print(f"Unknown gate: {gate_num}. Valid: {list(gates.keys())}")
        sys.exit(1)

    results = fn()
    all_pass = True
    for desc, passed in results:
        sym = "✅" if passed else "❌"
        print(f"  {sym} {desc}")
        if not passed:
            all_pass = False

    # Auto-bump phase on PASS (prevents Phase 0 timeout sabotage)
    if all_pass and gate_num in phase_bump and os.path.exists(SWARM_LOCK):
        new_phase = phase_bump[gate_num]
        lock = StateManager.read_json(SWARM_LOCK)
        lock["phase"] = new_phase
        StateManager.write_json(SWARM_LOCK, lock)
        print(f"  🔄 .swarm_lock phase auto-bumped to: {new_phase}")

    sys.exit(0 if all_pass else 1)


def cmd_update_phase(phase_name):
    """Update the phase in .swarm_lock to prevent Phase 0 timeout sabotage."""
    valid_phases = [p.value for p in Phase]
    if phase_name not in valid_phases:
        print(f"❌ Invalid phase: '{phase_name}'. Valid values: {', '.join(valid_phases)}")
        sys.exit(1)
    if os.path.exists(SWARM_LOCK):
        lock = StateManager.read_json(SWARM_LOCK)
        lock["phase"] = phase_name
        StateManager.write_json(SWARM_LOCK, lock)
        write_live_status("PHASE_UPDATED", f"Swarm phase updated to {phase_name}", phase=phase_name)
        print(f"✅ .swarm_lock phase updated to: {phase_name}")
    else:
        print(f"ℹ️  No .swarm_lock exists to update.")


def cmd_cleanup_ports():
    """Phase 5: Port-based kills. PID guessing is BANNED."""
    # [C3] Excluded port 8080 (SearXNG) from kill list so we don't break the protocol
    for port in [3000, 3001, 5173, 8000, 5000]:
        try:
            subprocess.run(["npx", "kill-port", str(port)],
                           capture_output=True, timeout=10)
            print(f"  ✅ Port {port} cleaned.")
        except Exception:
            print(f"  ⏭️  Port {port} skipped.")
    print(f"  🛡️  Keeping port 8080 (SearXNG) alive.")


def _acquire_resume_lock(timeout_seconds=5):
    """Cross-platform file lock for --resume. Blocks up to 5s, then fails."""
    pid = str(os.getpid())
    token = f"{pid}:{int(time.time() * 1000)}"
    start = time.time()
    while time.time() - start < timeout_seconds:
        try:
            fd = os.open(RESUME_LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(token)
            return token
        except FileExistsError:
            pass
        time.sleep(0.2)
    return None

def _release_resume_lock(owner_token=None):
    try:
        if owner_token is None:
            os.remove(RESUME_LOCK)
            return True
        with open(RESUME_LOCK, "r", encoding="utf-8") as f:
            current = f.read().strip()
        if current != owner_token:
            return False
        os.remove(RESUME_LOCK)
        return True
    except FileNotFoundError:
        return False


def cmd_resume():
    """Resume the historical host profile from durable BATON_STATE.json.

    The relay path preserves enough state to continue after an intentional
    interruption or recoverable outage; it does not promise unbounded runtime.
    """

    lock_token = _acquire_resume_lock()
    if not lock_token:
        print("❌ Another --resume process is running. Wait and retry.")
        sys.exit(1)
    try:
        baton = StateManager.read_json(BATON_STATE)
        status = baton.get("status", "IDLE")

        if status == "IDLE":
            print("ℹ️  No relay-baton pending. Nothing to resume.")
            return

        print(f"\n{'='*60}")
        print(f" SUDARSHAN V16.9 — Relay-Baton Resume")
        print(f"{'='*60}")
        print(f"  Baton Status:   {status}")
        print(f"  Phase:          {baton.get('current_phase', '?')}")
        print(f"  Relay Count:    {baton.get('relay_count', 0)}")
        print(f"  Session:        {baton.get('session_id', '?')}")
        print(f"  Serialized At:  {baton.get('metadata', {}).get('last_serialized_at', '?')}")
        print(f"  Nodes Complete: {len(baton.get('completed_nodes', []))}")
        print(f"  Nodes Failed:  {len(baton.get('failed_nodes', []))}")
        print(f"  Nodes Pending:  {len(baton.get('pending_nodes', []))}")

        # Check if HaaS is blocking
        bb = StateManager.read_json(BLACKBOARD)
        if bb.get("status") == "BLOCKED_AWAITING_HUMAN":
            print(f"\n  ⚠️  Swarm is BLOCKED awaiting human input.")
            print(f"  Blocker: {bb.get('blocker_description', '?')}")
            print(f"  Write response to: isolated_tasks/HUMAN_INPUT.txt")
            print(f"  Then re-run --resume")

            # If HUMAN_INPUT.txt has content, clear the block
            if os.path.exists(HUMAN_INPUT):
                with open(HUMAN_INPUT, "r", encoding="utf-8") as f:
                    human_data = f.read().strip()
                if human_data:
                    print(f"\n  ✅ Human input detected ({len(human_data)} chars). Clearing block.")
                    bb["status"] = "RESOLVED"
                    bb["metadata"]["last_updated_at"] = StateManager.iso_now()
                    StateManager.write_json(BLACKBOARD, bb)
                else:
                    print(f"  ❌ HUMAN_INPUT.txt is empty. Write your response first.")
                    return

        # Serialize execution state BEFORE overwriting baton
        # PRESERVE all execution progress across relay handoffs
        serialized_context = baton.get("serialized_context", {})
        completed_nodes = baton.get("completed_nodes", [])
        failed_nodes   = baton.get("failed_nodes", [])
        pending_nodes  = baton.get("pending_nodes", [])
        current_task   = baton.get("current_task_node_id")
        relay_count   = baton.get("relay_count", 0)

        # Increment relay counter
        relay_count += 1

        # Write updated BATON_STATE — preserve all execution progress
        StateManager.write_json(BATON_STATE, {
            "baton_version": baton.get("baton_version", "16.9"),
            "status": "RESUMED",
            "current_phase": baton.get("current_phase") or Phase.PHASE_0_RESEARCH.value,
            "current_task_node_id": current_task,
            "completed_nodes": completed_nodes,
            "failed_nodes": failed_nodes,
            "pending_nodes": pending_nodes,
            "serialized_context": serialized_context,
            "relay_count": relay_count,
            "metadata": {
                "created_at": baton.get("metadata", {}).get("created_at"),
                "last_serialized_at": StateManager.iso_now(),
                "resumed_at": StateManager.iso_now(),
                "swarm_session_id": baton.get("metadata", {}).get("swarm_session_id")
            }
        })

        # Refresh .swarm_lock using Phase enum value
        session_id = baton.get("metadata", {}).get("swarm_session_id", f"session_{int(time.time())}")
        phase_str = baton.get("current_phase") or Phase.PHASE_0_RESEARCH.value
        StateManager.write_json(SWARM_LOCK, {
            "last_active_timestamp": int(time.time()),
            "session_id": session_id,
            "phase": phase_str
        })

        # Output the resume payload
        resume_payload = (
            f"RESUME SEQUENCE: Read enterprise_state/BATON_STATE.json, "
            f"enterprise_state/SUPER_PROMPT_MUTATIONS.json (mutations override original assumptions), "
            f"enterprise_state/JIRA_DAG.json, enterprise_state/ARCHITECTURE_STATE.md, "
            f"and enterprise_state/BLACKBOARD_STATUS.json (contains model pricing data). "
            f"You are resuming from {phase_str} "
            f"(relay #{relay_count}). "
            f"Completed nodes: {completed_nodes}. "
            f"Failed nodes: {failed_nodes}. "
            f"Pending nodes: {pending_nodes}. "
            f"Continue execution from current_task: {current_task or 'next pending node'}."
        )
        if os.path.exists(HUMAN_INPUT):
            with open(HUMAN_INPUT, "r", encoding="utf-8") as f:
                hdata = f.read().strip()
            if hdata:
                resume_payload += (
                    f"\n\nHuman input received:\n{hdata}\n"
                    f"Incorporate this and proceed."
                )

        print(f"\n{'='*60}")
        print(f" RESUME PAYLOAD (pass this to your Orchestrator spawn):")
        print(f"{'='*60}")
        print(resume_payload)
        print(f"{'='*60}")
        print(f"\n  ✅ Baton consumed. .swarm_lock refreshed. "
              f"Execution state preserved across {relay_count} relay(s).")
        print(f"  Spawn a fresh Orchestrator with the payload above.\n")
        write_live_status(
            "RESUMED",
            "Relay baton resumed and payload emitted",
            phase=phase_str,
            extra={
                "relay_count": relay_count,
                "current_task": current_task,
            },
        )
    finally:
        _release_resume_lock(lock_token)


# ═══════════════════════════════════════════════════════════════
# PRE-FLIGHT DEPENDENCY CHECK (User Stipulation 2)
# ═══════════════════════════════════════════════════════════════
def pre_flight_check():
    """Verifies Host OS dependencies before allowing swarm to boot."""
    print(f"\n{'='*60}")
    print(f" SUDARSHAN V16.9 — Pre-Flight Target Acquisition Checks")
    print(f"{'='*60}")

    # Check 1: NodeJS
    try:
        r = subprocess.run(["node", "-v"], capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            print(f"  ✅ NodeJS found: {r.stdout.strip()}")
        else:
            raise Exception("Node returned non-zero")
    except Exception:
        print(f"  ❌ NodeJS NOT FOUND. Required for scripts and frontend build.")
        sys.exit(1)

    # Check 2: Docker
    try:
        r = subprocess.run(["docker", "info"], capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            print(f"  ✅ Docker Daemon running")
        else:
            raise Exception("Docker daemon not running")
    except Exception:
        print(f"  ❌ Docker Daemon NOT RUNNING. Start OrbStack/Docker Desktop.")
        sys.exit(1)

    # Check 3: SearXNG
    searxng_url = "http://localhost:8080/healthz"
    try:
        req = urllib.request.Request(searxng_url, method="GET")
        with urllib.request.urlopen(req, timeout=3) as response:
            if response.status == 200:
                 print(f"  ✅ SearXNG endpoint alive on port 8080")
            else:
                 raise Exception(f"SearXNG returned {response.status}")
    except URLError as e:
        print(f"  ❌ SearXNG NOT REACHABLE at localhost:8080. ({e.reason})")
        print(f"     Run: cd infrastructure/searxng && docker-compose up -d")
        sys.exit(1)
    except Exception as e:
        print(f"  ❌ SearXNG connection failed: {e}")
        sys.exit(1)

    print(f"  ✅ Target acquisition complete. Platform is GO for launch.\n")

    print(f"{'='*60}")
    print(f" Budget Enforcement Check")
    print(f"{'='*60}")
    result = BudgetEnforcer.check()
    if result == "EXCEEDED":
        print(f"\n  ❌ SWARM HALTED: Budget exceeded. Override with --force.")
        sys.exit(3)
    print(f"")

# ═══════════════════════════════════════════════════════════════
# BUDGET ENFORCER (C7 — V16.9)
# Reads spend from STRIKE_LEDGER.json and compares against
# budget config in BLACKBOARD_STATUS.json (metadata.budget).
# Emits deterministic signals for the LLM to act upon.
# ═══════════════════════════════════════════════════════════════
class BudgetEnforcer:
    @staticmethod
    def read_budget_config():
        bb = StateManager.read_json(BLACKBOARD, default={})
        metadata = bb.get("metadata", {})
        budget = metadata.get("budget", {})
        return {
            "max_session_usd": budget.get("max_session_token_burn_usd", 10.0),
            "alert_threshold": budget.get("alert_threshold_percent", 80),
            "hard_kill": budget.get("hard_kill_on_exceed", True),
        }

    @staticmethod
    def get_spend():
        ledger = StateManager.read_json(STRIKE_LEDGER, default={})
        return float(ledger.get("total_session_cost_usd", 0.0))

    @staticmethod
    def check():
        cfg = BudgetEnforcer.read_budget_config()
        spend = BudgetEnforcer.get_spend()
        pct = (spend / cfg["max_session_usd"] * 100) if cfg["max_session_usd"] > 0 else 0

        print(f"  Budget: ${spend:.2f} / ${cfg['max_session_usd']:.2f} ({pct:.1f}%)")
        print(f"  Alert threshold: {cfg['alert_threshold']}%")

        if spend >= cfg["max_session_usd"]:
            print(f"[SYSTEM: BUDGET_EXCEEDED] ${spend:.2f} >= ${cfg['max_session_usd']:.2f}")
            print(f"  Hard kill: {cfg['hard_kill']}")
            return "EXCEEDED"
        elif pct >= cfg["alert_threshold"]:
            print(f"[SYSTEM: BUDGET_WARNING] At {pct:.1f}% — threshold is {cfg['alert_threshold']}%")
            return "WARNING"
        else:
            print(f"[BUDGET_OK] ${spend:.2f} / ${cfg['max_session_usd']:.2f} — {pct:.1f}% consumed")
            return "OK"


def cmd_check_budget():
    result = BudgetEnforcer.check()
    if result == "EXCEEDED":
        sys.exit(3)
    sys.exit(0)


# ═══════════════════════════════════════════════════════════════
# CLI ENTRY POINT
# ═══════════════════════════════════════════════════════════════
def main():
    ensure_utf8_stdio()
    p = argparse.ArgumentParser(
        description="SUDARSHAN V16.9 — Task Manager Toolkit",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python3 taskmanager.py --init \"Build AI dating platform\"\n"
            "  python3 taskmanager.py --resume\n"
            "  python3 taskmanager.py --check-gate 1\n"
            "  python3 taskmanager.py --check-gate dag\n"
            "  python3 taskmanager.py --record-strike grunt_SETUP \"npm install failed\"\n"
            "  python3 taskmanager.py --record-cost phase_2 grunt_SETUP 5000 2000\n"
            "  python3 taskmanager.py --invoice\n"
            "  python3 taskmanager.py --status\n"
            "  python3 taskmanager.py --abort\n"
            "  python3 taskmanager.py --cleanup-ports\n"
            "  python3 taskmanager.py --record-search\n"
            "  python3 taskmanager.py --tag-phase 0\n"
            "  python3 taskmanager.py --check-gate-ui-spec\n"
            "  python3 taskmanager.py --check-budget\n"
        ))

    p.add_argument("--init", metavar="DIRECTIVE",
                    help="Bootstrap workspace and compile Super Prompt")
    p.add_argument("--resume", action="store_true",
                    help="Resume from BATON_STATE.json (Relay-Baton)")
    p.add_argument("--check-gate", metavar="N",
                    help="Run gate validator (0,1,2,3,4,dag,ports)")
    p.add_argument("--status", action="store_true",
                    help="Print current system status")
    p.add_argument("--abort", action="store_true",
                    help="Force-delete .swarm_lock and reset blackboard")
    p.add_argument("--record-strike", nargs=2,
                    metavar=("WORKER_ID", "DESCRIPTION"),
                    help="Record a failure strike")
    p.add_argument("--record-staff", metavar="SUMMARY",
                    help="Record a Staff Engineer intervention")
    p.add_argument("--record-pm-rejection", metavar="REASON",
                    help="Record a PM architecture rejection")
    p.add_argument("--record-cost", nargs=4,
                    metavar=("PHASE", "ROLE", "IN_TOKENS", "OUT_TOKENS"),
                    help="Record token usage and cost")
    p.add_argument("--invoice", action="store_true",
                    help="Generate cost invoice")
    p.add_argument("--cleanup-ports", action="store_true",
                    help="Kill dev servers on common ports (Phase 5)")
    p.add_argument("--check-gate-ui-spec", action="store_true",
                    help="Validate UI_SPEC.json schema (Gate 4b)")
    p.add_argument("--record-search", action="store_true",
                    help="Increment Phase 0 search counter (exit 1 on limit)")
    p.add_argument("--tag-phase", metavar="PHASE_NUM",
                    help="Create git tag sudarshan/phaseN-complete")
    p.add_argument("--update-phase", metavar="PHASE_NAME",
                    help="Update current phase in .swarm_lock")
    p.add_argument("--frontend-only", action="store_true",
                    help="Skip API contract gate")
    p.add_argument("--workspace", metavar="DIR",
                    help="Override workspace root directory")
    p.add_argument("--model", metavar="MODEL_ID",
                    help="Model ID for pricing (e.g., claude-3-5-sonnet, gpt-4o)")
    p.add_argument("--preflight", action="store_true",
                    help="Run host dependency checks (Node, Docker, SearXNG) without acquiring a lock")
    p.add_argument("--skip-preflight", action="store_true",
                    help="Skip host dependency checks for offline or degraded smoke tests")
    p.add_argument("--check-budget", action="store_true",
                    help="Check spend vs budget. Exit 0=OK, Exit 3=BUDGET_EXCEEDED")
    p.add_argument("--parallel-info", action="store_true",
                    help="Analyze DAG for parallel execution opportunities")

    args = p.parse_args()

    if args.workspace:
        global WORKSPACE_ROOT, ENTERPRISE_STATE, ISOLATED_TASKS
        global SWARM_LOCK, RESUME_LOCK, JIRA_DAG, STRIKE_LEDGER, BATON_STATE
        global BLACKBOARD, ARCHITECTURE_STATE, HUMAN_INPUT, LIVE_STATUS
        global RESEARCH_MANIFEST, RESEARCH_VERDICT, SUPER_PROMPT_MUTATIONS
        global SCOPE_MANIFEST, UI_SPEC, PM_AUDIT_REPORT
        WORKSPACE_ROOT = os.path.abspath(args.workspace)
        ENTERPRISE_STATE = os.path.join(WORKSPACE_ROOT, "enterprise_state")
        ISOLATED_TASKS = os.path.join(WORKSPACE_ROOT, "isolated_tasks")
        SWARM_LOCK = os.path.join(WORKSPACE_ROOT, ".swarm_lock")
        RESUME_LOCK = os.path.join(WORKSPACE_ROOT, ".resume_lock")
        JIRA_DAG = os.path.join(ENTERPRISE_STATE, "JIRA_DAG.json")
        STRIKE_LEDGER = os.path.join(ENTERPRISE_STATE, "STRIKE_LEDGER.json")
        BATON_STATE = os.path.join(ENTERPRISE_STATE, "BATON_STATE.json")
        BLACKBOARD = os.path.join(ENTERPRISE_STATE, "BLACKBOARD_STATUS.json")
        ARCHITECTURE_STATE = os.path.join(ENTERPRISE_STATE, "ARCHITECTURE_STATE.md")
        RESEARCH_MANIFEST = os.path.join(ENTERPRISE_STATE, "RESEARCH_MANIFEST.json")
        RESEARCH_VERDICT = os.path.join(ENTERPRISE_STATE, "RESEARCH_VERDICT.json")
        SUPER_PROMPT_MUTATIONS = os.path.join(ENTERPRISE_STATE, "SUPER_PROMPT_MUTATIONS.json")
        SCOPE_MANIFEST = os.path.join(ENTERPRISE_STATE, "SCOPE_MANIFEST.json")
        UI_SPEC = os.path.join(ENTERPRISE_STATE, "UI_SPEC.json")
        PM_AUDIT_REPORT = os.path.join(ENTERPRISE_STATE, "PM_AUDIT_REPORT.json")
        HUMAN_INPUT = os.path.join(ISOLATED_TASKS, "HUMAN_INPUT.txt")
        LIVE_STATUS = os.path.join(ISOLATED_TASKS, "live_status.json")

    if args.preflight:
        pre_flight_check()
        return

    if args.check_budget:
        cmd_check_budget()
        return

    if args.init:
        # Pre-flight check before lock acquisition (User Stipulation #2)
        if not args.skip_preflight:
            pre_flight_check()

        # Determine model for pricing (User Stipulation #1)
        model = args.model if args.model else "default"

        # Model is now threaded into cmd_init → compile_super_prompt
        # and injected into blackboard INSIDE cmd_init (before boot payload)
        cmd_init(args.init, args.frontend_only, model_id=model)

    elif args.resume:
        # Pre-flight check before resuming (User Stipulation #2)
        if not args.skip_preflight:
            pre_flight_check()
        cmd_resume()
    elif args.status:
        cmd_status()
    elif args.abort:
        cmd_abort()
    elif args.check_gate is not None:
        try:
            gate = int(args.check_gate)
        except ValueError:
            gate = args.check_gate
        cmd_check_gate(gate, args.frontend_only)
    elif args.record_strike:
        StrikeLedger.record_strike(args.record_strike[0], args.record_strike[1])
    elif args.record_staff:
        StrikeLedger.record_staff_intervention(args.record_staff)
    elif args.record_pm_rejection:
        StrikeLedger.record_pm_rejection(args.record_pm_rejection)
    elif args.record_cost:
        CostTracker.record(args.record_cost[0], args.record_cost[1],
                           int(args.record_cost[2]), int(args.record_cost[3]))
    elif args.invoice:
        CostTracker.invoice()
    elif args.cleanup_ports:
        cmd_cleanup_ports()
    elif args.check_gate_ui_spec:
        results = GateValidator.check_ui_spec()
        all_pass = True
        for desc, passed in results:
            sym = "✅" if passed else "❌"
            print(f"  {sym} {desc}")
            if not passed:
                all_pass = False
        sys.exit(0 if all_pass else 1)
    elif args.record_search:
        # V16.9: Increment Phase 0 search counter
        manifest = StateManager.read_json(RESEARCH_MANIFEST, default={})
        count = manifest.get("search_query_count", 0) + 1
        manifest["search_query_count"] = count
        StateManager.write_json(RESEARCH_MANIFEST, manifest)
        print(f"SEARCH #{count}/{MAX_SEARCH_QUERIES}")
        if count >= MAX_SEARCH_QUERIES:
            print(f"[SYSTEM: PHASE_0_SEARCH_LIMIT_HIT] Run --check-gate 0 immediately.")
            sys.exit(1)
        sys.exit(0)
    elif args.update_phase is not None:
        cmd_update_phase(args.update_phase)
    elif args.tag_phase is not None:
        phase_num = args.tag_phase
        tag_name = f"sudarshan/phase{phase_num}-complete"
        import glob
        print("  Staging verified artifacts for phase snapshot:")
        try:
            # Stage enterprise_state files
            state_files = glob.glob(os.path.join(ENTERPRISE_STATE, "*.json")) + \
                          glob.glob(os.path.join(ENTERPRISE_STATE, "*.md"))
            # Stage all workspace-root execution output scaffolds
            workspace_scaffolds = [
                os.path.join(WORKSPACE_ROOT, "STRICT_CONSTRAINTS.json"),
                os.path.join(WORKSPACE_ROOT, "openapi.yaml"),
                os.path.join(WORKSPACE_ROOT, "PRE_MORTEM.md"),
                os.path.join(WORKSPACE_ROOT, "EXECUTION_PLAN.md"),
                os.path.join(WORKSPACE_ROOT, "EXECUTION_PLAN_V2.md"),
                os.path.join(WORKSPACE_ROOT, "AUTOPSY.md"),
                os.path.join(WORKSPACE_ROOT, "COMPLETION_REPORT.md"),
            ]
            all_staged = state_files + workspace_scaffolds

            for f in all_staged:
                if not os.path.exists(f): continue
                # Intelligent parsing for JSON to avoid committing half-written garbage
                if f.endswith('.json'):
                    try:
                        with open(f, 'r', encoding='utf-8') as fh:
                            json.load(fh)  # Raw parse — raises JSONDecodeError if malformed
                        subprocess.run(["git", "add", f], capture_output=True, cwd=WORKSPACE_ROOT)
                        print(f"   + {os.path.basename(f)}")
                    except (json.JSONDecodeError, Exception) as e:
                        core_files = {"JIRA_DAG.json", "RESEARCH_MANIFEST.json", "SCOPE_MANIFEST.json", "UI_SPEC.json"}
                        if os.path.basename(f) in core_files:
                            print(f"   ❌ FATAL: Core state file {os.path.basename(f)} is corrupt: {e}")
                            sys.exit(1)
                        print(f"   ⏭️ Skipped {os.path.basename(f)} (Malformed/Lockfile)")
                else:
                    # Markdown files (like ARCHITECTURE_STATE.md)
                    subprocess.run(["git", "add", f], capture_output=True, cwd=WORKSPACE_ROOT)
                    print(f"   + {os.path.basename(f)}")

            subprocess.run(["git", "add", "RESEARCH_CACHE/"], capture_output=True, cwd=WORKSPACE_ROOT)

            # Execute snapshot
            subprocess.run(["git", "commit", "-m", f"SUDARSHAN: Phase {phase_num} complete"],
                           capture_output=True, cwd=WORKSPACE_ROOT, timeout=10)
            r = subprocess.run(["git", "tag", tag_name],
                               capture_output=True, text=True, cwd=WORKSPACE_ROOT, timeout=10)
            if r.returncode == 0:
                print(f"✅ Git tag created: {tag_name}")
            else:
                print(f"⚠️  Git tag failed: {r.stderr.strip()}")
        except Exception as e:
            print(f"⚠️  Git tag error: {e}")
    elif args.parallel_info:
        if not os.path.exists(JIRA_DAG):
            print(f"ERROR: DAG not found at {JIRA_DAG}")
            sys.exit(1)
        import subprocess
        result = subprocess.run(
            [sys.executable, os.path.join(os.path.dirname(__file__), "dag_subgraph.py"), "--parallel", JIRA_DAG],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            print(result.stdout)
        else:
            print(f"ERROR: {result.stderr}")
            sys.exit(1)
    else:
        p.print_help()


if __name__ == "__main__":
    main()
