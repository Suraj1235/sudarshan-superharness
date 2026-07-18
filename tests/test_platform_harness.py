#!/usr/bin/env python3
"""Tests for platform-neutral Sudarshan host harness helpers."""

import json
import os
import shutil
import sys
import tempfile
import unittest


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from platform_harness import (  # type: ignore
    SudarshanHarness,
    build_generic_spawn_request,
    required_host_capabilities,
    system_intercepts,
)


class TestPlatformHarness(unittest.TestCase):
    def setUp(self):
        self.agent_root = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.agent_root, "workspace", "isolated_tasks"), exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.agent_root, ignore_errors=True)

    def test_build_generic_spawn_request_is_platform_neutral(self):
        request = build_generic_spawn_request(
            task="Build a production dashboard",
            model="gpt-5-pro",
            workspace_root="/workspace",
            platform="custom-agent-runtime",
        )

        self.assertEqual(request["task"], "Build a production dashboard")
        self.assertEqual(request["model"], "gpt-5-pro")
        self.assertEqual(request["platform"], "custom-agent-runtime")
        self.assertEqual(request["runtime"]["timeout_seconds"], 3600)
        self.assertEqual(request["runtime"]["reasoning"], "max")
        self.assertEqual(request["context"]["sharing"], "none")
        self.assertEqual(request["context"]["workspace_root"], "/workspace")
        self.assertIn("web_search", request["tool_policy"]["deny"])
        self.assertEqual(request["signals"]["[SYSTEM: RELAY_BATON]"], "resume_orchestrator")
        self.assertIn("spawn_subagent", request["required_capabilities"])

    def test_workspace_root_cannot_escape_agent_root(self):
        for unsafe_path in (
            "../outside",
            "..\\outside",
            "/tmp/outside",
            "\\outside",
            "C:\\outside",
        ):
            with self.subTest(path=unsafe_path), self.assertRaises(ValueError):
                SudarshanHarness(self.agent_root, workspace_subdir=unsafe_path)

    def test_workspace_root_normalizes_both_separator_styles(self):
        harness = SudarshanHarness(
            self.agent_root, workspace_subdir="nested\\workspace"
        )
        self.assertEqual(
            harness.workspace_root,
            os.path.join(os.path.realpath(self.agent_root), "nested", "workspace"),
        )

    def test_status_and_human_input_helpers(self):
        harness = SudarshanHarness(self.agent_root)
        payload = {"status": "BOOTSTRAPPED", "phase": "phase_0_research"}
        harness.write_live_status(payload)

        self.assertEqual(harness.read_live_status(), payload)

        result = harness.write_human_input("Use PostgreSQL, not SQLite")
        self.assertEqual(result["status"], "ok")
        self.assertGreater(result["bytes"], 0)
        with open(harness.human_input_path, "r", encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "Use PostgreSQL, not SQLite")

    def test_contract_helpers_are_json_serializable(self):
        payload = {
            "required_capabilities": required_host_capabilities(),
            "system_intercepts": system_intercepts(),
        }
        self.assertIn("spawn_subagent", payload["required_capabilities"])
        self.assertIn("[SYSTEM: HAAS_REQUEST]", payload["system_intercepts"])
        json.dumps(payload)


if __name__ == "__main__":
    unittest.main()
