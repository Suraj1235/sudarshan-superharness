#!/usr/bin/env python3
"""Public-release hygiene checks for documentation and generated artifacts."""

from pathlib import Path
import unittest

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.9 and 3.10
    import tomli as tomllib


ROOT = Path(__file__).resolve().parents[1]


class TestReleaseHygiene(unittest.TestCase):
    def test_docs_never_prescribe_destructive_repository_recovery(self):
        violations = []
        forbidden = ("git reset --hard", "git clean -fd")
        for path in ROOT.rglob("*.md"):
            if any(part in {"build", "dist", ".git"} for part in path.parts):
                continue
            content = path.read_text(encoding="utf-8", errors="replace").lower()
            if any(command in content for command in forbidden):
                violations.append(str(path.relative_to(ROOT)))
        self.assertEqual(violations, [])

    def test_optional_searxng_stack_is_local_pinned_and_secret_backed(self):
        compose = (ROOT / "infrastructure" / "searxng" / "docker-compose.yml").read_text(
            encoding="utf-8"
        )
        settings = (
            ROOT / "infrastructure" / "searxng" / "searxng" / "settings.yml"
        ).read_text(encoding="utf-8")

        self.assertNotIn(":latest", compose)
        self.assertIn("127.0.0.1:8080:8080", compose)
        self.assertIn("SEARXNG_SECRET: ${SEARXNG_SECRET:?", compose)
        self.assertIn("limiter: true", settings)
        self.assertIn("valkey://valkey:6379/0", settings)

    def test_public_docs_do_not_present_historical_hype_as_proven(self):
        forbidden = (
            "physically replace a 50-member engineering team",
            "perfectly serializes its memory",
            "flawlessly deserializes",
            "allowing infinite runtime",
            "| 0 bugs |",
            "**status:** stable",
            "self-healing, mathematically deterministic software firm",
        )
        violations = []
        for path in ROOT.glob("*.md"):
            content = path.read_text(encoding="utf-8", errors="replace").lower()
            if any(claim in content for claim in forbidden):
                violations.append(path.name)
        self.assertEqual(violations, [])

    def test_package_is_labeled_alpha_until_production_scale_is_proven(self):
        with (ROOT / "pyproject.toml").open("rb") as handle:
            project = tomllib.load(handle)["project"]
        self.assertIn("Development Status :: 3 - Alpha", project["classifiers"])
        self.assertNotIn("Development Status :: 4 - Beta", project["classifiers"])


if __name__ == "__main__":
    unittest.main()
