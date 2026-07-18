#!/usr/bin/env python3
"""Tests for release/version/install manifest parity."""

import json
import os
import sys
import unittest


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from protocol_assets import load_install_manifest, load_version, repo_root  # type: ignore


class TestReleaseManifest(unittest.TestCase):
    def test_version_matches_manifest(self):
        manifest = load_install_manifest()
        self.assertEqual(load_version(), manifest["version"])

    def test_required_root_files_exist(self):
        manifest = load_install_manifest()
        root = repo_root()
        for relative_path in manifest["required_root_files"]:
            with self.subTest(path=relative_path):
                self.assertTrue(
                    os.path.exists(os.path.join(root, relative_path)),
                    msg=f"Missing required root file: {relative_path}",
                )

    def test_required_templates_exist(self):
        manifest = load_install_manifest()
        root = repo_root()
        for relative_path in manifest["required_template_files"]:
            with self.subTest(path=relative_path):
                self.assertTrue(
                    os.path.exists(os.path.join(root, relative_path)),
                    msg=f"Missing required template file: {relative_path}",
                )

    def test_required_plugin_schemas_exist(self):
        manifest = load_install_manifest()
        root = repo_root()
        for relative_path in manifest["required_openclaw_plugin_files"]:
            with self.subTest(path=relative_path):
                path = os.path.join(root, relative_path)
                self.assertTrue(os.path.exists(path), msg=f"Missing plugin schema: {relative_path}")
                with open(path, "r", encoding="utf-8") as handle:
                    data = json.load(handle)
                self.assertIn("name", data)
                self.assertIn("parameters", data)


if __name__ == "__main__":
    unittest.main()
