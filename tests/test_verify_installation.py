#!/usr/bin/env python3
"""Verification tests for installed Sudarshan agents."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest


REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")
FIXTURE_ROOT = os.path.join(os.path.dirname(__file__), "fixtures", "openclaw_blank_agent")


def _snapshot_files(root):
    paths = []
    for current_root, _, files in os.walk(root):
        for name in files:
            path = os.path.join(current_root, name)
            rel = os.path.relpath(path, root)
            with open(path, "rb") as handle:
                content = handle.read()
            paths.append((rel, os.path.getsize(path), hash(content)))
    return sorted(paths)


class TestVerifyInstallation(unittest.TestCase):
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

    def test_verify_read_only_mode_does_not_mutate_install(self):
        before = _snapshot_files(self.agent_root)
        result = subprocess.run(
            [sys.executable, "verify_installation.py", "--workspace", self.agent_root],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
        after = _snapshot_files(self.agent_root)

        self.assertEqual(result.returncode, 0, msg=result.stderr or result.stdout)
        self.assertEqual(before, after)

    def test_verify_fails_when_router_handler_is_wrong(self):
        config_path = os.path.join(self.agent_root, "agent_config.json")
        with open(config_path, "r", encoding="utf-8") as handle:
            config = json.load(handle)
        config["commands"]["/taskmanager"]["handler"] = "broken_handler"
        with open(config_path, "w", encoding="utf-8") as handle:
            json.dump(config, handle, indent=2)
            handle.write("\n")

        result = subprocess.run(
            [sys.executable, "verify_installation.py", "--workspace", self.agent_root],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertNotEqual(result.returncode, 0)

    def test_verify_fails_when_required_bundle_directory_is_missing(self):
        shutil.rmtree(os.path.join(self.agent_root, "sudarshan", "skills"))
        result = subprocess.run(
            [sys.executable, "verify_installation.py", "--workspace", self.agent_root],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
