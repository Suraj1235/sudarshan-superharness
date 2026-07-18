#!/usr/bin/env python3
"""Small router bridge for Sudarshan command hooks inside a patched OpenClaw agent."""

from __future__ import annotations

import json
import os
import shlex
from typing import Any, Dict

from openclaw_adapter import OpenClawAdapter


def parse_taskmanager_command(raw_command: str) -> Dict[str, str]:
    parts = shlex.split(raw_command)
    if not parts or parts[0] != "/taskmanager":
        raise ValueError("Command must start with /taskmanager")
    if len(parts) < 2:
        raise ValueError("Directive is required")
    if len(parts) >= 3:
        return {"model": parts[1], "directive": " ".join(parts[2:])}
    return {"model": "default", "directive": parts[1]}


def handle_taskmanager(agent_root: str, raw_command: str) -> Dict[str, Any]:
    parsed = parse_taskmanager_command(raw_command)
    adapter = OpenClawAdapter(agent_root)
    return {
        "status": "ok",
        "command": "/taskmanager",
        "workspace_root": adapter.workspace_root,
        "spawn_request": adapter.build_spawn_request(
            task=parsed["directive"],
            model=parsed["model"],
        ),
    }


def handle_status(agent_root: str) -> Dict[str, Any]:
    adapter = OpenClawAdapter(agent_root)
    if not os.path.exists(adapter.live_status_path):
        return {
            "status": "idle",
            "message": "No live status available yet",
            "path": adapter.live_status_path,
        }
    with open(adapter.live_status_path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("live_status.json must contain a JSON object")
    return data


def handle_input(agent_root: str, raw_command: str) -> Dict[str, Any]:
    parts = shlex.split(raw_command)
    if not parts or parts[0] != "!input":
        raise ValueError("Command must start with !input")
    payload = " ".join(parts[1:]).strip()
    if not payload:
        raise ValueError("!input requires data")
    adapter = OpenClawAdapter(agent_root)
    adapter.write_human_input(payload)
    return {"status": "ok", "path": adapter.human_input_path, "bytes": len(payload.encode("utf-8"))}
