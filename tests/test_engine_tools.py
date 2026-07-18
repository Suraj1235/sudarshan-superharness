import os
import sys
import tempfile
import unittest

from engine_tools import ToolPolicyError, WorkspaceTools


class TestWorkspaceTools(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = self.temp_dir.name
        self.tools = WorkspaceTools(self.workspace)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_read_and_write_are_confined_to_workspace(self):
        written = self.tools.write_file("src/app.py", "print('hello')\n")
        self.assertEqual(written["path"], "src/app.py")
        self.assertEqual(self.tools.read_file("src/app.py")["content"], "print('hello')\n")

        with self.assertRaises(ToolPolicyError):
            self.tools.write_file("../escape.txt", "no")
        with self.assertRaises(ToolPolicyError):
            self.tools.read_file(os.path.abspath(os.path.join(self.workspace, "..", "escape.txt")))

    def test_engine_state_directory_is_reserved(self):
        with self.assertRaisesRegex(ToolPolicyError, "reserved"):
            self.tools.write_file(".sudarshan/engine_state.json", "{}")

    def test_read_is_bounded_and_reports_truncation(self):
        self.tools.write_file("large.txt", "abcdefghij")
        result = self.tools.read_file("large.txt", max_chars=4)
        self.assertEqual(result["content"], "abcd")
        self.assertTrue(result["truncated"])

    def test_exact_text_edit_is_atomic_and_rejects_ambiguous_matches(self):
        self.tools.write_file("app.py", "VALUE = 1\nOTHER = 1\n")

        result = self.tools.edit_file(
            "app.py",
            old_text="VALUE = 1",
            new_text="VALUE = 2",
        )

        self.assertEqual(result["replacements"], 1)
        self.assertEqual(
            self.tools.read_file("app.py")["content"],
            "VALUE = 2\nOTHER = 1\n",
        )
        with self.assertRaisesRegex(ToolPolicyError, "expected 1 exact match"):
            self.tools.edit_file("app.py", old_text=" = ", new_text=" == ")

    def test_list_files_is_stable_and_hides_engine_state(self):
        self.tools.write_file("z.txt", "z")
        self.tools.write_file("a/a.txt", "a")
        os.makedirs(os.path.join(self.workspace, ".sudarshan"), exist_ok=True)
        with open(os.path.join(self.workspace, ".sudarshan", "secret.json"), "w") as handle:
            handle.write("{}")

        result = self.tools.list_files()

        self.assertEqual(result["files"], ["a/a.txt", "z.txt"])

    def test_command_requires_argument_array_and_allowlisted_executable(self):
        with self.assertRaisesRegex(ToolPolicyError, "argument array"):
            self.tools.run_command("python -V")
        with self.assertRaisesRegex(ToolPolicyError, "not allowed"):
            self.tools.run_command(["powershell", "-Command", "Write-Host no"])
        with self.assertRaisesRegex(ToolPolicyError, "destructive"):
            self.tools.run_command(["git", "reset", "--hard"])

    def test_command_captures_and_caps_output(self):
        result = self.tools.run_command(
            [sys.executable, "-c", "import sys; print('123456'); print('err', file=sys.stderr)"],
            max_output_chars=4,
        )
        self.assertEqual(result["returncode"], 0)
        self.assertEqual(result["stdout"], "1234")
        self.assertTrue(result["stdout_truncated"])
        self.assertEqual(result["stderr"], "err\n")

    def test_command_drains_high_volume_output_without_exceeding_the_cap(self):
        result = self.tools.run_command(
            [
                sys.executable,
                "-c",
                "import sys; sys.stdout.write('x' * 1000000); "
                "sys.stderr.write('y' * 1000000)",
            ],
            max_output_chars=128,
        )
        self.assertEqual(result["returncode"], 0)
        self.assertEqual(len(result["stdout"]), 128)
        self.assertEqual(len(result["stderr"]), 128)
        self.assertTrue(result["stdout_truncated"])
        self.assertTrue(result["stderr_truncated"])

    def test_command_timeout_returns_observation(self):
        result = self.tools.run_command(
            [sys.executable, "-c", "import time; time.sleep(2)"],
            timeout_seconds=0.1,
        )
        self.assertTrue(result["timed_out"])
        self.assertIsNone(result["returncode"])

    def test_sensitive_environment_values_are_not_forwarded(self):
        old = os.environ.get("SUDARSHAN_TEST_API_KEY")
        os.environ["SUDARSHAN_TEST_API_KEY"] = "never-forward-this"
        try:
            result = self.tools.run_command(
                [
                    sys.executable,
                    "-c",
                    "import os; print(os.environ.get('SUDARSHAN_TEST_API_KEY', 'missing'))",
                ]
            )
        finally:
            if old is None:
                os.environ.pop("SUDARSHAN_TEST_API_KEY", None)
            else:
                os.environ["SUDARSHAN_TEST_API_KEY"] = old
        self.assertEqual(result["stdout"].strip(), "missing")


if __name__ == "__main__":
    unittest.main()
