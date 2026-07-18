#!/usr/bin/env python3
"""Project the standalone engine's canonical state into Sudarshan protocol files."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict

from protocol_assets import install_required_templates, load_version


def _read_json(path: Path) -> Dict[str, object]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _write_json_atomic(path: Path, data: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            delete=False,
            dir=str(path.parent),
            prefix=f".{path.name}.",
            suffix=".tmp",
        ) as handle:
            temp_name = handle.name
            json.dump(data, handle, indent=2, ensure_ascii=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if temp_name and os.path.exists(temp_name):
            os.unlink(temp_name)


class ProtocolStateBridge:
    """Keep legacy protocol artifacts as projections, not a second lifecycle."""

    def __init__(self, workspace_root: str) -> None:
        self.workspace = Path(workspace_root).resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.enterprise = self.workspace / "enterprise_state"
        self.isolated = self.workspace / "isolated_tasks"
        self.enterprise.mkdir(parents=True, exist_ok=True)
        self.isolated.mkdir(parents=True, exist_ok=True)
        (self.workspace / "RESEARCH_CACHE").mkdir(parents=True, exist_ok=True)
        install_required_templates(str(self.workspace), overwrite=False)

    @staticmethod
    def _phase(state: Dict[str, object]) -> str:
        status = state.get("status")
        if status == "COMPLETED":
            return "completed"
        if status in {"FAILED", "BUDGET_EXCEEDED", "MAX_STEPS"}:
            return "halted"
        if state.get("verification_commands"):
            return "phase_4_integration"
        if state.get("plan"):
            return "phase_2_execution"
        return "phase_1_contract"

    def sync(self, state: Dict[str, object]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        phase = self._phase(state)
        usage = dict(state.get("usage") or {})

        blackboard_path = self.enterprise / "BLACKBOARD_STATUS.json"
        blackboard = _read_json(blackboard_path)
        metadata = blackboard.setdefault("metadata", {})
        metadata["model"] = state.get("model")
        metadata["phase"] = phase
        metadata["engine"] = "standalone"
        metadata["engine_id"] = state.get("engine_id")
        metadata["last_updated_at"] = now
        metadata["usage"] = usage
        blackboard["blackboard_version"] = load_version()
        blackboard["status"] = state.get("status")
        blackboard["blocker_type"] = (
            "HUMAN_INPUT" if state.get("status") == "WAITING_HUMAN" else None
        )
        blackboard["blocker_description"] = (
            (state.get("human_request") or {}).get("question")
            if state.get("status") == "WAITING_HUMAN"
            else state.get("last_error")
        )
        _write_json_atomic(blackboard_path, blackboard)

        plan = state.get("plan") or []
        if plan:
            dag = {
                "dag_version": load_version(),
                "description": "Canonical plan projected from .sudarshan/engine_state.json",
                "source": ".sudarshan/engine_state.json",
                "nodes": [
                    {
                        "id": task["id"],
                        "squad": "standalone-engine",
                        "description": task["description"],
                        "dependencies": list(task.get("depends_on") or []),
                        "status": str(task["status"]).upper(),
                    }
                    for task in plan
                ],
            }
            _write_json_atomic(self.enterprise / "JIRA_DAG.json", dag)

        ledger_path = self.enterprise / "STRIKE_LEDGER.json"
        ledger = _read_json(ledger_path)
        ledger["ledger_version"] = load_version()
        ledger["total_session_cost_usd"] = float(usage.get("cost_usd", 0.0))
        ledger["standalone_engine_usage"] = {
            "input_tokens": int(usage.get("input_tokens", 0)),
            "output_tokens": int(usage.get("output_tokens", 0)),
            "cost_usd": float(usage.get("cost_usd", 0.0)),
            "last_updated_at": now,
        }
        _write_json_atomic(ledger_path, ledger)

        live_status = {
            "timestamp": int(datetime.now(timezone.utc).timestamp()),
            "iso_timestamp": now,
            "status": state.get("status"),
            "phase": phase,
            "message": state.get("last_error") or f"Standalone engine step {state.get('step', 0)}",
            "engine_id": state.get("engine_id"),
            "step": state.get("step", 0),
        }
        _write_json_atomic(self.isolated / "live_status.json", live_status)


__all__ = ["ProtocolStateBridge"]
