#!/usr/bin/env python3
"""Tests for the heartbeat lifecycle daemon."""

import json
import os
import shutil
import sys
import tempfile
import unittest


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from protocol_assets import install_required_templates  # type: ignore
from heartbeat_daemon import HeartbeatDaemon  # type: ignore


class TestHeartbeatDaemon(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        install_required_templates(self.temp_dir, overwrite=False)
        os.makedirs(os.path.join(self.temp_dir, "isolated_tasks"), exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _write_json(self, relative_path, data):
        path = os.path.join(self.temp_dir, relative_path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)

    def _read_json(self, relative_path):
        with open(os.path.join(self.temp_dir, relative_path), "r", encoding="utf-8") as handle:
            return json.load(handle)

    def test_phase_zero_timeout_marks_blackboard(self):
        self._write_json(
            ".swarm_lock",
            {
                "last_active_timestamp": 1000,
                "created_at": 1000,
                "session_id": "session_1",
                "phase": "phase_0_research",
            },
        )

        daemon = HeartbeatDaemon(self.temp_dir)
        daemon.run_once(current_epoch=5000)

        blackboard = self._read_json("enterprise_state/BLACKBOARD_STATUS.json")
        self.assertEqual(blackboard["status"], "PHASE_TIMEOUT")
        self.assertEqual(blackboard["event"], "[SYSTEM: PHASE_TIMEOUT]")

    def test_budget_exceeded_marks_blackboard(self):
        self._write_json(
            "enterprise_state/BLACKBOARD_STATUS.json",
            {
                "blackboard_version": "16.9.1",
                "status": "IDLE",
                "blocker_type": None,
                "blocker_description": None,
                "observer_attempts": 0,
                "escalated_to_l1": False,
                "resolution": None,
                "event": None,
                "affected": [],
                "metadata": {
                    "last_updated_at": None,
                    "model": "default",
                    "budget": {
                        "max_session_token_burn_usd": 10.0,
                        "alert_threshold_percent": 80,
                        "hard_kill_on_exceed": True
                    }
                }
            }
        )
        self._write_json(
            "enterprise_state/STRIKE_LEDGER.json",
            {
                "ledger_version": "16.9.1",
                "total_strikes": 0,
                "total_staff_engineer_interventions": 0,
                "total_session_cost_usd": 12.5,
                "strikes": [],
                "staff_interventions": [],
                "pm_audit_rejections": [],
                "token_usage": [],
                "metadata": {}
            }
        )

        daemon = HeartbeatDaemon(self.temp_dir)
        daemon.run_once(current_epoch=5000)

        blackboard = self._read_json("enterprise_state/BLACKBOARD_STATUS.json")
        self.assertEqual(blackboard["status"], "BUDGET_EXCEEDED")
        self.assertEqual(blackboard["event"], "[SYSTEM: BUDGET_EXCEEDED]")

    def test_phase_timeout_is_not_overwritten_by_budget_check(self):
        self._write_json(
            ".swarm_lock",
            {
                "last_active_timestamp": 1000,
                "created_at": 1000,
                "session_id": "session_1",
                "phase": "phase_0_research",
            },
        )
        self._write_json(
            "enterprise_state/BLACKBOARD_STATUS.json",
            {
                "blackboard_version": "16.9.1",
                "status": "IDLE",
                "blocker_type": None,
                "blocker_description": None,
                "observer_attempts": 0,
                "escalated_to_l1": False,
                "resolution": None,
                "event": None,
                "affected": [],
                "metadata": {
                    "last_updated_at": None,
                    "model": "default",
                    "budget": {
                        "max_session_token_burn_usd": 10.0,
                        "alert_threshold_percent": 80,
                        "hard_kill_on_exceed": True
                    }
                }
            }
        )
        self._write_json(
            "enterprise_state/STRIKE_LEDGER.json",
            {
                "ledger_version": "16.9.1",
                "total_strikes": 0,
                "total_staff_engineer_interventions": 0,
                "total_session_cost_usd": 12.5,
                "strikes": [],
                "staff_interventions": [],
                "pm_audit_rejections": [],
                "token_usage": [],
                "metadata": {}
            }
        )

        daemon = HeartbeatDaemon(self.temp_dir)
        daemon.run_once(current_epoch=5000)

        blackboard = self._read_json("enterprise_state/BLACKBOARD_STATUS.json")
        self.assertEqual(blackboard["status"], "PHASE_TIMEOUT")
        self.assertEqual(blackboard["event"], "[SYSTEM: PHASE_TIMEOUT]")


if __name__ == "__main__":
    unittest.main()
