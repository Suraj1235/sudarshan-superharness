#!/usr/bin/env python3
"""Helpers for interacting with a patched OpenClaw agent install."""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

from platform_harness import SudarshanHarness


def _resolve_workspace_root(agent_root: str, workspace_subdir: str) -> str:
    normalized = os.path.normpath(workspace_subdir)
    if os.path.isabs(normalized):
        raise ValueError("workspace_root must be relative to the agent root")
    workspace_root = os.path.abspath(os.path.join(agent_root, normalized))
    agent_root_abs = os.path.abspath(agent_root)
    try:
        common = os.path.commonpath([agent_root_abs, workspace_root])
    except ValueError as exc:
        raise ValueError("workspace_root must stay within the agent root") from exc
    if common != agent_root_abs:
        raise ValueError("workspace_root must stay within the agent root")
    return workspace_root


class OpenClawAdapter:
    def __init__(self, agent_root: str):
        self.agent_root = os.path.abspath(agent_root)
        self.config_path = os.path.join(self.agent_root, "agent_config.json")
        if not os.path.exists(self.config_path):
            raise FileNotFoundError(f"Missing agent_config.json under {self.agent_root}")
        self.config = self._read_json(self.config_path)
        sudarshan = self.config.get("sudarshan") or {}
        workspace_subdir = sudarshan.get("workspace_root", "workspace")
        self._harness = SudarshanHarness(self.agent_root, workspace_subdir=workspace_subdir)
        self.workspace_root = self._harness.workspace_root
        self.live_status_path = os.path.join(self.workspace_root, "isolated_tasks", "live_status.json")
        self.human_input_path = os.path.join(self.workspace_root, "isolated_tasks", "HUMAN_INPUT.txt")

    def _read_json(self, path: str) -> Dict[str, Any]:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)

    def _write_json(self, path: str, data: Dict[str, Any]) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
            handle.write("\n")

    def build_spawn_request(
        self,
        task: str,
        model: str,
        thinking: str = "max",
        timeout_seconds: int = 3600,
        context_sharing: str = "none",
    ) -> Dict[str, Any]:
        deny = list(((self.config.get("tool_policy_defaults") or {}).get("deny") or []))
        neutral = self._harness.build_spawn_request(
            task=task,
            model=model,
            platform="openclaw",
            reasoning=thinking,
            timeout_seconds=timeout_seconds,
            context_sharing=context_sharing,
            denied_tools=deny,
        )
        return {
            "task": neutral["task"],
            "model": neutral["model"],
            "thinking": neutral["runtime"]["reasoning"],
            "timeoutSeconds": neutral["runtime"]["timeout_seconds"],
            "toolPolicy": neutral["tool_policy"],
            "contextSharing": neutral["context"]["sharing"],
        }

    def intercept_action(self, signal: str) -> Optional[str]:
        return (self.config.get("system_intercepts") or {}).get(signal)

    def command_handler(self, command_name: str) -> Optional[Dict[str, Any]]:
        return (self.config.get("commands") or {}).get(command_name)

    def write_live_status(self, payload: Dict[str, Any]) -> None:
        self._harness.write_live_status(payload)

    def write_human_input(self, content: str) -> None:
        self._harness.write_human_input(content)
