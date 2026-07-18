#!/usr/bin/env python3
"""Fresh-agent install tests."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest


REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")
FIXTURE_ROOT = os.path.join(os.path.dirname(__file__), "fixtures", "openclaw_blank_agent")


class TestInstallFreshAgent(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.agent_root = os.path.join(self.temp_dir, "agent")
        shutil.copytree(FIXTURE_ROOT, self.agent_root)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_install_seeds_sudarshan_overlay_and_router_hooks(self):
        result = subprocess.run(
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
        self.assertEqual(result.returncode, 0, msg=result.stderr or result.stdout)

        install_root = os.path.join(self.agent_root, "sudarshan")
        self.assertTrue(os.path.exists(os.path.join(install_root, "VERSION")))
        self.assertTrue(os.path.exists(os.path.join(install_root, "openclaw_plugins", "patch_identity.json")))

        with open(os.path.join(self.agent_root, "agent_config.json"), "r", encoding="utf-8") as handle:
            config = json.load(handle)

        self.assertTrue(config["sudarshan"]["enabled"])
        self.assertIn("/taskmanager", config["commands"])
        self.assertIn("!status", config["commands"])
        self.assertIn("!input", config["commands"])
        self.assertIn("spawn_subagent", config["plugins"])

    def test_install_rolls_back_when_agent_config_is_invalid(self):
        broken_config = os.path.join(self.agent_root, "agent_config.json")
        with open(broken_config, "w", encoding="utf-8") as handle:
            handle.write("{ this is not valid json")

        result = subprocess.run(
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

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(os.path.exists(os.path.join(self.agent_root, "sudarshan", "VERSION")))


if __name__ == "__main__":
    unittest.main()
