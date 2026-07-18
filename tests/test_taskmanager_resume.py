#!/usr/bin/env python3
"""Resume lock and resume-path tests for taskmanager."""

import os
import shutil
import sys
import tempfile
import unittest


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import taskmanager  # type: ignore


class TestTaskmanagerResume(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.original_resume_lock = taskmanager.RESUME_LOCK
        taskmanager.RESUME_LOCK = os.path.join(self.temp_dir, ".resume_lock")

    def tearDown(self):
        taskmanager.RESUME_LOCK = self.original_resume_lock
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_resume_lock_records_owner_and_rejects_other_releaser(self):
        lock_token = taskmanager._acquire_resume_lock(timeout_seconds=1)
        self.assertTrue(lock_token)
        self.assertTrue(os.path.exists(taskmanager.RESUME_LOCK))

        released = taskmanager._release_resume_lock("different-owner")
        self.assertFalse(released)
        self.assertTrue(os.path.exists(taskmanager.RESUME_LOCK))

        released = taskmanager._release_resume_lock(lock_token)
        self.assertTrue(released)
        self.assertFalse(os.path.exists(taskmanager.RESUME_LOCK))
