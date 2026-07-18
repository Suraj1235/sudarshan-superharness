# SUDARSHAN V16.9 LEGACY MULTI-AGENT PROTOCOL PROFILE

> **Status: experimental reference architecture.** This document preserves the
> original multi-agent operating model developed before the standalone engine.
> It is not evidence that every described role or phase is automated today.
> The supported turnkey path is `sudarshan estimate`, `sudarshan build`, and
> `sudarshan resume`; see `README.md`. OpenClaw is optional compatibility only.

## 1. IDENTITY & GOAL
- **Identity:** An experimental role-and-gate protocol for coordinating long-running LLM engineering work.
- **Goal:** Help capable models attempt large software builds with durable state, scoped context, explicit checks, and recoverable execution. Production readiness remains a verification target, not a guarantee.
- **Portability:** The core runtime is host-neutral. OpenClaw is supported through an adapter, but any LLM API harness or agent framework can integrate by satisfying `PLATFORM_CONTRACT.md`.

## 2. CLEARANCES & INVOCATION
- **Authorized Users:** L1 ONLY.
- **Trigger:** `/taskmanager [Prompt]` -> Main Thread runs Super Prompt Cross-Check (Self-Critique for logic gaps) before locking `.swarm_lock` and spawning Chief Orchestrator.


## 2.5 THE OBSERVER NODE (L0.5)
In compatible host runtimes, the Observer Node can run as an L0.5 structural monitor. It records state changes and routes known CLI-level escalation patterns; it does not semantically prove or automatically repair arbitrary architecture defects.

## 3. ENTERPRISE MECHANICS & SURVIVAL (M2 HARDWARE OPTIMIZED)
- **The JIRA DAG (Dependency Matrix):** State is tracked in `enterprise_state/JIRA_DAG.json`. Deterministic validation checks cycles, missing dependencies, and readiness rules.
- **1-Degree Subgraph Context Loading (Context Trimming):** Compatible multi-agent hosts can use `python3 dag_subgraph.py <path_to_dag> <target_node_id>` to reduce context sent to a worker. This reduces token use but cannot eliminate all context loss.
- **Context Discipline (Anti-Bleed Mandate):** When spawning any sub-agent (Red Team, PM Node, Staff Engineer), the Orchestrator MUST manually construct the context payload. Sub-agents receive ONLY their assigned Grunt's output files + the 1-degree subgraph context. Full session history injection is BANNED. If the underlying agent framework supports automatic context sharing or memory inheritance (e.g., OpenClaw's `contextSharing`), the Orchestrator MUST explicitly disable it (e.g., `contextSharing: "none"`) and rely solely on the manually constructed `task` payload. Native platform compaction or auto-summarization of SUDARSHAN's `enterprise_state/` files is strictly FORBIDDEN — SUDARSHAN manages its own state lifecycle.
- **Active Lease-Based File Mutexes (.lock):** Shared states require a JSON `.lock` file containing an `expires_at` timestamp (180 seconds TTL). Executing agents MUST spawn a background thread to ping/touch the lock if streaming takes >180s. Expired locks are aggressively stolen.
- **Shallow Git Snapshots:** To prevent IO spikes and workspace bloat, global commits (`git add .`) are BANNED. The Swarm MUST use `safe_edit.py --greenlight` to execute `git add <specific_file> && git commit -m "Autosave"` ONLY on files actively touched after a Red Team Green Light.
- **Lazy Zombie Prune:** Main Thread lazily checks `last_active_timestamp` every 5 mins. If >15m old, issues `subagents(action="kill")` before purging `.swarm_lock`.

## 4. THE V16.9 STATE MACHINE

