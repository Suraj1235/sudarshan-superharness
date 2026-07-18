#!/usr/bin/env python3
"""Cross-platform subprocess execution with bounded in-memory output."""

from __future__ import annotations

import math
import os
import signal
import subprocess
import threading
from dataclasses import dataclass
from typing import Dict, Optional, Sequence


@dataclass(frozen=True)
class BoundedProcessResult:
    returncode: Optional[int]
    timed_out: bool
    stdout: str
    stderr: str
    stdout_truncated: bool
    stderr_truncated: bool


class _Collector:
    def __init__(self, max_chars: int) -> None:
        self.max_chars = max_chars
        self.max_bytes = max_chars * 4
        self.buffer = bytearray()
        self.total_bytes = 0
        self.forced_closed = False

    def drain(self, stream) -> None:
        try:
            while True:
                chunk = stream.read(8192)
                if not chunk:
                    break
                self.total_bytes += len(chunk)
                remaining = self.max_bytes - len(self.buffer)
                if remaining > 0:
                    self.buffer.extend(chunk[:remaining])
        except (OSError, ValueError):
            self.forced_closed = True
        finally:
            try:
                stream.close()
            except (OSError, ValueError):
                pass

    def result(self) -> tuple[str, bool]:
        text = bytes(self.buffer).decode("utf-8", errors="replace")
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        truncated = (
            self.forced_closed
            or self.total_bytes > len(self.buffer)
            or len(text) > self.max_chars
        )
        return text[: self.max_chars], truncated


def _terminate_process_tree(process: subprocess.Popen) -> None:
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
                check=False,
                shell=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass

    if process.poll() is None:
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            if os.name != "nt":
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
            try:
                process.kill()
            except OSError:
                pass
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass


def run_bounded_process(
    argv: Sequence[str],
    *,
    cwd: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
    input_text: Optional[str] = None,
    timeout_seconds: float,
    max_stdout_chars: int,
    max_stderr_chars: int,
) -> BoundedProcessResult:
    """Run an argv command while continuously draining and capping both pipes."""
    if not math.isfinite(float(timeout_seconds)) or timeout_seconds <= 0:
        raise ValueError("timeout must be positive and finite")
    if any(
        isinstance(limit, bool) or not isinstance(limit, int) or limit < 1
        for limit in (max_stdout_chars, max_stderr_chars)
    ):
        raise ValueError("timeout and output caps must be positive")

    popen_kwargs = {
        "cwd": cwd,
        "env": env,
        "stdin": subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "shell": False,
    }
    if os.name == "nt":
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        popen_kwargs["start_new_session"] = True

    process = subprocess.Popen(list(argv), **popen_kwargs)
    stdout_collector = _Collector(max_stdout_chars)
    stderr_collector = _Collector(max_stderr_chars)
    readers = [
        threading.Thread(
            target=stdout_collector.drain,
            args=(process.stdout,),
            daemon=True,
        ),
        threading.Thread(
            target=stderr_collector.drain,
            args=(process.stderr,),
            daemon=True,
        ),
    ]
    for reader in readers:
        reader.start()

    writer = None
    if input_text is not None:
        payload = input_text.encode("utf-8")

        def write_input() -> None:
            try:
                process.stdin.write(payload)
                process.stdin.flush()
            except (BrokenPipeError, OSError, ValueError):
                pass
            finally:
                try:
                    process.stdin.close()
                except (OSError, ValueError):
                    pass

        writer = threading.Thread(target=write_input, daemon=True)
        writer.start()

    timed_out = False
    try:
        process.wait(timeout=float(timeout_seconds))
    except subprocess.TimeoutExpired:
        timed_out = True
        _terminate_process_tree(process)

    if writer is not None:
        writer.join(timeout=1)
    for reader in readers:
        reader.join(timeout=1)
    if any(reader.is_alive() for reader in readers):
        _terminate_process_tree(process)
        for stream, collector in (
            (process.stdout, stdout_collector),
            (process.stderr, stderr_collector),
        ):
            collector.forced_closed = True
            try:
                stream.close()
            except (OSError, ValueError):
                pass
        for reader in readers:
            reader.join(timeout=1)

    stdout, stdout_truncated = stdout_collector.result()
    stderr, stderr_truncated = stderr_collector.result()
    return BoundedProcessResult(
        returncode=None if timed_out else process.returncode,
        timed_out=timed_out,
        stdout=stdout,
        stderr=stderr,
        stdout_truncated=stdout_truncated,
        stderr_truncated=stderr_truncated,
    )


__all__ = ["BoundedProcessResult", "run_bounded_process"]
