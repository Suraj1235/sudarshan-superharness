#!/usr/bin/env python3
"""Read-only verifier for the Sudarshan source tree or installed agents."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import urllib.request
from urllib.error import URLError
from typing import Dict, Iterable, Tuple

from protocol_assets import load_install_manifest, load_version


EXPECTED_COMMAND_HANDLERS = {
    "/taskmanager": "openclaw_router_bridge.handle_taskmanager",
    "!status": "openclaw_router_bridge.handle_status",
    "!input": "openclaw_router_bridge.handle_input",
}

EXPECTED_INTERCEPTS = {
    "[SYSTEM: HAAS_REQUEST]": "spawn_observer",
    "[SYSTEM: RELAY_BATON]": "resume_orchestrator",
    "[SYSTEM: JUDGE_PROBE_READY]": "spawn_judge_probe",
    "[SYSTEM: BUDGET_WARNING]": "notify_l1",
    "[SYSTEM: BUDGET_EXCEEDED]": "halt_swarm",
    "[SYSTEM: TASK_COMPLETE]": "deliver_completion_report",
}


def ensure_utf8_stdio() -> None:
    if sys.platform != "win32":
        return
    import io

    if hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "buffer"):
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


def ok(msg: str) -> None:
    print(f"  OK: {msg}")


def warn(msg: str) -> None:
    print(f"  WARN: {msg}")


def fail(msg: str) -> None:
    print(f"  FAIL: {msg}")


def _read_json(path: str) -> Dict:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _check_paths(base_root: str, relative_paths: Iterable[str]) -> Tuple[int, int]:
    errors = 0
    warnings = 0
    for relative_path in relative_paths:
        path = os.path.join(base_root, relative_path)
        if os.path.exists(path):
            ok(relative_path)
        else:
            fail(f"missing {relative_path}")
            errors += 1
    return errors, warnings


def _resolve_under_root(root: str, relative_path: str) -> str:
    candidate = os.path.abspath(os.path.join(root, relative_path))
    common = os.path.commonpath([os.path.abspath(root), candidate])
    if common != os.path.abspath(root):
        raise ValueError(f"Path escapes root: {relative_path}")
    return candidate


def _detect_mode(root: str) -> str:
    if os.path.exists(os.path.join(root, "agent_config.json")):
        return "agent"
    if os.path.exists(os.path.join(root, "install_manifest.json")) and os.path.exists(os.path.join(root, "taskmanager.py")):
        return "source"
    return "unknown"


def validate_source_tree(root: str) -> int:
    manifest = load_install_manifest()
    errors = 0
    warnings = 0
    print("\n============================================================")
    print(f" Sudarshan {load_version()} - Source Tree Verification")
    print(f" Root: {root}")
    print("============================================================\n")

    for section_name, paths in (
        ("Core files", manifest["required_root_files"]),
        ("Template files", manifest["required_template_files"]),
        ("Plugin files", manifest["required_openclaw_plugin_files"]),
    ):
        print(f"{section_name}:")
        section_errors, section_warnings = _check_paths(root, paths)
        errors += section_errors
        warnings += section_warnings
        print("")

    for directory in manifest.get("required_bundle_directories", []):
        if os.path.isdir(os.path.join(root, directory)):
            ok(f"directory {directory}/")
        else:
            fail(f"missing directory {directory}/")
            errors += 1

    if shutil.which("python") or shutil.which("python3"):
        ok("Python available")
    else:
        fail("Python missing from PATH")
        errors += 1

    if shutil.which("node"):
        ok("Node.js available")
    else:
        warn("Node.js missing from PATH")
        warnings += 1

    print("\nVerification complete.")
    print(f"Errors: {errors}  Warnings: {warnings}\n")
    return 1 if errors else 0


def validate_installed_agent(root: str) -> int:
    manifest = load_install_manifest()
    errors = 0
    warnings = 0
    print("\n============================================================")
    print(f" Sudarshan {load_version()} - Installed Agent Verification")
    print(f" Agent root: {root}")
    print("============================================================\n")

    config_path = os.path.join(root, "agent_config.json")
    try:
        config = _read_json(config_path)
        ok("agent_config.json parse")
    except Exception as exc:  # pragma: no cover - catastrophic path
        fail(f"agent_config.json unreadable: {exc}")
        return 1

    sudarshan = config.get("sudarshan") or {}
    install_subdir = sudarshan.get("install_root", "sudarshan")
    workspace_subdir = sudarshan.get("workspace_root", "workspace")
    try:
        install_root = _resolve_under_root(root, install_subdir)
        workspace_root = _resolve_under_root(root, workspace_subdir)
    except ValueError as exc:
        fail(str(exc))
        return 1

    if sudarshan.get("enabled") is True:
        ok("Sudarshan enabled in agent config")
    else:
        fail("Sudarshan not enabled in agent config")
        errors += 1

    if sudarshan.get("version") == load_version():
        ok("Installed version matches source version")
    else:
        fail("Installed version mismatch")
        errors += 1

    install_errors, install_warnings = _check_paths(install_root, manifest["required_root_files"])
    errors += install_errors
    warnings += install_warnings

    template_errors, template_warnings = _check_paths(install_root, manifest["required_template_files"])
    errors += template_errors
    warnings += template_warnings

    plugin_errors, plugin_warnings = _check_paths(install_root, manifest["required_openclaw_plugin_files"])
    errors += plugin_errors
    warnings += plugin_warnings

    for directory in manifest.get("required_bundle_directories", []):
        bundle_path = os.path.join(install_root, directory)
        if os.path.isdir(bundle_path):
            ok(f"installed bundle directory {directory}/")
        else:
            fail(f"missing installed bundle directory {directory}/")
            errors += 1

    identity = config.get("identity") or {}
    expected_identity = {
        "router_rules_path": f"{install_subdir}/IDENTITY.md",
        "persona_path": f"{install_subdir}/SOUL.md",
        "user_policy_path": f"{install_subdir}/USER.md",
        "heartbeat_path": f"{install_subdir}/HEARTBEAT.md",
    }
    for key, expected in expected_identity.items():
        if identity.get(key) == expected:
            ok(f"identity mapping {key}")
        else:
            fail(f"identity mapping {key} mismatch")
            errors += 1

    commands = config.get("commands") or {}
    for command_name, expected_handler in EXPECTED_COMMAND_HANDLERS.items():
        command = commands.get(command_name)
        if not command:
            fail(f"missing command hook {command_name}")
            errors += 1
        elif command.get("handler") != expected_handler:
            fail(f"command hook {command_name} handler mismatch")
            errors += 1
        else:
            ok(f"command hook {command_name}")

    intercepts = config.get("system_intercepts") or {}
    for signal, expected_action in EXPECTED_INTERCEPTS.items():
        if intercepts.get(signal) == expected_action:
            ok(f"system intercept {signal}")
        else:
            fail(f"missing or incorrect system intercept {signal}")
            errors += 1

    deny_list = ((config.get("tool_policy_defaults") or {}).get("deny") or [])
    if "web_search" in deny_list:
        ok("web_search denied by default tool policy")
    else:
        fail("web_search not denied by default tool policy")
        errors += 1

    if os.path.isdir(workspace_root):
        ok(f"workspace directory present: {workspace_subdir}/")
    else:
        fail(f"missing workspace directory: {workspace_subdir}/")
        errors += 1

    if shutil.which("node"):
        ok("runtime dependency available: node")
    else:
        warn("runtime dependency missing: node")
        warnings += 1

    if shutil.which("docker"):
        try:
            result = shutil.which("docker")
            proc = __import__("subprocess").run([result, "info"], capture_output=True, text=True, timeout=5)
            if proc.returncode == 0:
                ok("runtime dependency available: docker daemon")
            else:
                warn("runtime dependency degraded: docker daemon not responding")
                warnings += 1
        except Exception:
            warn("runtime dependency degraded: docker daemon check failed")
            warnings += 1
    else:
        warn("runtime dependency missing: docker")
        warnings += 1

    try:
        req = urllib.request.Request("http://localhost:8080/healthz", method="GET")
        with urllib.request.urlopen(req, timeout=3) as response:
            if response.status == 200:
                ok("runtime dependency available: SearXNG health endpoint")
            else:
                warn("runtime dependency degraded: SearXNG health endpoint returned non-200")
                warnings += 1
    except URLError:
        warn("runtime dependency degraded: SearXNG not reachable on localhost:8080")
        warnings += 1
    except Exception:
        warn("runtime dependency degraded: SearXNG health check failed")
        warnings += 1

    plugins = config.get("plugins") or []
    expected_plugins = [os.path.splitext(os.path.basename(p))[0] for p in manifest["required_openclaw_plugin_files"]]
    for plugin_name in expected_plugins:
        if plugin_name in plugins:
            ok(f"plugin registered: {plugin_name}")
        else:
            fail(f"missing registered plugin: {plugin_name}")
            errors += 1

    print("\nVerification complete.")
    print(f"Errors: {errors}  Warnings: {warnings}\n")
    return 1 if errors else 0


def main() -> int:
    ensure_utf8_stdio()
    parser = argparse.ArgumentParser(description="Read-only verifier for Sudarshan source trees and installed agents")
    parser.add_argument("--workspace", default=".", help="Path to the Sudarshan source tree or installed agent root")
    args = parser.parse_args()

    root = os.path.abspath(args.workspace)
    mode = _detect_mode(root)
    if mode == "source":
        return validate_source_tree(root)
    if mode == "agent":
        return validate_installed_agent(root)

    fail(f"Could not detect verification mode for {root}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
