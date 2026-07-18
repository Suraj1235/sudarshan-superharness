#!/usr/bin/env python3
"""End-to-end certification test for a fresh OpenClaw agent install."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest


REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")
FIXTURE_ROOT = os.path.join(os.path.dirname(__file__), "fixtures", "openclaw_blank_agent")


class TestFreshAgentCertification(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.agent_root = os.path.join(self.temp_dir, "agent")
        shutil.copytree(FIXTURE_ROOT, self.agent_root)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_blank_agent_can_install_verify_and_bootstrap_workspace(self):
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
        self.assertEqual(install_result.returncode, 0, msg=install_result.stderr or install_result.stdout)

        verify_result = subprocess.run(
            [sys.executable, "verify_installation.py", "--workspace", self.agent_root],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(verify_result.returncode, 0, msg=verify_result.stderr or verify_result.stdout)

        install_root = os.path.join(self.agent_root, "sudarshan")
        workspace_root = os.path.join(self.agent_root, "workspace")
        env = os.environ.copy()
        env["SUDARSHAN_WORKSPACE"] = workspace_root
        init_result = subprocess.run(
            [
                sys.executable,
                "taskmanager.py",
                "--workspace",
                workspace_root,
                "--skip-preflight",
                "--frontend-only",
                "--model",
                "default",
                "--init",
                "Build a demo app",
            ],
            cwd=install_root,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(init_result.returncode, 0, msg=init_result.stderr or init_result.stdout)

        blackboard_path = os.path.join(workspace_root, "enterprise_state", "BLACKBOARD_STATUS.json")
        pre_mortem_path = os.path.join(workspace_root, "PRE_MORTEM.md")
        with open(blackboard_path, "r", encoding="utf-8") as handle:
            blackboard = json.load(handle)
        self.assertEqual(blackboard["metadata"]["model"], "default")

        with open(pre_mortem_path, "r", encoding="utf-8") as handle:
            self.assertIn("# PRE-MORTEM", handle.read())

        live_status_path = os.path.join(workspace_root, "isolated_tasks", "live_status.json")
        with open(live_status_path, "r", encoding="utf-8") as handle:
            live_status = json.load(handle)
        self.assertEqual(live_status["status"], "BOOTSTRAPPED")


if __name__ == "__main__":
    unittest.main()
