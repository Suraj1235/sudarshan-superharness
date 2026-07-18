#!/usr/bin/env python3
"""Unit tests for safe_edit.py"""
import json, os, sys, unittest, tempfile, time, shutil, threading

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from safe_edit import acquire_lock, release_lock, LockRefresher


class TestSafeEditLocking(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.test_file = os.path.join(self.test_dir, "test_target.py")
        with open(self.test_file, "w") as f:
            f.write("line1\nline2\nline3\n")
        self.lock_file = f"{self.test_file}.lock"

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_acquire_and_release(self):
        """Basic acquire and release cycle should work."""
        lock_id = acquire_lock(self.test_file, "worker_1", timeout_sec=60)
        self.assertTrue(lock_id)
        self.assertTrue(os.path.exists(self.lock_file))

        with open(self.lock_file, "r") as f:
            data = json.load(f)
        self.assertEqual(data["worker_id"], "worker_1")
        self.assertEqual(data["lock_id"], lock_id)
        self.assertIn("expires_at", data)

        release_lock(self.test_file, "worker_1", lock_id)
        self.assertFalse(os.path.exists(self.lock_file))

    def test_reused_worker_name_does_not_create_a_second_owner(self):
        """A worker label is descriptive, not proof of process identity."""
        lock_id = acquire_lock(self.test_file, "worker_1", timeout_sec=60)
        try:
            with self.assertRaises(TimeoutError):
                acquire_lock(
                    self.test_file,
                    "worker_1",
                    timeout_sec=60,
                    acquire_timeout_sec=0.05,
                )
        finally:
            release_lock(self.test_file, "worker_1", lock_id)

    def test_wrong_worker_cannot_release(self):
        """A different worker should NOT be able to release someone else's lock."""
        lock_id = acquire_lock(self.test_file, "worker_1", timeout_sec=60)
        release_lock(self.test_file, "worker_2", "not-the-owner-token")
        # Lock should still exist
        self.assertTrue(os.path.exists(self.lock_file))
        # Cleanup
        release_lock(self.test_file, "worker_1", lock_id)

    def test_expired_lock_steal(self):
        """An expired lock should be atomically stolen by a new worker."""
        # Create an already-expired lock
        now = int(time.time())
        lock_data = {
            "worker_id": "dead_worker",
            "acquired_at": now - 200,
            "expires_at": now - 10,
            "last_refreshed_at": now - 200
        }
        with open(self.lock_file, "w") as f:
            json.dump(lock_data, f)

        # New worker should steal it
        lock_id = acquire_lock(self.test_file, "worker_2", timeout_sec=60)
        self.assertTrue(lock_id)

        with open(self.lock_file, "r") as f:
            data = json.load(f)
        self.assertEqual(data["worker_id"], "worker_2")
        self.assertEqual(data["lock_id"], lock_id)
        self.assertEqual(data.get("stolen_from"), "dead_worker")

        release_lock(self.test_file, "worker_2", lock_id)

    def test_corrupt_lock_steal(self):
        """A corrupt/unparseable lock file should be stolen."""
        with open(self.lock_file, "w") as f:
            f.write("THIS IS NOT JSON")

        lock_id = acquire_lock(self.test_file, "worker_3", timeout_sec=60)
        self.assertTrue(lock_id)

        with open(self.lock_file, "r") as f:
            data = json.load(f)
        self.assertEqual(data["worker_id"], "worker_3")

        release_lock(self.test_file, "worker_3", lock_id)

    def test_expired_reacquire_same_worker_cannot_be_released_by_old_instance(self):
        """A reused worker name must not make a stale process the new lock owner."""
        old_lock_id = acquire_lock(self.test_file, "shared_worker", timeout_sec=60)
        with open(self.lock_file, "r", encoding="utf-8") as f:
            expired = json.load(f)
        expired["expires_at"] = int(time.time()) - 1
        with open(self.lock_file, "w", encoding="utf-8") as f:
            json.dump(expired, f)

        new_lock_id = acquire_lock(self.test_file, "shared_worker", timeout_sec=60)
        self.assertNotEqual(new_lock_id, old_lock_id)

        release_lock(self.test_file, "shared_worker", old_lock_id)
        self.assertTrue(os.path.exists(self.lock_file))
        with open(self.lock_file, "r", encoding="utf-8") as f:
            current = json.load(f)
        self.assertEqual(current["lock_id"], new_lock_id)
        release_lock(self.test_file, "shared_worker", new_lock_id)

    def test_expired_lock_has_only_one_concurrent_owner(self):
        """Two contenders must never both report ownership of the same stale lock."""
        now = int(time.time())
        with open(self.lock_file, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "worker_id": "dead_worker",
                    "lock_id": "dead-token",
                    "acquired_at": now - 100,
                    "expires_at": now - 1,
                },
                f,
            )

        start = threading.Barrier(2)
        results = {}
        results_guard = threading.Lock()

        def contend(worker_id):
            start.wait()
            try:
                lock_id = acquire_lock(
                    self.test_file,
                    worker_id,
                    timeout_sec=10,
                    acquire_timeout_sec=0.15,
                )
                with results_guard:
                    results[worker_id] = ("acquired", lock_id)
                time.sleep(0.3)
                release_lock(self.test_file, worker_id, lock_id)
            except TimeoutError:
                with results_guard:
                    results[worker_id] = ("timed_out", None)

        threads = [
            threading.Thread(target=contend, args=("worker_a",)),
            threading.Thread(target=contend, args=("worker_b",)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=2)

        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(
            sorted(result[0] for result in results.values()),
            ["acquired", "timed_out"],
        )

    def test_lock_refresher(self):
        """LockRefresher should update expires_at while running."""
        lock_id = acquire_lock(self.test_file, "worker_1", timeout_sec=10)

        with open(self.lock_file, "r") as f:
            original = json.load(f)

        refresher = LockRefresher(self.lock_file, "worker_1", lock_id, ttl=10)
        def fast_wait(timeout=None):
            time.sleep(0.1)
            return False

        refresher._stop_event.wait = fast_wait  # Speed up for test
        # Manually trigger one refresh
        refresher.start()
        time.sleep(0.5)
        refresher.stop()
        refresher.join(timeout=2)

        if os.path.exists(self.lock_file):
            with open(self.lock_file, "r") as f:
                refreshed = json.load(f)
            self.assertGreaterEqual(refreshed["expires_at"], original["expires_at"])

        release_lock(self.test_file, "worker_1", lock_id)


class TestSafeEditFileOps(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.test_file = os.path.join(self.test_dir, "target.txt")
        with open(self.test_file, "w", encoding="utf-8") as f:
            f.write("line1\nline2\nline3\nline4\nline5\n")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_edit_via_cli(self):
        """Test the full CLI edit flow via subprocess."""
        import subprocess
        safe_edit_path = os.path.join(os.path.dirname(__file__), "..", "safe_edit.py")
        python_cmd = sys.executable

        result = subprocess.run(
            [python_cmd, safe_edit_path,
             "--file", self.test_file,
             "--worker_id", "test_worker",
             "--start", "2",
             "--end", "3",
             "--text", "REPLACED_LINE_2\nREPLACED_LINE_3"],
            capture_output=True, text=True, timeout=15
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("SUCCESS", result.stdout)

        with open(self.test_file, "r") as f:
            content = f.read()
        self.assertIn("REPLACED_LINE_2", content)
        self.assertIn("REPLACED_LINE_3", content)
        self.assertIn("line1", content)
        self.assertIn("line4", content)

        # Check backup was created
        bak_path = f"{self.test_file}.test_worker.bak"
        self.assertTrue(os.path.exists(bak_path))

    def test_restore_via_cli(self):
        """Test backup restore via CLI."""
        import subprocess
        safe_edit_path = os.path.join(os.path.dirname(__file__), "..", "safe_edit.py")
        python_cmd = sys.executable

        # First make an edit (creates backup)
        subprocess.run(
            [python_cmd, safe_edit_path,
             "--file", self.test_file,
             "--worker_id", "test_worker",
             "--start", "1", "--end", "1", "--text", "CHANGED"],
            capture_output=True, timeout=15
        )

        # Now restore
        result = subprocess.run(
            [python_cmd, safe_edit_path,
             "--file", self.test_file,
             "--worker_id", "test_worker",
             "--restore"],
            capture_output=True, text=True, timeout=15
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("SUCCESS: Restored", result.stdout)

        with open(self.test_file, "r") as f:
            content = f.read()
        self.assertIn("line1", content)  # Original content restored

    def test_edit_rejects_end_line_out_of_bounds(self):
        """CLI should fail instead of silently truncating when --end exceeds file length."""
        import subprocess

        safe_edit_path = os.path.join(os.path.dirname(__file__), "..", "safe_edit.py")
        python_cmd = sys.executable

        result = subprocess.run(
            [python_cmd, safe_edit_path,
             "--file", self.test_file,
             "--worker_id", "test_worker",
             "--start", "2",
             "--end", "99",
             "--text", "REPLACED"],
            capture_output=True, text=True, timeout=15
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ERROR: End line out of bounds.", result.stdout)

        with open(self.test_file, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertEqual(content, "line1\nline2\nline3\nline4\nline5\n")


if __name__ == "__main__":
    unittest.main()