### Phase 0: The Research & Scope Engine (Extreme Credit Efficiency)
- **The Web Recon Mandate:** The native `web_search` tool is strictly BANNED. The Research Engine MUST exclusively use `node skills/os_search/search.js "query"` connected to our self-hosted SearXNG (localhost:8080). **CRITICAL:** Grunts MUST extract the raw target URLs from the search output and ONLY execute `web_fetch` on those external links. `web_fetch` on the `localhost:8080` SearXNG endpoint itself is strictly BANNED (prevents RAG poisoning with UI elements).
- **Unified Model Execution:** The Swarm MUST exclusively use the specific model category provided by the L1 User during invocation. Model cascading (switching to cheaper/faster models for basic tasks) is strictly BANNED. The reasoning depth must remain mathematically consistent across all phases.
- **Structured Research Playbook:** The Orchestrator MUST follow the `research-commander` skill (`skills/research-commander/SKILL.md`) and produce `enterprise_state/RESEARCH_MANIFEST.json` containing stack versions, compatibility findings, env key discovery, anti-patterns, and deployment constraints. Freestyling research queries without the playbook is BANNED.
- **Map-Reduce Constraints:** For payloads >5k tokens, the Research Engine MUST first run a Map-Reduce pass to extract all absolute business rules into `STRICT_CONSTRAINTS.json`. Remaining text is cached via structured markdown in the `RESEARCH_CACHE/` directory, organized by topic. Files are selectively loaded by the Orchestrator and Grunts as needed.
- **Super Prompt Mutations:** If Phase 0 research invalidates any assumption in the original Super Prompt, the Orchestrator MUST record the amendment in `enterprise_state/SUPER_PROMPT_MUTATIONS.json`. On relay-baton resume, the Orchestrator reads mutations BEFORE reading `JIRA_DAG.json`.
- **Phase 0 Limits:** Research is capped by `MAX_SEARCH_QUERIES` (default: 40) and `MAX_PHASE_0_DURATION_SECONDS` (default: 3600). When either limit is hit, the Orchestrator MUST immediately run `taskmanager.py --check-gate 0`. The HEARTBEAT daemon enforces the time ceiling.
- **Scope Validation:** Before Phase 0 exits, the PM Node MUST run the `scope-validator` skill and produce `enterprise_state/SCOPE_MANIFEST.json`. If estimated DAG nodes > 15, the PM MUST force a scope reduction (80/20 rule).
- **Judge Probe:** At Phase 0 completion, the Main Thread spawns a single-turn Judge Probe sub-agent to evaluate `RESEARCH_MANIFEST.json` completeness. The Judge produces `enterprise_state/RESEARCH_VERDICT.json` with verdict: `LOCK_PHASE_0` | `EXPAND_RESEARCH` | `ESCALATE_TO_L1`. Gate 0 (`taskmanager.py --check-gate 0`) validates this verdict.
- **Env Key Discovery:** The Orchestrator populates `env_manifest` in `RESEARCH_MANIFEST.json` during Phase 0. If any keys have `provided: false`, a HaaS ping fires immediately at Phase 0 end — before Phase 1 begins — giving the human the entirety of Phase 1 to respond.
- **Phase Boundary Snapshot:** After Gate 0 passes, the Orchestrator MUST run `taskmanager.py --tag-phase 0` to create a `sudarshan/phase0-complete` git tag. This protects research from being nuked by Phase 1 failures.

### Phase 1: Contract-First & Architecture Guardrails
- **Gate 1: The Git Foundation & Strike Ledger:** The PM Node's absolute first atomic task MUST be generating a stack-specific `.gitignore`. Next, it MUST physically create the state directory (`mkdir -p enterprise_state/`) and initialize `enterprise_state/STRIKE_LEDGER.json` to permanently track LLM failure strikes and bypass token amnesia.
- **Gate 2: Pre-Mortem & Adversarial QA:** Before finalizing the `EXECUTION_PLAN.md` and DAG, the Orchestrator MUST evaluate task complexity. If >2 DAG nodes or >3 files, the PM Node MUST write an adversarial `PRE_MORTEM.md` detailing a 100k-user system crash against the Orchestrator's `EXECUTION_PLAN.md`. The Orchestrator then reads `PRE_MORTEM.md` and self-patches its execution plan into `EXECUTION_PLAN_V2.md`. The architect CANNOT audit their own blueprint (Anchoring Bias).
- **Gate 3: PM Architecture Audit (2-Strike Rule):** The PM runs the `architecture-auditor` skill and produces `enterprise_state/PM_AUDIT_REPORT.json` with steps AA1-AA5. Each step must be PASS/WARN/FAIL with evidence. Exit Code 1 rejections are logged in `STRIKE_LEDGER.json`. 3rd rejection → HaaS to Observer Node.
- **Gate 4: The Contract Absolute Gate:** *(MVP BYPASS: If the architecture is a frontend-only MVP without a custom backend API, skip this gate entirely)*. Otherwise, the PM Node MUST generate `openapi.yaml` and a data contract artifact (`schema.prisma` if Prisma is chosen, otherwise `DATA_CONTRACT.md` or an equivalent stack-specific contract). Phase 1 CANNOT lock until `npx @stoplight/spectral-cli lint openapi.yaml` deterministically returns Exit Code 0.
- **Gate 4b: Frontend Contract Validation:** `taskmanager.py --check-gate-ui-spec` validates `enterprise_state/UI_SPEC.json` structure — pages defined, design system populated, component library selected, all referenced components exist.
- **Delta-Debate (Structured):** Creative Director proposes `UI_SPEC_DRAFT.json` → PM critiques in `DELTA_CRITIQUE_1.json` → CD revises in `UI_SPEC_V2.json` → PM issues `DELTA_RULING.json` (ACCEPT/ACCEPT_WITH_MODS/REJECT). SHORT-CIRCUIT: If PM accepts in Round 2, skip to lock. 5th round = escalation to Orchestrator.
- **Phase 1 Boundary Snapshot:** After all gates pass, the Orchestrator MUST run `taskmanager.py --tag-phase 1` to create a `sudarshan/phase1-complete` git tag.

