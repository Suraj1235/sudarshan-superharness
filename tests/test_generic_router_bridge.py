#!/usr/bin/env python3
"""Tests for framework-neutral Sudarshan router bridge."""

import json
import os
import shutil
import sys
import tempfile
import unittest


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from generic_router_bridge import (  # type: ignore
    handle_input,
    handle_launch,
    handle_status,
    parse_launch_command,
)


class TestGenericRouterBridge(unittest.TestCase):
    def setUp(self):
        self.agent_root = tempfile.mkdtemp()
        self.workspace = os.path.join(self.agent_root, "workspace")
        os.makedirs(os.path.join(self.workspace, "isolated_tasks"), exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.agent_root, ignore_errors=True)

    def test_parse_launch_command_accepts_sudarshan_and_taskmanager_aliases(self):
        self.assertEqual(
            parse_launch_command('/sudarshan gpt-5 "Build a fintech app"'),
            {"model": "gpt-5", "directive": "Build a fintech app"},
        )
        self.assertEqual(
            parse_launch_command('/taskmanager "Build a dashboard"'),
            {"model": "default", "directive": "Build a dashboard"},
        )
        self.assertEqual(
            parse_launch_command("/taskmanager Build a dashboard"),
            {"model": "default", "directive": "Build a dashboard"},
        )
        self.assertEqual(
            parse_launch_command("/sudarshan --model local/qwen Build a dashboard"),
            {"model": "local/qwen", "directive": "Build a dashboard"},
        )

    def test_handle_launch_returns_neutral_spawn_request(self):
        result = handle_launch(self.agent_root, "/sudarshan gpt-5 Build a dashboard")

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["command"], "/sudarshan")
        self.assertEqual(result["workspace_root"], self.workspace)
        self.assertEqual(result["spawn_request"]["platform"], "generic")
        self.assertEqual(result["spawn_request"]["model"], "gpt-5")
        self.assertEqual(result["spawn_request"]["context"]["workspace_root"], self.workspace)

    def test_handle_status_and_input_use_workspace_files(self):
        status_path = os.path.join(self.workspace, "isolated_tasks", "live_status.json")
        with open(status_path, "w", encoding="utf-8") as handle:
            json.dump({"status": "BOOTSTRAPPED"}, handle)

        self.assertEqual(handle_status(self.agent_root)["status"], "BOOTSTRAPPED")

        result = handle_input(self.agent_root, "!input Ship the smallest useful core")
        self.assertEqual(result["status"], "ok")
        with open(os.path.join(self.workspace, "isolated_tasks", "HUMAN_INPUT.txt"), encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "Ship the smallest useful core")


if __name__ == "__main__":
    unittest.main()
