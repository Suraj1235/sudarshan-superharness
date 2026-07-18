#!/usr/bin/env python3
"""Basic docs/code parity checks for the installable overlay."""

import os
import unittest


REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")


def _read(relative_path):
    with open(os.path.join(REPO_ROOT, relative_path), "r", encoding="utf-8") as handle:
        return handle.read()


class TestDocsParity(unittest.TestCase):
    def test_install_guide_leads_with_standalone_and_preserves_legacy_flow(self):
        content = _read("INSTALL_SUDARSHAN.md")
        self.assertIn("python -m pip install -e .", content)
        self.assertIn("sudarshan doctor", content)
        self.assertIn("Optional OpenClaw Compatibility Install", content)
        self.assertIn("python install.py", content)

    def test_protocol_uses_data_contract_language(self):
        content = _read("SUDARSHAN.md")
        self.assertIn("data contract artifact", content)

    def test_api_contract_mentions_router_bridge(self):
        content = _read("OPENCLAW_API_CONTRACT.md")
        self.assertIn("openclaw_router_bridge.handle_taskmanager", content)

    def test_guide_mentions_new_runtime_modules(self):
        content = _read("SUDARSHAN_Guide_V7_Master.md")
        self.assertIn("heartbeat_daemon.py", content)
        self.assertIn("openclaw_router_bridge.py", content)


if __name__ == "__main__":
    unittest.main()
