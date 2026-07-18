#!/usr/bin/env python3
"""Deterministic file editor with cross-process ownership locks."""

import argparse
from contextlib import contextmanager
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid


LOCK_TTL_SECONDS = 180
LOCK_REFRESH_INTERVAL = LOCK_TTL_SECONDS // 3
ACQUIRE_TIMEOUT_SECONDS = 30
METADATA_GUARD_TIMEOUT_SECONDS = 5
METADATA_GUARD_STALE_SECONDS = 30


@contextmanager
def _metadata_guard(lock_file, timeout_sec=METADATA_GUARD_TIMEOUT_SECONDS):
    """Serialize lock metadata transitions across threads and processes."""
    guard_dir = f"{lock_file}.guard"
    deadline = time.monotonic() + timeout_sec

    while True:
        try:
            os.mkdir(guard_dir)
            break
        except FileExistsError:
            try:
                age = time.time() - os.path.getmtime(guard_dir)
            except FileNotFoundError:
                continue

            if age > METADATA_GUARD_STALE_SECONDS:
                stale_dir = f"{guard_dir}.stale-{uuid.uuid4().hex}"
                try:
                    os.replace(guard_dir, stale_dir)
                    os.rmdir(stale_dir)
                    continue
                except (FileNotFoundError, OSError):
                    pass

            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"Timed out waiting for lock metadata guard: {lock_file}"
                )
            time.sleep(0.01)
        except PermissionError:
            # NTFS can briefly report access denied while another thread removes
            # the guard directory. Treat it as contention within the same bound.
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"Timed out waiting for lock metadata guard: {lock_file}"
                )
            time.sleep(0.01)

    try:
        yield
    finally:
        for attempt in range(10):
            try:
                os.rmdir(guard_dir)
                break
            except FileNotFoundError:
                break
            except PermissionError:
                if attempt == 9:
                    raise
                time.sleep(0.01)


def _write_lock(lock_file, lock_data):
    """Atomically replace lock metadata while the caller holds its guard."""
    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=os.path.dirname(lock_file) or ".",
        suffix=".lock.tmp",
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as handle:
            json.dump(lock_data, handle)
        os.replace(tmp_path, lock_file)
    finally:
        try:
            os.remove(tmp_path)
        except FileNotFoundError:
            pass


class LockRefresher(threading.Thread):
    """Refresh a lock only while this exact acquisition still owns it."""

    def __init__(self, lock_file, worker_id, lock_id, ttl):
        super().__init__(daemon=True)
        self.lock_file = lock_file
        self.worker_id = worker_id
        self.lock_id = lock_id
        self.ttl = ttl
        self._stop_event = threading.Event()

    def run(self):
        refresh_interval = max(0.1, min(LOCK_REFRESH_INTERVAL, self.ttl / 3))
        while not self._stop_event.is_set():
            self._stop_event.wait(refresh_interval)
            if self._stop_event.is_set():
                break
            try:
                with _metadata_guard(self.lock_file):
                    with open(self.lock_file, "r", encoding="utf-8") as handle:
                        lock_data = json.load(handle)
                    owns_lock = (
                        lock_data.get("worker_id") == self.worker_id
                        and lock_data.get("lock_id") == self.lock_id
                    )
                    if not owns_lock:
                        self._stop_event.set()
                        break
                    now = int(time.time())
                    lock_data["expires_at"] = now + self.ttl
                    lock_data["last_refreshed_at"] = now
                    _write_lock(self.lock_file, lock_data)
            except (FileNotFoundError, json.JSONDecodeError, TimeoutError, OSError):
                self._stop_event.set()

    def stop(self):
        self._stop_event.set()


def acquire_lock(
    file_path,
    worker_id,
    timeout_sec=LOCK_TTL_SECONDS,
    acquire_timeout_sec=ACQUIRE_TIMEOUT_SECONDS,
):
    """Acquire a lock and return its unique ownership token.

    A directory guard serializes expiry takeovers. The per-acquisition token
    prevents an older process with the same worker name from refreshing or
    releasing a newer owner's lock.
    """
    parent = os.path.dirname(os.path.abspath(file_path))
    os.makedirs(parent, exist_ok=True)
    lock_file = f"{file_path}.lock"
    deadline = time.monotonic() + acquire_timeout_sec

    while True:
        remaining = None
        try:
            guard_timeout = max(
                0.01,
                min(METADATA_GUARD_TIMEOUT_SECONDS, deadline - time.monotonic()),
            )
            with _metadata_guard(lock_file, timeout_sec=guard_timeout):
                lock_data = None
                corrupt = False
                try:
                    with open(lock_file, "r", encoding="utf-8") as handle:
                        lock_data = json.load(handle)
                except FileNotFoundError:
                    pass
                except (json.JSONDecodeError, ValueError):
                    corrupt = True

                now = int(time.time())
                expired = (
                    lock_data is not None
                    and now >= lock_data.get("expires_at", 0)
                )

                if lock_data is None or corrupt or expired:
                    lock_id = uuid.uuid4().hex
                    replacement = {
                        "worker_id": worker_id,
                        "lock_id": lock_id,
                        "acquired_at": now,
                        "expires_at": now + timeout_sec,
                        "last_refreshed_at": now,
                    }
                    if corrupt:
                        replacement["stolen_from"] = "corrupt_lock"
                    elif lock_data is not None:
                        replacement["stolen_from"] = lock_data.get(
                            "worker_id", "unknown"
                        )
                    _write_lock(lock_file, replacement)
                    return lock_id

                current_owner = lock_data.get("worker_id", "unknown")
                remaining = lock_data.get("expires_at", now) - now
        except TimeoutError:
            pass

        if time.monotonic() >= deadline:
            expiry = "" if remaining is None else f" (expires in {remaining}s)"
            raise TimeoutError(
                f"File {file_path} is locked by another worker{expiry}; "
                f"timed out after {acquire_timeout_sec}s"
            )
        time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))


