#!/usr/bin/env python3
"""Patch a supported OpenClaw agent config with Sudarshan hooks."""

from __future__ import annotations

import json
import os
from typing import Any, Dict

from protocol_assets import load_install_manifest, load_version


def _read_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _write_json(path: str, data: Dict[str, Any]) -> None:
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
        handle.write("\n")
    os.replace(tmp_path, path)


def _normalize_relative_subdir(value: str, field_name: str) -> str:
    if not value:
        raise ValueError(f"{field_name} must not be empty")
    normalized = os.path.normpath(value).replace("/", os.sep)
    if os.path.isabs(normalized) or normalized.startswith("..") or os.path.normpath(normalized) == ".":
        raise ValueError(f"{field_name} must stay within agent root: {value}")
    return normalized


def _plugin_names() -> list[str]:
    manifest = load_install_manifest()
    names: list[str] = []
    for relative_path in manifest["required_openclaw_plugin_files"]:
        names.append(os.path.splitext(os.path.basename(relative_path))[0])
    return names


def build_patched_config(config: Dict[str, Any], install_subdir: str = "sudarshan", workspace_subdir: str = "workspace") -> Dict[str, Any]:
    version = load_version()
    install_subdir = _normalize_relative_subdir(install_subdir, "install_subdir")
    workspace_subdir = _normalize_relative_subdir(workspace_subdir, "workspace_subdir")

    config.setdefault("identity", {})
    config["identity"].update({
        "router_rules_path": f"{install_subdir}/IDENTITY.md",
        "persona_path": f"{install_subdir}/SOUL.md",
        "user_policy_path": f"{install_subdir}/USER.md",
        "heartbeat_path": f"{install_subdir}/HEARTBEAT.md",
    })

    config.setdefault("sudarshan", {})
    config["sudarshan"].update({
        "enabled": True,
        "version": version,
        "install_root": install_subdir,
        "workspace_root": workspace_subdir,
        "managed_by": "Sudarshan installer",
    })

    config.setdefault("commands", {})
    config["commands"].update({
        "/taskmanager": {
            "handler": "openclaw_router_bridge.handle_taskmanager",
            "workspace_root": workspace_subdir,
        },
        "!status": {
            "handler": "openclaw_router_bridge.handle_status",
            "workspace_root": workspace_subdir,
        },
        "!input": {
            "handler": "openclaw_router_bridge.handle_input",
            "workspace_root": workspace_subdir,
        },
    })

    config.setdefault("system_intercepts", {})
    config["system_intercepts"].update({
        "[SYSTEM: HAAS_REQUEST]": "spawn_observer",
        "[SYSTEM: RELAY_BATON]": "resume_orchestrator",
        "[SYSTEM: JUDGE_PROBE_READY]": "spawn_judge_probe",
        "[SYSTEM: BUDGET_WARNING]": "notify_l1",
        "[SYSTEM: BUDGET_EXCEEDED]": "halt_swarm",
        "[SYSTEM: TASK_COMPLETE]": "deliver_completion_report",
    })

    config.setdefault("tool_policy_defaults", {})
    deny_list = config["tool_policy_defaults"].setdefault("deny", [])
    if "web_search" not in deny_list:
        deny_list.append("web_search")

    plugins = config.setdefault("plugins", [])
    for plugin_name in _plugin_names():
        if plugin_name not in plugins:
            plugins.append(plugin_name)

    return config


def patch_agent(agent_root: str, install_subdir: str = "sudarshan", workspace_subdir: str = "workspace") -> Dict[str, Any]:
    agent_config_path = os.path.join(agent_root, "agent_config.json")
    if not os.path.exists(agent_config_path):
        raise FileNotFoundError(f"Unsupported agent root: missing {agent_config_path}")

    config = _read_json(agent_config_path)
    patched = build_patched_config(config, install_subdir=install_subdir, workspace_subdir=workspace_subdir)
    _write_json(agent_config_path, patched)
    return patched
