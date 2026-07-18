#!/usr/bin/env python3
"""Workspace-confined tools for the standalone Sudarshan engine."""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

from process_runner import run_bounded_process


class ToolPolicyError(ValueError):
    pass


DEFAULT_ALLOWED_COMMANDS = {
    "bun",
    "cargo",
    "cmake",
    "deno",
    "docker",
    "docker-compose",
    "dotnet",
    "git",
    "go",
    "gradle",
    "gradlew",
    "java",
    "javac",
    "make",
    "mvn",
    "node",
    "npm",
    "npx",
    "pip",
    "pip3",
    "pnpm",
    "py",
    "pytest",
    "python",
    "python3",
    "rustc",
    "uv",
    "yarn",
}

_HIDDEN_DIRECTORIES = {".git", ".sudarshan", ".venv", "venv", "node_modules", "__pycache__"}
_SENSITIVE_ENV = re.compile(r"(?:API[_-]?KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|PRIVATE[_-]?KEY|AUTH)", re.I)


def _normalized_executable(value: str) -> str:
    name = os.path.basename(value).lower()
    for suffix in (".exe", ".cmd", ".bat", ".com"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break
    return name


class WorkspaceTools:
    def __init__(
        self,
        workspace_root: str,
        *,
        allowed_commands: Optional[Iterable[str]] = None,
    ) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        configured = allowed_commands if allowed_commands is not None else DEFAULT_ALLOWED_COMMANDS
        self.allowed_commands = {_normalized_executable(item) for item in configured}

    def _resolve(self, relative_path: str) -> Path:
        if not isinstance(relative_path, str) or not relative_path.strip():
            raise ToolPolicyError("path must be a non-empty string")
        path = Path(relative_path)
        if path.is_absolute():
            raise ToolPolicyError("absolute paths are outside the workspace policy")
        if path.parts and path.parts[0].lower() == ".sudarshan":
            raise ToolPolicyError(".sudarshan is reserved for engine state")
        candidate = (self.workspace_root / path).resolve()
        try:
            common = os.path.commonpath([str(self.workspace_root), str(candidate)])
        except ValueError:
            raise ToolPolicyError("path is outside the workspace") from None
        if os.path.normcase(common) != os.path.normcase(str(self.workspace_root)):
            raise ToolPolicyError("path is outside the workspace")
        return candidate

    def _relative(self, path: Path) -> str:
        return path.relative_to(self.workspace_root).as_posix()

    def read_file(self, path: str, *, max_chars: int = 100_000) -> Dict[str, object]:
        if max_chars < 1:
            raise ToolPolicyError("max_chars must be positive")
        target = self._resolve(path)
        if not target.is_file():
            raise ToolPolicyError(f"file does not exist: {path}")
        content = target.read_text(encoding="utf-8", errors="replace")
        return {
            "path": self._relative(target),
            "content": content[:max_chars],
            "truncated": len(content) > max_chars,
            "total_chars": len(content),
        }

    def write_file(self, path: str, content: str) -> Dict[str, object]:
        if not isinstance(content, str):
            raise ToolPolicyError("content must be text")
        target = self._resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        temp_name = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="",
                delete=False,
                dir=str(target.parent),
                prefix=f".{target.name}.",
                suffix=".tmp",
            ) as handle:
                temp_name = handle.name
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, target)
        finally:
            if temp_name and os.path.exists(temp_name):
                os.unlink(temp_name)
        raw = content.encode("utf-8")
        return {
            "path": self._relative(target),
            "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
        }

    def edit_file(
        self,
        path: str,
        *,
        old_text: str,
        new_text: str,
        expected_replacements: int = 1,
    ) -> Dict[str, object]:
        """Atomically apply an exact, cardinality-checked text replacement."""
        if not isinstance(old_text, str) or not old_text:
            raise ToolPolicyError("old_text must be non-empty text")
        if not isinstance(new_text, str):
            raise ToolPolicyError("new_text must be text")
        if not isinstance(expected_replacements, int) or expected_replacements < 1:
            raise ToolPolicyError("expected_replacements must be a positive integer")
        target = self._resolve(path)
        if not target.is_file():
            raise ToolPolicyError(f"file does not exist: {path}")
        try:
            content = target.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            raise ToolPolicyError(f"file is not UTF-8 text: {path}") from None
        matches = content.count(old_text)
        if matches != expected_replacements:
            raise ToolPolicyError(
                f"expected {expected_replacements} exact match(es), found {matches}: {path}"
            )
        result = self.write_file(
            path,
            content.replace(old_text, new_text, expected_replacements),
        )
        result["replacements"] = matches
        return result

    def delete_file(self, path: str) -> Dict[str, object]:
        target = self._resolve(path)
        if not target.is_file():
            raise ToolPolicyError(f"file does not exist: {path}")
        target.unlink()
        return {"path": self._relative(target), "deleted": True}

    def list_files(self, path: str = ".", *, max_entries: int = 1000) -> Dict[str, object]:
        if max_entries < 1:
            raise ToolPolicyError("max_entries must be positive")
        target = self._resolve(path)
        if not target.is_dir():
            raise ToolPolicyError(f"directory does not exist: {path}")
        files: List[str] = []
        for candidate in target.rglob("*"):
            relative_to_root = candidate.relative_to(self.workspace_root)
            if any(part in _HIDDEN_DIRECTORIES for part in relative_to_root.parts):
                continue
            if candidate.is_file():
                files.append(relative_to_root.as_posix())
        files.sort()
        return {
            "path": self._relative(target) or ".",
            "files": files[:max_entries],
            "truncated": len(files) > max_entries,
            "total_files": len(files),
        }

    def _validate_command(self, argv: Sequence[str]) -> List[str]:
        if isinstance(argv, (str, bytes)) or not isinstance(argv, Sequence):
            raise ToolPolicyError("command must be an argument array, not a shell string")
        if not argv or any(not isinstance(item, str) or "\x00" in item for item in argv):
            raise ToolPolicyError("command argument array is invalid")
        command = _normalized_executable(argv[0])
        if command not in self.allowed_commands:
            raise ToolPolicyError(f"command is not allowed: {command}")
        lowered = [item.lower() for item in argv[1:]]
        if command == "git" and lowered:
            subcommand = lowered[0]
            destructive = subcommand in {"clean", "reset", "restore"}
            destructive = destructive or (subcommand == "checkout" and "--" in lowered)
            destructive = destructive or (subcommand == "rm" and any("r" in item for item in lowered[1:] if item.startswith("-")))
            if destructive:
                raise ToolPolicyError("destructive git command is blocked by policy")
        return list(argv)

    @staticmethod
    def _safe_environment() -> Dict[str, str]:
        return {key: value for key, value in os.environ.items() if not _SENSITIVE_ENV.search(key)}

    def run_command(
        self,
        argv: Sequence[str],
        *,
        timeout_seconds: float = 120.0,
        max_output_chars: int = 20_000,
        cwd: str = ".",
    ) -> Dict[str, object]:
        command = self._validate_command(argv)
        if timeout_seconds <= 0 or max_output_chars < 1:
            raise ToolPolicyError("timeout and output cap must be positive")
        working_directory = self._resolve(cwd)
        if not working_directory.is_dir():
            raise ToolPolicyError(f"working directory does not exist: {cwd}")

        started = time.monotonic()
        result = run_bounded_process(
            command,
            cwd=str(working_directory),
            env=self._safe_environment(),
            timeout_seconds=float(timeout_seconds),
            max_stdout_chars=max_output_chars,
            max_stderr_chars=max_output_chars,
        )

        duration = round(time.monotonic() - started, 3)
        return {
            "argv": command,
            "cwd": self._relative(working_directory) or ".",
            "returncode": result.returncode,
            "timed_out": result.timed_out,
            "duration_seconds": duration,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "stdout_truncated": result.stdout_truncated,
            "stderr_truncated": result.stderr_truncated,
        }


__all__ = ["DEFAULT_ALLOWED_COMMANDS", "ToolPolicyError", "WorkspaceTools"]
