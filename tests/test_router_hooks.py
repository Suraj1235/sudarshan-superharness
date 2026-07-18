#!/usr/bin/env python3
"""Tests for OpenClaw router bridge hooks."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest


REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")
FIXTURE_ROOT = os.path.join(os.path.dirname(__file__), "fixtures", "openclaw_blank_agent")
sys.path.insert(0, REPO_ROOT)

from openclaw_router_bridge import (  # type: ignore
    handle_input,
    handle_status,
    parse_taskmanager_command,
)


class TestRouterHooks(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.agent_root = os.path.join(self.temp_dir, "agent")
        shutil.copytree(FIXTURE_ROOT, self.agent_root)
        install_result = subprocess.run(
            [
                sys.executable,
                "install.py",
                "--agent-root",
                self.agent_root,
                "--noninteractive",
                "--skip-searxng",
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if install_result.returncode != 0:
            raise RuntimeError(install_result.stderr or install_result.stdout)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_parse_taskmanager_command_extracts_model_and_directive(self):
        parsed = parse_taskmanager_command('/taskmanager gpt-4o Build a dashboard')
        self.assertEqual(parsed["model"], "gpt-4o")
        self.assertEqual(parsed["directive"], "Build a dashboard")

    def test_handle_input_writes_human_input_file(self):
        result = handle_input(self.agent_root, '!input Approved continue')
        self.assertEqual(result["status"], "ok")
        with open(result["path"], "r", encoding="utf-8") as handle:
            self.assertEqual(handle.read().strip(), "Approved continue")

    def test_handle_status_reads_live_status(self):
        live_status_path = os.path.join(self.agent_root, "workspace", "isolated_tasks", "live_status.json")
        os.makedirs(os.path.dirname(live_status_path), exist_ok=True)
        with open(live_status_path, "w", encoding="utf-8") as handle:
            json.dump({"phase": "phase_1_contract", "summary": "working"}, handle)
        result = handle_status(self.agent_root)
        self.assertEqual(result["phase"], "phase_1_contract")


if __name__ == "__main__":
    unittest.main()
