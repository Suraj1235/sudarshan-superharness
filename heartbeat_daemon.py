#!/usr/bin/env python3
"""Lifecycle watchdog for Sudarshan workspaces."""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from protocol_assets import load_template_json


MAX_PHASE_0_DURATION_SECONDS = 3600
DEFAULT_POLL_INTERVAL = 30


class HeartbeatDaemon:
    def __init__(self, workspace_root: str, poll_interval: int = DEFAULT_POLL_INTERVAL):
        self.workspace_root = os.path.abspath(workspace_root)
        self.poll_interval = poll_interval
        self.enterprise_state = os.path.join(self.workspace_root, "enterprise_state")
        self.swarm_lock = os.path.join(self.workspace_root, ".swarm_lock")
        self.blackboard = os.path.join(self.enterprise_state, "BLACKBOARD_STATUS.json")
        self.strike_ledger = os.path.join(self.enterprise_state, "STRIKE_LEDGER.json")

    def _iso_now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _read_json(
        self, path: str, default: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        try:
            with open(path, "r", encoding="utf-8") as handle:
                return json.load(handle)
        except (FileNotFoundError, json.JSONDecodeError):
            return {} if default is None else default

    def _write_json(self, path: str, data: Dict[str, Any]) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp_path = path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
            handle.write("\n")
        os.replace(tmp_path, path)

    def _load_blackboard(self) -> Dict[str, Any]:
        return self._read_json(
            self.blackboard,
            default=load_template_json("enterprise_state/BLACKBOARD_STATUS.json"),
        )

    def _load_ledger(self) -> Dict[str, Any]:
        return self._read_json(
            self.strike_ledger,
            default=load_template_json("enterprise_state/STRIKE_LEDGER.json"),
        )

    def check_phase_timeout(self, current_epoch: Optional[int] = None) -> bool:
        if not os.path.exists(self.swarm_lock):
            return False

        current_epoch = int(time.time()) if current_epoch is None else current_epoch
        lock = self._read_json(self.swarm_lock, default={})
        if lock.get("phase") != "phase_0_research":
            return False

        created_at = int(lock.get("created_at") or lock.get("last_active_timestamp") or current_epoch)
        if current_epoch - created_at < MAX_PHASE_0_DURATION_SECONDS:
            return False

        blackboard = self._load_blackboard()
        blackboard["status"] = "PHASE_TIMEOUT"
        blackboard["event"] = "[SYSTEM: PHASE_TIMEOUT]"
        blackboard["blocker_type"] = "phase_timeout"
        blackboard["blocker_description"] = "Phase 0 exceeded time limit"
        if blackboard.get("metadata") is None:
            blackboard["metadata"] = {}
        blackboard["metadata"]["last_updated_at"] = self._iso_now()
        self._write_json(self.blackboard, blackboard)
        return True

    def check_budget(self) -> str:
        blackboard = self._load_blackboard()
        ledger = self._load_ledger()
        if blackboard.get("metadata") is None:
            blackboard["metadata"] = {}
        metadata = blackboard["metadata"]
        if metadata.get("budget") is None:
            metadata["budget"] = {
                "max_session_token_burn_usd": 10.0,
                "alert_threshold_percent": 80,
                "hard_kill_on_exceed": True,
            }
        budget = metadata["budget"]
        spend = float(ledger.get("total_session_cost_usd", 0.0))
        max_budget = float(budget.get("max_session_token_burn_usd", 10.0))
        threshold = float(budget.get("alert_threshold_percent", 80))
        pct = (spend / max_budget * 100) if max_budget > 0 else 0.0

        if spend >= max_budget:
            blackboard["status"] = "BUDGET_EXCEEDED"
            blackboard["event"] = "[SYSTEM: BUDGET_EXCEEDED]"
            blackboard["blocker_type"] = "budget"
            blackboard["blocker_description"] = "Session budget exceeded"
            metadata["last_updated_at"] = self._iso_now()
            self._write_json(self.blackboard, blackboard)
            return "EXCEEDED"

        if pct >= threshold:
            blackboard["status"] = "BUDGET_WARNING"
            blackboard["event"] = "[SYSTEM: BUDGET_WARNING]"
            blackboard["blocker_type"] = "budget"
            blackboard["blocker_description"] = "Session budget approaching limit"
            metadata["last_updated_at"] = self._iso_now()
            self._write_json(self.blackboard, blackboard)
            return "WARNING"

        return "OK"

    def run_once(self, current_epoch: Optional[int] = None) -> None:
        if self.check_phase_timeout(current_epoch=current_epoch):
            return
        self.check_budget()

    def run(self) -> None:
        while True:
            self.run_once()
            time.sleep(self.poll_interval)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Sudarshan heartbeat lifecycle daemon")
    parser.add_argument("--workspace", default=os.getcwd(), help="Workspace root")
    parser.add_argument("--interval", type=int, default=DEFAULT_POLL_INTERVAL, help="Poll interval in seconds")
    parser.add_argument("--once", action="store_true", help="Run a single heartbeat cycle and exit")
    args = parser.parse_args()

    daemon = HeartbeatDaemon(args.workspace, poll_interval=args.interval)
    if args.once:
        daemon.run_once()
        return 0
    daemon.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
