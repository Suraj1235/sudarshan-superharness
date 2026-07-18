import json
import os
import sys
import tempfile
import unittest

from quality_gate import detect_verification_commands


class TestQualityGate(unittest.TestCase):
    def test_python_project_gets_compile_and_test_commands(self):
        with tempfile.TemporaryDirectory() as workspace:
            with open(os.path.join(workspace, "app.py"), "w", encoding="utf-8") as handle:
                handle.write("VALUE = 1\n")
            with open(os.path.join(workspace, "test_app.py"), "w", encoding="utf-8") as handle:
                handle.write("import unittest\n")

            commands = detect_verification_commands(workspace)

            self.assertIn([sys.executable, "-m", "compileall", "-q", "."], commands)
            self.assertIn([sys.executable, "-m", "unittest", "discover", "-q"], commands)

    def test_package_scripts_are_detected_without_shell_strings(self):
        with tempfile.TemporaryDirectory() as workspace:
            with open(os.path.join(workspace, "package.json"), "w", encoding="utf-8") as handle:
                json.dump(
                    {"scripts": {"lint": "eslint .", "test": "vitest", "build": "vite build"}},
                    handle,
                )

            commands = detect_verification_commands(workspace)

            self.assertEqual(
                commands,
                [["npm", "run", "lint"], ["npm", "test", "--", "--run"], ["npm", "run", "build"]],
            )
