#!/usr/bin/env python3
"""Install Sudarshan into a supported OpenClaw agent root."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile

from openclaw_patcher import build_patched_config, patch_agent
from protocol_assets import (
    copy_required_bundle_directories,
    copy_required_plugin_files,
    copy_required_root_files,
    ensure_required_directories,
    load_version,
)


def _print(msg: str) -> None:
    print(msg)


def _stage_install_tree(stage_root: str) -> None:
    ensure_required_directories(stage_root)
    copy_required_root_files(stage_root, overwrite=True)
    copy_required_plugin_files(stage_root, overwrite=True)
    copy_required_bundle_directories(stage_root, overwrite=True)


def _replace_tree(source: str, destination: str) -> None:
    backup_path = None
    if os.path.exists(destination):
        backup_path = destination + ".bak"
        if os.path.exists(backup_path):
            shutil.rmtree(backup_path)
        os.replace(destination, backup_path)
    try:
        os.replace(source, destination)
    except Exception:
        if backup_path and os.path.exists(backup_path) and not os.path.exists(destination):
            os.replace(backup_path, destination)
        raise
    else:
        if backup_path and os.path.exists(backup_path):
            shutil.rmtree(backup_path, ignore_errors=True)


def install_into_agent(agent_root: str, skip_searxng: bool = False) -> int:
    agent_root = os.path.abspath(agent_root)
    agent_config_path = os.path.join(agent_root, "agent_config.json")
    if not os.path.exists(agent_config_path):
        _print(f"ERROR: Unsupported agent root (missing agent_config.json): {agent_root}")
        return 1

    try:
        with open(agent_config_path, "r", encoding="utf-8") as handle:
            config = json.load(handle)
        build_patched_config(config, install_subdir="sudarshan", workspace_subdir="workspace")
    except Exception as exc:
        _print(f"ERROR: Invalid or unsupported agent_config.json: {exc}")
        return 1

    install_root = os.path.join(agent_root, "sudarshan")
    workspace_root = os.path.join(agent_root, "workspace")
    os.makedirs(workspace_root, exist_ok=True)
    stage_root = tempfile.mkdtemp(prefix="sudarshan-stage-", dir=agent_root)

    try:
        _stage_install_tree(stage_root)
        patch_agent(agent_root, install_subdir="sudarshan", workspace_subdir="workspace")
        _replace_tree(stage_root, install_root)
    except Exception as exc:
        shutil.rmtree(stage_root, ignore_errors=True)
        _print(f"ERROR: Install failed: {exc}")
        return 1

    _print(f"Installed Sudarshan {load_version()} into {install_root}")
    _print(f"Workspace ready at {workspace_root}")
    if skip_searxng:
        _print("SearXNG provisioning skipped by request.")
    else:
        _print("NOTE: SearXNG provisioning is not automated yet; verify Docker/runtime manually.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Install Sudarshan into a fresh OpenClaw agent")
    parser.add_argument("--agent-root", required=True, help="Path to the OpenClaw agent root")
    parser.add_argument("--noninteractive", action="store_true", help="Reserved for future use")
    parser.add_argument("--repair", action="store_true", help="Reserved for future use")
    parser.add_argument("--with-searxng", action="store_true", help="Reserved for future use")
    parser.add_argument("--skip-searxng", action="store_true", help="Skip SearXNG provisioning")
    parser.add_argument("--dry-run", action="store_true", help="Validate arguments without writing files")
    args = parser.parse_args()

    if args.dry_run:
        print(f"DRY RUN: would install Sudarshan {load_version()} into {os.path.abspath(args.agent_root)}")
        return 0

    return install_into_agent(args.agent_root, skip_searxng=args.skip_searxng and not args.with_searxng)


if __name__ == "__main__":
    sys.exit(main())
