#!/usr/bin/env python3
"""Framework-neutral command bridge for Sudarshan hosts."""

from __future__ import annotations

import shlex
import re
from typing import Any, Dict

from platform_harness import SudarshanHarness


LAUNCH_COMMANDS = {"/sudarshan", "/taskmanager", "sudarshan", "taskmanager"}


def _looks_like_model(value: str) -> bool:
    lowered = value.lower()
    if lowered == "default" or "/" in value or ":" in value:
        return True
    return bool(
        re.match(
            r"^(?:gpt|o\d|claude|gemini|llama|mistral|deepseek|qwen|command|phi|codestral)[a-z0-9._-]*$",
            lowered,
        )
    )


def parse_launch_command(raw_command: str) -> Dict[str, str]:
    parts = shlex.split(raw_command)
    if not parts or parts[0] not in LAUNCH_COMMANDS:
        raise ValueError("Command must start with /sudarshan or /taskmanager")
    if len(parts) < 2:
        raise ValueError("Directive is required")
    if parts[1] in {"--model", "-m"}:
        if len(parts) < 4:
            raise ValueError("--model requires a model and directive")
        return {"model": parts[2], "directive": " ".join(parts[3:])}
    if parts[1].startswith("--model="):
        model = parts[1].split("=", 1)[1]
        if not model or len(parts) < 3:
            raise ValueError("--model requires a model and directive")
        return {"model": model, "directive": " ".join(parts[2:])}
    if len(parts) >= 3 and _looks_like_model(parts[1]):
        return {"model": parts[1], "directive": " ".join(parts[2:])}
    return {"model": "default", "directive": " ".join(parts[1:])}


def handle_launch(host_root: str, raw_command: str) -> Dict[str, Any]:
    parsed = parse_launch_command(raw_command)
    command = shlex.split(raw_command)[0]
    harness = SudarshanHarness(host_root)
    return {
        "status": "ok",
        "command": command,
        "workspace_root": harness.workspace_root,
        "spawn_request": harness.build_spawn_request(
            task=parsed["directive"],
            model=parsed["model"],
            platform="generic",
        ),
    }


def handle_status(host_root: str) -> Dict[str, Any]:
    return SudarshanHarness(host_root).read_live_status()


def handle_input(host_root: str, raw_command: str) -> Dict[str, Any]:
    parts = shlex.split(raw_command)
    if not parts or parts[0] != "!input":
        raise ValueError("Command must start with !input")
    payload = " ".join(parts[1:]).strip()
    if not payload:
        raise ValueError("!input requires data")
    return SudarshanHarness(host_root).write_human_input(payload)
