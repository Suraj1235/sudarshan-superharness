#!/usr/bin/env python3
"""Deterministic, model-independent verification command detection."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import List


_IGNORED_PARTS = {".git", ".sudarshan", ".venv", "venv", "node_modules", "__pycache__"}


def _project_files(root: Path):
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if any(part in _IGNORED_PARTS for part in relative.parts):
            continue
        if path.is_file():
            yield path, relative


def detect_verification_commands(workspace_root: str) -> List[List[str]]:
    """Return stack-aware checks the model cannot remove from the finish gate."""
    root = Path(workspace_root).resolve()
    files = list(_project_files(root))
    relative_names = {relative.as_posix() for _, relative in files}
    commands: List[List[str]] = []

    python_files = [relative for path, relative in files if path.suffix == ".py"]
    if python_files:
        commands.append([sys.executable, "-m", "compileall", "-q", "."])
        has_python_tests = any(
            relative.name.startswith("test_") or relative.name.endswith("_test.py")
            for relative in python_files
        )
        if has_python_tests:
            pytest_configured = any(
                name in relative_names for name in ("pytest.ini", "tox.ini", "setup.cfg")
            )
            pyproject = root / "pyproject.toml"
            if pyproject.is_file() and "pytest" in pyproject.read_text(
                encoding="utf-8", errors="ignore"
            ).lower():
                pytest_configured = True
            if pytest_configured:
                commands.append([sys.executable, "-m", "pytest", "-q"])
            else:
                commands.append([sys.executable, "-m", "unittest", "discover", "-q"])

    package_path = root / "package.json"
    if package_path.is_file():
        try:
            package = json.loads(package_path.read_text(encoding="utf-8"))
            scripts = package.get("scripts") or {}
        except (json.JSONDecodeError, TypeError):
            scripts = {}
        if isinstance(scripts, dict):
            if scripts.get("lint"):
                commands.append(["npm", "run", "lint"])
            test_script = scripts.get("test")
            if test_script and "no test specified" not in str(test_script).lower():
                command = ["npm", "test"]
                if "vitest" in str(test_script).lower():
                    command.extend(["--", "--run"])
                commands.append(command)
            if scripts.get("build"):
                commands.append(["npm", "run", "build"])

    if "Cargo.toml" in relative_names:
        commands.append(["cargo", "test"])
    if "go.mod" in relative_names:
        commands.append(["go", "test", "./..."])
    if "pom.xml" in relative_names:
        commands.append(["mvn", "test"])
    if "build.gradle" in relative_names or "build.gradle.kts" in relative_names:
        wrapper = "gradlew" if os.name == "nt" else "./gradlew"
        commands.append([wrapper, "test"])

    unique: List[List[str]] = []
    seen = set()
    for command in commands:
        key = tuple(command)
        if key not in seen:
            unique.append(command)
            seen.add(key)
    return unique


__all__ = ["detect_verification_commands"]