### Phase 2: Polyglot Horizontal Squad Execution (RAM Strangulation)
- **DAG Deadlock Validation:** Before execution begins, `JIRA_DAG.json` MUST pass `python3 dag_validator.py`. Validates against circular dependencies AND dangling/missing dependencies.
- **Native Docker / OrbStack Directive:** Docker Desktop is strictly BANNED due to VM bloat. Ephemeral DBs must run on Native Docker Engine (if Ubuntu/Linux) or OrbStack (if macOS) to save ~2GB of idle RAM.
- **Sequential Dev Booting:** The Orchestrator is BANNED from running frontend and backend `npm run dev` servers concurrently until Phase 4.
- **Port 8080 Constraint:** Port 8080 is strictly reserved for SUDARSHAN's internal SearXNG cluster. Grunts MUST NEVER bind any generated application or mock server to port 8080. Default to 3000, 3001, 4000, or 5000.
- **Strict Mocking:** The Frontend Squad MUST exclusively rely on a lightweight local mock server (like Prism) running off the Spectral-validated `openapi.yaml`. No live DB connections until Integration Gate.
- **Playwright Singleton:** The Playwright visual QA script MUST be hardcoded to instantly `browser.close()` the moment a screenshot is taken.
- **SWE-Agent ACI Mandate:** Grunts write code ONLY via `python3 safe_edit.py` (which physically enforces the mutex lock on all edits).

### Phase 3: CI/CD & The 12-Strike Macro-Breaker
- **Ephemeral DDL Isolation:** `BEGIN; ROLLBACK;` is banned for DB tests. CI/CD MUST spin up isolated, ephemeral Docker Postgres containers per Squad.
- **Staff Engineer Escalation:** If a Grunt fails a build/test 3 times, it freezes. Red Team writes `AUTOPSY.md`. Staff Engineer sequentially executes the fix via `safe_edit.py`.
- **12-Strike Ceiling:** Failures are explicitly logged in `STRIKE_LEDGER.json`. Four Staff Engineer interventions trigger a graceful halt and `[SYSTEM: HAAS_REQUEST]`. The Swarm serializes state, writes `RECOVERY_MANIFEST.json`, and preserves every tracked and untracked file. Any destructive rollback requires explicit operator approval.
- **Interaction-Aware QA:** Playwright tests wait 15s-30s dynamically. Full-page screenshots and Vision AI calls are ONLY triggered on failed Playwright assertions or visual-diff regressions.

### Phase 4: Integration Gate & HaaS
- **True E2E Integration Gate:** Mocks are BANNED in Phase 4. DevOps Squad spins up Ephemeral DB + Actual Backend + Actual Frontend. Playwright QA agents execute full user journey.
- **HaaS (Human as a Service):** If blocked by CAPTCHA/Auth, serialize to `BATON_STATE.json`, update Blackboard, and terminate.

### Phase 5: Delivery
- **DevSecOps:** Swarm writes standard GitHub Actions workflows and `docker-compose.prod.yml`.
- **The Strict Cleanup Mandate:** Do NOT kill processes while ongoing. Only when verified, the Orchestrator MUST identify all local dev servers and gracefully kill their process trees using explicit Port-Based Kills (`npx kill-port <PORT>`). `kill -9` on wrapper shell scripts is BANNED to prevent zombie node children from binding ports.
- **Completion:** Output `[SYSTEM: TASK_COMPLETE]`. Main Thread deletes root `.swarm_lock` and delivers invoice/screenshots to L1.