def release_lock(file_path, worker_id, lock_id):
    """Release only when both worker name and acquisition token match."""
    lock_file = f"{file_path}.lock"
    try:
        with _metadata_guard(lock_file):
            with open(lock_file, "r", encoding="utf-8") as handle:
                lock_data = json.load(handle)
            owns_lock = (
                lock_data.get("worker_id") == worker_id
                and lock_data.get("lock_id") == lock_id
            )
            if owns_lock:
                os.remove(lock_file)
    except (FileNotFoundError, json.JSONDecodeError, PermissionError, TimeoutError):
        pass


def shallow_git_commit(file_path):
    """Create a targeted Git snapshot for one file."""
    try:
        print(f"Executing shallow Git snapshot for {file_path}...")
        subprocess.check_call(
            ["git", "add", file_path],
            stderr=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
        )
        subprocess.check_call(
            [
                "git",
                "commit",
                "-m",
                f"Autosave: Red Team Green Light for {os.path.basename(file_path)}",
            ],
            stderr=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
        )
        print(f"SUCCESS: Git snapshot saved for {file_path}.")
    except (subprocess.CalledProcessError, FileNotFoundError) as error:
        print(
            "WARN: Git snapshot failed or Git is unavailable. "
            f"Proceeding without Git. Error: {error}"
        )


def main():
    parser = argparse.ArgumentParser(
        description="Deterministic file editor for LLM workers with ownership locks"
    )
    parser.add_argument("--file", required=True, help="File path to edit")
    parser.add_argument("--worker_id", required=True, help="Unique worker ID")
    parser.add_argument("--restore", action="store_true", help="Restore scoped backup")
    parser.add_argument("--greenlight", action="store_true", help="Create Git snapshot")
    parser.add_argument("--start", type=int, help="Start line number (1-indexed)")
    parser.add_argument("--end", type=int, help="End line number (inclusive)")
    parser.add_argument("--text", help="Replacement text")
    args = parser.parse_args()

    bak_path = f"{args.file}.{args.worker_id}.bak"
    try:
        lock_id = acquire_lock(args.file, args.worker_id, timeout_sec=LOCK_TTL_SECONDS)
    except TimeoutError as error:
        print(f"ERROR: {error}")
        return 1

    refresher = LockRefresher(
        f"{args.file}.lock",
        args.worker_id,
        lock_id,
        LOCK_TTL_SECONDS,
    )
    refresher.start()

    try:
        if args.greenlight:
            shallow_git_commit(args.file)
            return 0

        if args.restore:
            if os.path.exists(bak_path):
                shutil.copy2(bak_path, args.file)
                print(f"SUCCESS: Restored {args.file} from {bak_path}")
                return 0
            print(f"ERROR: Backup file {bak_path} not found.")
            return 1

        if not args.start or not args.end or args.text is None:
            print("ERROR: Must provide --start, --end, and --text to edit.")
            return 1

        os.makedirs(os.path.dirname(os.path.abspath(args.file)), exist_ok=True)
        if not os.path.exists(args.file):
            print(f"INFO: Target file {args.file} not found. Creating a new file.")
            with open(args.file, "w", encoding="utf-8"):
                pass

        with open(args.file, "r", encoding="utf-8", errors="replace") as handle:
            lines = handle.readlines()

        start_idx = args.start - 1
        end_idx = args.end
        if start_idx < 0 or start_idx > len(lines):
            print("ERROR: Start line out of bounds.")
            return 1
        if end_idx < args.start or end_idx > len(lines):
            print("ERROR: End line out of bounds.")
            return 1

        shutil.copy2(args.file, bak_path)
        replacement = [line + "\n" for line in args.text.split("\n")]
        lines = lines[:start_idx] + replacement + lines[end_idx:]
        with open(args.file, "w", encoding="utf-8") as handle:
            handle.writelines(lines)

        print(
            f"SUCCESS: Edited {args.file} (Lines {args.start}-{args.end} replaced). "
            f"Backup created at {bak_path}"
        )
        return 0
    finally:
        refresher.stop()
        refresher.join(timeout=2)
        release_lock(args.file, args.worker_id, lock_id)


if __name__ == "__main__":
    sys.exit(main())
