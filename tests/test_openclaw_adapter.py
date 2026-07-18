#!/usr/bin/env python3
"""Tests for the OpenClaw adapter helpers."""

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

from openclaw_adapter import OpenClawAdapter  # type: ignore


class TestOpenClawAdapter(unittest.TestCase):
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

    def test_build_spawn_request_applies_sudarshan_policy_defaults(self):
        adapter = OpenClawAdapter(self.agent_root)
        request = adapter.build_spawn_request("Audit the DAG", model="gpt-4o")

        self.assertEqual(request["task"], "Audit the DAG")
        self.assertEqual(request["model"], "gpt-4o")
        self.assertEqual(request["thinking"], "max")
        self.assertEqual(request["contextSharing"], "none")
        self.assertIn("web_search", request["toolPolicy"]["deny"])

    def test_intercept_lookup_uses_agent_config(self):
        adapter = OpenClawAdapter(self.agent_root)
        self.assertEqual(adapter.intercept_action("[SYSTEM: TASK_COMPLETE]"), "deliver_completion_report")

    def test_live_status_and_human_input_write_to_workspace(self):
        adapter = OpenClawAdapter(self.agent_root)
        adapter.write_live_status({"timestamp": 1234, "phase": "phase_1_contract"})
        adapter.write_human_input("Approved. Continue.")

        with open(adapter.live_status_path, "r", encoding="utf-8") as handle:
            live_status = json.load(handle)
        self.assertEqual(live_status["phase"], "phase_1_contract")

        with open(adapter.human_input_path, "r", encoding="utf-8") as handle:
            human_input = handle.read().strip()
        self.assertEqual(human_input, "Approved. Continue.")

    def test_workspace_path_cannot_escape_agent_root(self):
        config_path = os.path.join(self.agent_root, "agent_config.json")
        with open(config_path, "r", encoding="utf-8") as handle:
            config = json.load(handle)
        config["sudarshan"]["workspace_root"] = "..\\escaped_workspace"
        with open(config_path, "w", encoding="utf-8") as handle:
            json.dump(config, handle, indent=2)
            handle.write("\n")

        with self.assertRaises(ValueError):
            OpenClawAdapter(self.agent_root)

    def test_command_handler_uses_bridge_targets(self):
        adapter = OpenClawAdapter(self.agent_root)
        handler = adapter.command_handler("/taskmanager")
        self.assertEqual(handler["handler"], "openclaw_router_bridge.handle_taskmanager")


if __name__ == "__main__":
    unittest.main()
