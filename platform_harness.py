#!/usr/bin/env python3
"""Platform-neutral Sudarshan host harness helpers.

This module is intentionally stdlib-only. Agent frameworks can call it directly
to build a Sudarshan-compatible spawn envelope without depending on OpenClaw.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional


DEFAULT_SYSTEM_INTERCEPTS: Dict[str, str] = {
    "[SYSTEM: HAAS_REQUEST]": "spawn_observer",
    "[SYSTEM: RELAY_BATON]": "resume_orchestrator",
    "[SYSTEM: JUDGE_PROBE_READY]": "spawn_judge_probe",
    "[SYSTEM: BUDGET_WARNING]": "notify_l1",
    "[SYSTEM: BUDGET_EXCEEDED]": "halt_swarm",
    "[SYSTEM: TASK_COMPLETE]": "deliver_completion_report",
}

DEFAULT_REQUIRED_CAPABILITIES: List[str] = [
    "spawn_subagent",
    "list_subagents",
    "kill_subagent",
    "kill_all_subagents",
    "stream_output",
    "intercept_system_signals",
    "workspace_filesystem_rw",
    "shell_exec",
]


def _resolve_under_root(root: str, relative_path: str, field_name: str) -> str:
    normalized = os.path.normpath(relative_path)
    if os.path.isabs(normalized):
        raise ValueError(f"{field_name} must be relative to the host root")
    candidate = os.path.abspath(os.path.join(root, normalized))
    root_abs = os.path.abspath(root)
    try:
        common = os.path.commonpath([root_abs, candidate])
    except ValueError as exc:
        raise ValueError(f"{field_name} must stay within the host root") from exc
    if common != root_abs:
        raise ValueError(f"{field_name} must stay within the host root")
    return candidate


def system_intercepts() -> Dict[str, str]:
    return dict(DEFAULT_SYSTEM_INTERCEPTS)


def required_host_capabilities() -> List[str]:
    return list(DEFAULT_REQUIRED_CAPABILITIES)


def build_generic_spawn_request(
    task: str,
    model: str,
    workspace_root: str,
    platform: str = "generic",
    reasoning: str = "max",
    timeout_seconds: int = 3600,
    context_sharing: str = "none",
    denied_tools: Optional[List[str]] = None,
) -> Dict[str, Any]:
    if not task or not task.strip():
        raise ValueError("task is required")
    if not model or not model.strip():
        raise ValueError("model is required")

    deny = list(denied_tools or [])
    if "web_search" not in deny:
        deny.append("web_search")

    return {
        "platform": platform,
        "task": task.strip(),
        "model": model.strip(),
        "runtime": {
            "reasoning": reasoning,
            "timeout_seconds": timeout_seconds,
        },
        "context": {
            "sharing": context_sharing,
            "workspace_root": workspace_root,
            "read_first": [
                "SUDARSHAN.md",
                "enterprise_state/BATON_STATE.json",
                "enterprise_state/SUPER_PROMPT_MUTATIONS.json",
            ],
        },
        "tool_policy": {
            "deny": deny,
        },
        "signals": system_intercepts(),
        "required_capabilities": required_host_capabilities(),
    }


class SudarshanHarness:
    """Filesystem and spawn-envelope helper for any Sudarshan host runtime."""

    def __init__(self, host_root: str, workspace_subdir: str = "workspace"):
        self.host_root = os.path.abspath(host_root)
        self.workspace_root = _resolve_under_root(self.host_root, workspace_subdir, "workspace_subdir")
        self.live_status_path = os.path.join(self.workspace_root, "isolated_tasks", "live_status.json")
        self.human_input_path = os.path.join(self.workspace_root, "isolated_tasks", "HUMAN_INPUT.txt")

    def build_spawn_request(
        self,
        task: str,
        model: str,
        platform: str = "generic",
        reasoning: str = "max",
        timeout_seconds: int = 3600,
        context_sharing: str = "none",
        denied_tools: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        return build_generic_spawn_request(
            task=task,
            model=model,
            workspace_root=self.workspace_root,
            platform=platform,
            reasoning=reasoning,
            timeout_seconds=timeout_seconds,
            context_sharing=context_sharing,
            denied_tools=denied_tools,
        )

    def read_live_status(self) -> Dict[str, Any]:
        if not os.path.exists(self.live_status_path):
            return {
                "status": "idle",
                "message": "No live status available yet",
                "path": self.live_status_path,
            }
        with open(self.live_status_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            raise ValueError("live_status.json must contain a JSON object")
        return data

    def write_live_status(self, payload: Dict[str, Any]) -> None:
        os.makedirs(os.path.dirname(self.live_status_path), exist_ok=True)
        with open(self.live_status_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
            handle.write("\n")

    def write_human_input(self, content: str) -> Dict[str, Any]:
        os.makedirs(os.path.dirname(self.human_input_path), exist_ok=True)
        with open(self.human_input_path, "w", encoding="utf-8") as handle:
            handle.write(content)
        return {"status": "ok", "path": self.human_input_path, "bytes": len(content.encode("utf-8"))}
