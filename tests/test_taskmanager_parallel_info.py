#!/usr/bin/env python3
"""Regression tests for taskmanager parallel-info behavior."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from protocol_assets import install_required_templates  # type: ignore


class TestTaskmanagerParallelInfo(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        install_required_templates(self.temp_dir, overwrite=False)
        os.makedirs(os.path.join(self.temp_dir, "isolated_tasks"), exist_ok=True)
        self.repo_root = os.path.join(os.path.dirname(__file__), "..")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_parallel_info_uses_workspace_dag_not_process_cwd(self):
        dag_path = os.path.join(self.temp_dir, "enterprise_state", "JIRA_DAG.json")
        with open(dag_path, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "nodes": [
                        {"id": "ONE", "dependencies": []},
                        {"id": "TWO", "dependencies": ["ONE"]},
                    ]
                },
                handle,
                indent=2,
            )

        result = subprocess.run(
            [
                sys.executable,
                "taskmanager.py",
                "--workspace",
                self.temp_dir,
                "--parallel-info",
            ],
            cwd=self.repo_root,
            capture_output=True,
            text=True,
            timeout=20,
        )

        self.assertEqual(result.returncode, 0, msg=result.stderr or result.stdout)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["total_nodes"], 2)
        self.assertEqual(payload["parallel_batches"], [["ONE"], ["TWO"]])
