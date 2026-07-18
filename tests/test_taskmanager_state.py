#!/usr/bin/env python3
"""Concurrency tests for taskmanager's legacy shared JSON state."""

import json
import os
import shutil
import tempfile
import threading
import traceback
import unittest
from unittest import mock

import taskmanager


class TestStateManagerConcurrency(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.path = os.path.join(self.temp_dir, "state.json")
        self.original_strike_ledger = taskmanager.STRIKE_LEDGER
        taskmanager.STRIKE_LEDGER = os.path.join(self.temp_dir, "strike-ledger.json")

    def tearDown(self):
        taskmanager.STRIKE_LEDGER = self.original_strike_ledger
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_concurrent_writers_use_distinct_atomic_temp_files(self):
        real_replace = os.replace
        errors = []
        temp_sources = []
        sources_guard = threading.Lock()

        def synchronized_replace(source, destination):
            if destination == self.path:
                with sources_guard:
                    temp_sources.append(source)
                threading.Event().wait(0.02)
            return real_replace(source, destination)

        def write(value):
            try:
                taskmanager.StateManager.write_json(self.path, {"value": value})
            except Exception as error:  # pragma: no cover - asserted below
                errors.append(error)

        with mock.patch.object(taskmanager.os, "replace", synchronized_replace):
            threads = [threading.Thread(target=write, args=(value,)) for value in (1, 2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=3)

        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(errors, [])
        self.assertEqual(len(set(temp_sources)), 2)
        with open(self.path, "r", encoding="utf-8") as handle:
            self.assertIn(json.load(handle)["value"], (1, 2))

    def test_transactional_updates_do_not_lose_concurrent_increments(self):
        taskmanager.StateManager.write_json(self.path, {"count": 0})
        errors = []

        def increment():
            try:
                def mutate(state):
                    current = state["count"]
                    # Widen the race window that an unlocked read/write would expose.
                    threading.Event().wait(0.01)
                    state["count"] = current + 1
                    return state

                taskmanager.StateManager.update_json(self.path, mutate)
            except Exception as error:  # pragma: no cover - asserted below
                errors.append(error)

        threads = [threading.Thread(target=increment) for _ in range(12)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)

        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(errors, [])
        self.assertEqual(taskmanager.StateManager.read_json(self.path)["count"], 12)

    def test_strike_ledger_preserves_all_concurrent_events(self):
        errors = []

        def record(index):
            try:
                taskmanager.StrikeLedger.record_strike(f"worker_{index}", "test failure")
            except Exception as error:  # pragma: no cover - asserted below
                errors.append((error, traceback.format_exc()))

        with mock.patch("builtins.print"):
            threads = [threading.Thread(target=record, args=(index,)) for index in range(12)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=5)

        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(errors, [])
        ledger = taskmanager.StateManager.read_json(taskmanager.STRIKE_LEDGER)
        self.assertEqual(ledger["total_strikes"], 12)
        self.assertEqual(len(ledger["strikes"]), 12)


if __name__ == "__main__":
    unittest.main()
