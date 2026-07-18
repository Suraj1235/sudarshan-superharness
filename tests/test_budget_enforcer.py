#!/usr/bin/env python3
"""Budget enforcement CLI tests."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest


REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")


class TestBudgetEnforcer(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.temp_dir, "enterprise_state"), exist_ok=True)
        with open(os.path.join(self.temp_dir, "enterprise_state", "BLACKBOARD_STATUS.json"), "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "blackboard_version": "16.9.1",
                    "status": "IDLE",
                    "metadata": {
                        "budget": {
                            "max_session_token_burn_usd": 10.0,
                            "alert_threshold_percent": 80,
                            "hard_kill_on_exceed": True,
                        }
                    },
                },
                handle,
                indent=2,
            )

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _run_check(self, spend):
        with open(os.path.join(self.temp_dir, "enterprise_state", "STRIKE_LEDGER.json"), "w", encoding="utf-8") as handle:
            json.dump({"total_session_cost_usd": spend}, handle, indent=2)
        return subprocess.run(
            [sys.executable, "taskmanager.py", "--workspace", self.temp_dir, "--check-budget"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def test_budget_ok_returns_zero(self):
        result = self._run_check(3.0)
        self.assertEqual(result.returncode, 0, msg=result.stderr or result.stdout)

    def test_budget_exceeded_returns_three(self):
        result = self._run_check(12.0)
        self.assertEqual(result.returncode, 3, msg=result.stderr or result.stdout)


if __name__ == "__main__":
    unittest.main()
