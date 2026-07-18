#!/usr/bin/env python3
"""Tests for taskmanager workspace bootstrap."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from protocol_assets import load_version  # type: ignore


class TestTaskmanagerInit(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self._old_workspace = os.environ.get("SUDARSHAN_WORKSPACE")
        os.environ["SUDARSHAN_WORKSPACE"] = self.temp_dir

    def tearDown(self):
        if self._old_workspace is None:
            os.environ.pop("SUDARSHAN_WORKSPACE", None)
        else:
            os.environ["SUDARSHAN_WORKSPACE"] = self._old_workspace
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _run_cmd_init(self, directive="Build a demo dashboard", model_id="default"):
        env = os.environ.copy()
        env["SUDARSHAN_WORKSPACE"] = self.temp_dir
        result = subprocess.run(
            [
                sys.executable,
                "taskmanager.py",
                "--workspace",
                self.temp_dir,
                "--skip-preflight",
                "--frontend-only",
                "--model",
                model_id,
                "--init",
                directive,
            ],
            cwd=os.path.join(os.path.dirname(__file__), ".."),
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr or result.stdout)

    def test_cmd_init_seeds_nonempty_workspace_templates(self):
        self._run_cmd_init()

        pre_mortem = os.path.join(self.temp_dir, "PRE_MORTEM.md")
        architecture_state = os.path.join(self.temp_dir, "enterprise_state", "ARCHITECTURE_STATE.md")
        strict_constraints = os.path.join(self.temp_dir, "STRICT_CONSTRAINTS.json")
        live_status = os.path.join(self.temp_dir, "isolated_tasks", "live_status.json")

        with open(pre_mortem, "r", encoding="utf-8") as handle:
            self.assertIn("# PRE-MORTEM", handle.read())

        with open(architecture_state, "r", encoding="utf-8") as handle:
            content = handle.read()
        self.assertIn(load_version(), content)

        with open(strict_constraints, "r", encoding="utf-8") as handle:
            self.assertEqual(json.load(handle), [])

        with open(live_status, "r", encoding="utf-8") as handle:
            status = json.load(handle)
        self.assertEqual(status["phase"], "phase_0_research")
        self.assertEqual(status["status"], "BOOTSTRAPPED")

    def test_cmd_init_blackboard_uses_budget_template(self):
        self._run_cmd_init(model_id="gpt-4o")

        blackboard = os.path.join(self.temp_dir, "enterprise_state", "BLACKBOARD_STATUS.json")
        with open(blackboard, "r", encoding="utf-8") as handle:
            data = json.load(handle)

        self.assertEqual(data["blackboard_version"], load_version())
        self.assertEqual(data["metadata"]["model"], "gpt-4o")
        self.assertEqual(data["metadata"]["budget"]["max_session_token_burn_usd"], 10.0)


if __name__ == "__main__":
    unittest.main()
