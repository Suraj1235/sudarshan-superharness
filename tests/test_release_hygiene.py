#!/usr/bin/env python3
"""Public-release hygiene checks for documentation and generated artifacts."""

from pathlib import Path
import re
import subprocess
import unittest
import xml.etree.ElementTree as ET

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.9 and 3.10
    import tomli as tomllib


ROOT = Path(__file__).resolve().parents[1]


def _tracked_files():
    try:
        result = subprocess.run(
            ["git", "-C", str(ROOT), "ls-files", "-z"],
            check=True,
            capture_output=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return [
            path.relative_to(ROOT)
            for path in ROOT.rglob("*")
            if path.is_file()
            and not any(part in {".git", "build", "dist"} for part in path.parts)
        ]
    return [Path(item.decode("utf-8")) for item in result.stdout.split(b"\0") if item]


class TestReleaseHygiene(unittest.TestCase):
    def test_git_tracks_no_runtime_state_secrets_or_generated_bundles(self):
        forbidden_roots = {
            ".sudarshan",
            ".tmp",
            "enterprise_state",
            "isolated_tasks",
            "node_modules",
            "build",
            "dist",
        }
        forbidden_names = {
            ".env",
            ".swarm_lock",
            ".resume_lock",
            "engine_state.json",
            "events.jsonl",
            "run_config.json",
            "live_status.json",
            "HUMAN_INPUT.txt",
            "RECOVERY_MANIFEST.json",
        }
        forbidden_suffixes = {
            ".bak",
            ".db",
            ".key",
            ".log",
            ".p12",
            ".pem",
            ".pfx",
            ".sqlite",
            ".tmp",
            ".whl",
            ".zip",
        }
        violations = []
        for path in _tracked_files():
            if path.parts and path.parts[0] in forbidden_roots:
                violations.append(path.as_posix())
                continue
            if path.name in forbidden_names or path.name.startswith(".env."):
                violations.append(path.as_posix())
                continue
            if path.suffix.lower() in forbidden_suffixes:
                violations.append(path.as_posix())
        self.assertEqual(violations, [])

    def test_tracked_text_has_no_private_machine_paths_or_key_material(self):
        machine_path = re.compile(r"(?:[A-Za-z]:\\Users\\|/Users/[^/]+/|/home/[^/]+/)")
        private_key = re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")
        token_prefix = re.compile(
            r"(?:github_pat_[A-Za-z0-9_]{20,}|ghp_[A-Za-z0-9]{20,}|"
            r"AKIA[0-9A-Z]{16}|sk-(?:live|proj)-[A-Za-z0-9_-]{16,})"
        )
        azure_host = re.compile(r"([A-Za-z0-9_-]+)\.services\.ai\.azure\.com")
        violations = []
        for relative in _tracked_files():
            if relative == Path("tests/test_release_hygiene.py"):
                continue
            path = ROOT / relative
            if not path.exists() or path.suffix.lower() in {
                ".gif",
                ".ico",
                ".jpg",
                ".jpeg",
                ".png",
            }:
                continue
            try:
                content = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            if machine_path.search(content):
                violations.append(f"machine path: {relative.as_posix()}")
            if private_key.search(content) or token_prefix.search(content):
                violations.append(f"key material: {relative.as_posix()}")
            for match in azure_host.finditer(content):
                if match.group(1) != "YOUR_RESOURCE":
                    violations.append(f"specific Azure host: {relative.as_posix()}")
        self.assertEqual(violations, [])

    def test_readme_visual_assets_exist_and_svg_assets_parse(self):
        content = (ROOT / "README.md").read_text(encoding="utf-8")
        assets = re.findall(r'src="(docs/assets/[^"]+)"', content)
        self.assertGreaterEqual(len(assets), 4)
        for relative in assets:
            path = ROOT / relative
            self.assertTrue(path.is_file(), relative)
            if path.suffix == ".svg":
                ET.parse(path)

    def test_readme_is_grounded_in_the_v169_master_guide(self):
        content = (ROOT / "README.md").read_text(encoding="utf-8")
        required = (
            "SUDARSHAN_Guide_V7_Master.md",
            "The Adversarial Hierarchy",
            "The Phase and Gate Machine",
            "Architecture Invariants",
            "Research Agenda",
            "OpenClaw is a compatibility adapter, not a dependency.",
            "not a prompt file",
        )
        for phrase in required:
            self.assertIn(phrase, content)

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
