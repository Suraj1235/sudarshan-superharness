#!/usr/bin/env python3
"""
SUDARSHAN V16.9 — Observer Node (L0.5 Daemon)

The Observer Node runs as a lightweight polling daemon that:
1. Monitors enterprise_state/ for changes
2. Maintains ARCHITECTURE_STATE.md (the global semantic memory map)
3. Intercepts [SYSTEM: HAAS_REQUEST] signals from the Swarm
4. Attempts to resolve structural/CLI flaws before escalating to L1

Usage:
    python3 observer.py --workspace /path/to/workspace
    python3 observer.py --workspace /path/to/workspace --interval 30
    python3 observer.py --once   # Single check, then exit (for cron)

Dependencies: Python 3.8+ stdlib only (zero external packages).
"""

import os, sys, json, time, argparse, hashlib, tempfile
from datetime import datetime, timezone
from pathlib import Path


# ═══════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════
DEFAULT_POLL_INTERVAL = 30  # seconds
OBSERVER_OWNED_FILES = frozenset({"ARCHITECTURE_STATE.md"})
TRANSIENT_SUFFIXES = (".tmp", ".lock")


class ObserverNode:
    """
    The L0.5 escalation tier. Runs parallel to the Orchestrator.
    Its sole job is to observe execution and maintain the global truth.
    """

    def __init__(self, workspace_root, poll_interval=DEFAULT_POLL_INTERVAL):
        self.workspace = workspace_root
        self.poll_interval = poll_interval
        self.enterprise_state = os.path.join(workspace_root, "enterprise_state")
        self.isolated_tasks = os.path.join(workspace_root, "isolated_tasks")

        # State file paths
        self.architecture_state = os.path.join(self.enterprise_state, "ARCHITECTURE_STATE.md")
        self.strike_ledger = os.path.join(self.enterprise_state, "STRIKE_LEDGER.json")
        self.baton_state = os.path.join(self.enterprise_state, "BATON_STATE.json")
        self.blackboard = os.path.join(self.enterprise_state, "BLACKBOARD_STATUS.json")
        self.jira_dag = os.path.join(self.enterprise_state, "JIRA_DAG.json")
        self.swarm_lock = os.path.join(workspace_root, ".swarm_lock")
        self.live_status = os.path.join(self.isolated_tasks, "live_status.json")

        # Track file hashes for change detection
        self._file_hashes = {}
        self._observation_log = []

    # ── Utility ──
    def _read_json(self, path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _write_json(self, path, data):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)

    def _file_hash(self, path):
        try:
            with open(path, "rb") as f:
                return hashlib.md5(f.read()).hexdigest()
        except FileNotFoundError:
            return None

    def _iso_now(self):
        return datetime.now(timezone.utc).isoformat()

    def _log(self, message):
        entry = f"[{self._iso_now()}] [OBSERVER] {message}"
        try:
            print(entry)
        except UnicodeEncodeError:
            print(entry.encode("ascii", errors="replace").decode("ascii"))
        self._observation_log.append(entry)

    def _strikes_are_consistent_cli_failure(self, strikes):
        """Return True only when recent strike evidence is consistently CLI-level."""
        cli_keywords = ("syntax", "cli", "command not found", "permission denied", "enoent")
        recent = strikes[-3:]
        if len(recent) < 2:
            return False
        return all(
            any(keyword in strike.get("description", "").lower() for keyword in cli_keywords)
            for strike in recent
        )

    # ── Change Detection ──
    def detect_changes(self):
        """Scan enterprise_state/ for file changes since last poll."""
        changes = []
        if not os.path.isdir(self.enterprise_state):
            return changes

        for root, dirs, files in os.walk(self.enterprise_state):
            for fname in files:
                if fname in OBSERVER_OWNED_FILES or fname.endswith(TRANSIENT_SUFFIXES):
                    continue
                fpath = os.path.join(root, fname)
                new_hash = self._file_hash(fpath)
                old_hash = self._file_hashes.get(fpath)
                if new_hash != old_hash:
                    changes.append({
                        "file": fpath,
                        "basename": fname,
                        "type": "modified" if old_hash else "created",
                        "hash": new_hash
                    })
                    self._file_hashes[fpath] = new_hash
        return changes

    # ── Architecture State Maintenance ──
    def update_architecture_state(self, changes):
        """
        Update ARCHITECTURE_STATE.md based on observed changes.
        This is the global semantic memory map that prevents the
        "1-Degree Subgraph Trap" — where Grunts write disjointed code
        because they can't see the full system.
        """
        if not changes:
            return

        # Read current state
        try:
            with open(self.architecture_state, "r", encoding="utf-8") as f:
                content = f.read()
        except (FileNotFoundError, UnicodeDecodeError):
            self._log("ARCHITECTURE_STATE.md corrupted or non-UTF-8 — resetting")
            content = "# ARCHITECTURE STATE\n"

        # Build observation summary
        timestamp = self._iso_now()
        observation = f"\n## Observer Update ({timestamp})\n"

        # Track DAG changes
        dag_changes = [c for c in changes if c["basename"] == "JIRA_DAG.json"]
        if dag_changes:
            dag = self._read_json(self.jira_dag)
            nodes = dag.get("nodes", dag.get("tasks", []))
            if isinstance(nodes, list):
                node_ids = [n.get("id", n.get("task_id", "?")) for n in nodes]
                statuses = {}
                for n in nodes:
                    s = n.get("status", "UNKNOWN")
                    statuses[s] = statuses.get(s, 0) + 1
                observation += f"- **DAG Updated**: {len(nodes)} nodes\n"
                observation += f"  - Status breakdown: {statuses}\n"
                observation += f"  - Node IDs: {', '.join(node_ids[:20])}\n"
            elif isinstance(nodes, dict):
                observation += f"- **DAG Updated**: {len(nodes)} nodes\n"

        # Track strike changes
        strike_changes = [c for c in changes if c["basename"] == "STRIKE_LEDGER.json"]
        if strike_changes:
            ledger = self._read_json(self.strike_ledger)
            observation += (
                f"- **Strike Ledger Updated**: "
                f"{ledger.get('total_strikes', 0)} strikes, "
                f"{ledger.get('total_staff_engineer_interventions', 0)} staff interventions\n"
            )

        # Track baton changes
        baton_changes = [c for c in changes if c["basename"] == "BATON_STATE.json"]
        if baton_changes:
            baton = self._read_json(self.baton_state)
            observation += (
                f"- **Baton State**: {baton.get('status', 'UNKNOWN')} "
                f"(relay #{baton.get('relay_count', 0)})\n"
            )

        # Track generic file changes
        other_changes = [c for c in changes
                        if c["basename"] not in ("JIRA_DAG.json", "STRIKE_LEDGER.json",
                                                  "BATON_STATE.json")]
        for c in other_changes:
            observation += f"- **{c['type'].title()}**: {c['basename']}\n"

        # Append to architecture state
        content += observation

        # [C1 FIX] Atomic write to prevent corruption mid-crash
        tmp_fd, tmp_path = tempfile.mkstemp(
            dir=os.path.dirname(self.architecture_state) or ".",
            suffix=".md.tmp"
        )
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_path, self.architecture_state)

        self._log(f"Architecture state updated with {len(changes)} change(s)")

    # ── Signal Interception ──
    def check_haas_request(self):
        """
        Check if the Swarm has emitted a [SYSTEM: HAAS_REQUEST].
        If so, the Observer attempts to resolve it before escalating to L1.
        """
        blackboard = self._read_json(self.blackboard)
        if blackboard.get("status") != "BLOCKED_AWAITING_HUMAN":
            return False

        self._log(f"⚠️  HaaS Request intercepted: {blackboard.get('blocker_description', 'unknown')}")

        # Attempt resolution based on blocker type
        blocker = blackboard.get("blocker_type", "unknown")
        attempts = blackboard.get("observer_attempts", 0)

        resolved = False

        if blocker == "12_strike":
            # Check if the strike ledger shows a pattern we can fix
            ledger = self._read_json(self.strike_ledger)
            strikes = ledger.get("strikes", [])
            if strikes:
                last_strike = strikes[-1]
                self._log(f"  Analyzing last strike: {last_strike.get('description', 'N/A')}")
                if self._strikes_are_consistent_cli_failure(strikes):
                    self._log("  Identified consistent CLI/bootstrap failure. Resetting strike ledger.")
                    ledger["total_strikes"] = 0
                    ledger["strikes"] = []
                    ledger["total_staff_engineer_interventions"] = 0
                    ledger["staff_interventions"] = []
                    self._write_json(self.strike_ledger, ledger)
                    resolved = True

        if resolved:
            # Touch .swarm_lock to prevent zombie prune from killing the resumed swarm
            lock = self._read_json(self.swarm_lock)
            lock["last_active_timestamp"] = int(time.time())
            self._write_json(self.swarm_lock, lock)
            # Clear the blackboard and signal continuation
            blackboard["status"] = "RESOLVED_BY_OBSERVER"
            blackboard["resolution"] = f"Observer resolved after {attempts + 1} attempt(s)"
            blackboard["observer_attempts"] = attempts + 1
            blackboard["metadata"]["last_updated_at"] = self._iso_now()
            self._write_json(self.blackboard, blackboard)
            self._log("✅ Blocker resolved by Observer. Emitting [SYSTEM: RELAY_BATON]")
            # Write relay signal
            baton = self._read_json(self.baton_state)
            baton["status"] = "RELAY_PENDING"
            self._write_json(self.baton_state, baton)
            return True
        else:
            # Cannot resolve — escalate to L1
            blackboard["observer_attempts"] = attempts + 1
            if attempts >= 2:
                blackboard["escalated_to_l1"] = True
                self._write_json(self.blackboard, blackboard)
                self._log("❌ Observer cannot resolve. Emitting [SYSTEM: L1_ESCALATION]")
            else:
                self._write_json(self.blackboard, blackboard)
                self._log(f"  Observer attempt {attempts + 1} — will retry on next poll")
            return False

    # ── Zombie Detection ──
    def check_zombie_lock(self):
        """Check for stale .swarm_lock files."""
        if not os.path.exists(self.swarm_lock):
            return
        lock = self._read_json(self.swarm_lock)
        age = int(time.time()) - lock.get("last_active_timestamp", 0)
        phase = lock.get("phase", "phase_0_research")
        # Phase-aware grace periods (must match HEARTBEAT.md PHASE_GRACE)
        grace = {"phase_0_research": 900, "phase_1_contract": 900,
                 "phase_2_execution": 900, "phase_3_cicd": 900,
                 "phase_4_integration": 900, "phase_5_delivery": 5400,
                 "completed": 60, "halted": 60}.get(phase, 900)
        if age > grace:
            self._log(f"🧟 Zombie lock detected (age: {age}s, phase: {phase}). Flagging for cleanup.")

    # ── Main Loop ──
    def run_once(self):
        """Execute a single observation cycle."""
        if not os.path.exists(self.swarm_lock):
            return  # No active swarm — nothing to observe

        changes = self.detect_changes()
        if changes:
            self.update_architecture_state(changes)

        self.check_haas_request()
        self.check_zombie_lock()

    def run(self):
        """Run the observer daemon continuously."""
        self._log(f"Observer Node (L0.5) starting. Polling every {self.poll_interval}s")
        self._log(f"Workspace: {self.workspace}")

        # Initialize file hashes
        self.detect_changes()

        try:
            while True:
                self.run_once()
                time.sleep(self.poll_interval)
        except KeyboardInterrupt:
            self._log("Observer Node stopped by user.")


def main():
    parser = argparse.ArgumentParser(
        description="SUDARSHAN V16.9 — Observer Node (L0.5 Daemon)"
    )
    parser.add_argument("--workspace", default=os.getcwd(),
                        help="Workspace root directory")
    parser.add_argument("--interval", type=int, default=DEFAULT_POLL_INTERVAL,
                        help=f"Poll interval in seconds (default: {DEFAULT_POLL_INTERVAL})")
    parser.add_argument("--once", action="store_true",
                        help="Run a single observation cycle and exit")

    args = parser.parse_args()
    observer = ObserverNode(
        workspace_root=os.path.abspath(args.workspace),
        poll_interval=args.interval
    )

    if args.once:
        observer.run_once()
    else:
        observer.run()


if __name__ == "__main__":
    main()
