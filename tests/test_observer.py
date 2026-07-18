#!/usr/bin/env python3
"""Tests for observer escalation behavior."""

import json
import os
import shutil
import sys
import tempfile
import unittest


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from observer import ObserverNode  # type: ignore
from protocol_assets import install_required_templates  # type: ignore


class TestObserverEscalation(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        install_required_templates(self.temp_dir, overwrite=False)
        os.makedirs(os.path.join(self.temp_dir, "isolated_tasks"), exist_ok=True)
        self.enterprise_state = os.path.join(self.temp_dir, "enterprise_state")

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

    def test_observer_does_not_observe_its_own_architecture_log(self):
        """Writing the observer log must not create an endless update loop."""
        observer = ObserverNode(self.temp_dir)

        initial_changes = observer.detect_changes()
        observer.update_architecture_state(initial_changes)
        follow_up_changes = observer.detect_changes()

        self.assertNotIn(
            "ARCHITECTURE_STATE.md",
            [change["basename"] for change in follow_up_changes],
        )

    def test_observer_does_not_reset_strikes_on_single_keyword_match(self):
        """Keyword-only evidence should not let the observer wipe the strike ledger."""
        self._write_json(
            ".swarm_lock",
            {
                "last_active_timestamp": 1000,
                "created_at": 1000,
                "session_id": "session_1",
                "phase": "phase_3_cicd",
            },
        )
        self._write_json(
            "enterprise_state/BLACKBOARD_STATUS.json",
            {
                "blackboard_version": "16.9.1",
                "status": "BLOCKED_AWAITING_HUMAN",
                "blocker_type": "12_strike",
                "blocker_description": "12 strike ceiling hit",
                "observer_attempts": 0,
                "escalated_to_l1": False,
                "resolution": None,
                "event": "[SYSTEM: HAAS_REQUEST]",
                "affected": [],
                "metadata": {"last_updated_at": None},
            },
        )
        self._write_json(
            "enterprise_state/STRIKE_LEDGER.json",
            {
                "ledger_version": "16.9.1",
                "total_strikes": 12,
                "total_staff_engineer_interventions": 4,
                "total_session_cost_usd": 0,
                "strikes": [
                    {"worker_id": "grunt_a", "description": "auth race condition"},
                    {"worker_id": "grunt_a", "description": "command not found while retrying broken auth flow"},
                ],
                "staff_interventions": [
                    {"summary": "Investigated architectural auth failure; not a CLI issue."}
                ],
                "pm_audit_rejections": [],
                "token_usage": [],
                "metadata": {},
            },
        )
        self._write_json(
            "enterprise_state/BATON_STATE.json",
            {"status": "HALTED", "relay_count": 0, "metadata": {}},
        )

        observer = ObserverNode(self.temp_dir)
        resolved = observer.check_haas_request()

        self.assertFalse(resolved)
        ledger = self._read_json("enterprise_state/STRIKE_LEDGER.json")
        self.assertEqual(ledger["total_strikes"], 12)
        self.assertEqual(len(ledger["strikes"]), 2)

    def test_observer_can_still_resolve_consistent_cli_failures(self):
        """Observer should preserve the intended self-heal path for repeated CLI-only failures."""
        self._write_json(
            ".swarm_lock",
            {
                "last_active_timestamp": 1000,
                "created_at": 1000,
                "session_id": "session_1",
                "phase": "phase_3_cicd",
            },
        )
        self._write_json(
            "enterprise_state/BLACKBOARD_STATUS.json",
            {
                "blackboard_version": "16.9.1",
                "status": "BLOCKED_AWAITING_HUMAN",
                "blocker_type": "12_strike",
                "blocker_description": "12 strike ceiling hit",
                "observer_attempts": 0,
                "escalated_to_l1": False,
                "resolution": None,
                "event": "[SYSTEM: HAAS_REQUEST]",
                "affected": [],
                "metadata": {"last_updated_at": None},
            },
        )
        self._write_json(
            "enterprise_state/STRIKE_LEDGER.json",
            {
                "ledger_version": "16.9.1",
                "total_strikes": 6,
                "total_staff_engineer_interventions": 4,
                "total_session_cost_usd": 0,
                "strikes": [
                    {"worker_id": "grunt_cli", "description": "command not found: prism"},
                    {"worker_id": "grunt_cli", "description": "cli syntax failure in npm command"},
                    {"worker_id": "grunt_cli", "description": "permission denied launching local cli binary"},
                ],
                "staff_interventions": [
                    {"summary": "Confirmed repeated CLI/bootstrap failure, safe to reset strike ledger."}
                ],
                "pm_audit_rejections": [],
                "token_usage": [],
                "metadata": {},
            },
        )
        self._write_json(
            "enterprise_state/BATON_STATE.json",
            {"status": "HALTED", "relay_count": 0, "metadata": {}},
        )

        observer = ObserverNode(self.temp_dir)
        resolved = observer.check_haas_request()

        self.assertTrue(resolved)
        ledger = self._read_json("enterprise_state/STRIKE_LEDGER.json")
        self.assertEqual(ledger["total_strikes"], 0)
        self.assertEqual(ledger["total_staff_engineer_interventions"], 0)
