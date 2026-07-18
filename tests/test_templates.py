#!/usr/bin/env python3
"""Tests for template loading and parity."""

import json
import os
import sys
import unittest


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from protocol_assets import (  # type: ignore
    load_install_manifest,
    load_version,
    load_template_json,
    load_template_text,
    repo_root,
)


class TestTemplates(unittest.TestCase):
    def test_json_templates_parse(self):
        manifest = load_install_manifest()
        for relative_path in manifest["required_template_files"]:
            if not relative_path.endswith(".json"):
                continue
            relative_template = relative_path.split("templates/", 1)[1]
            with self.subTest(path=relative_template):
                data = load_template_json(relative_template)
                self.assertIsInstance(data, (dict, list))

    def test_text_templates_are_nonempty(self):
        manifest = load_install_manifest()
        for relative_path in manifest["required_template_files"]:
            if relative_path.endswith(".json"):
                continue
            relative_template = relative_path.split("templates/", 1)[1]
            with self.subTest(path=relative_template):
                content = load_template_text(relative_template)
                self.assertTrue(content.strip())

    def test_architecture_template_uses_current_version(self):
        content = load_template_text("enterprise_state/ARCHITECTURE_STATE.md")
        self.assertIn(load_version(), content)

    def test_manifest_template_paths_resolve_under_repo_root(self):
        manifest = load_install_manifest()
        root = repo_root()
        for relative_path in manifest["required_template_files"]:
            with self.subTest(path=relative_path):
                self.assertTrue(os.path.isfile(os.path.join(root, relative_path)))


if __name__ == "__main__":
    unittest.main()
