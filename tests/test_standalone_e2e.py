import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLI = os.path.join(ROOT, "sudarshan_cli.py")


class _BuildHandler(BaseHTTPRequestHandler):
    outcomes = []
    request_count = 0

    def do_POST(self):
        type(self).request_count += 1
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)
        status, headers, action = type(self).outcomes.pop(0)
        if status == 200:
            payload = {
                "choices": [{"message": {"content": json.dumps(action)}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 25},
            }
        else:
            payload = {"error": {"message": "synthetic rate limit"}}
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        for key, value in headers.items():
            self.send_header(key, value)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *_args):
        return


class TestStandaloneEndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _BuildHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}/v1"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def setUp(self):
        verify_code = (
            "import app; "
            "assert app.add(2, 3) == 5; "
            "assert app.add(-1, 1) == 0"
        )
        _BuildHandler.request_count = 0
        _BuildHandler.outcomes = [
            (429, {"Retry-After": "0"}, None),
            (
                200,
                {},
                {
                    "action": "set_plan",
                    "tasks": [
                        {
                            "id": "T1",
                            "description": "Implement and verify calculator",
                            "status": "in_progress",
                        }
                    ],
                },
            ),
            (
                200,
                {},
                {
                    "action": "write_file",
                    "path": "app.py",
                    "content": "def add(left, right):\n    return left + right\n",
                },
            ),
            (
                200,
                {},
                {
                    "action": "write_file",
                    "path": "test_app.py",
                    "content": (
                        "import unittest\n\n"
                        "from app import add\n\n"
                        "class AddTests(unittest.TestCase):\n"
                        "    def test_add(self):\n"
                        "        self.assertEqual(add(2, 3), 5)\n\n"
                        "if __name__ == '__main__':\n"
                        "    unittest.main()\n"
                    ),
                },
            ),
            (200, {}, {"action": "run_command", "argv": [sys.executable, "-m", "unittest", "-q"]}),
            (
                200,
                {},
                {
                    "action": "set_plan",
                    "tasks": [
                        {
                            "id": "T1",
                            "description": "Implement and verify calculator",
                            "status": "done",
                        }
                    ],
                },
            ),
            (
                200,
                {},
                {"action": "set_verification", "commands": [[sys.executable, "-c", verify_code]]},
            ),
            (
                200,
                {},
                {"action": "finish", "summary": "Calculator module implemented and verified."},
            ),
        ]

    def _run(self, *args):
        return subprocess.run(
            [sys.executable, CLI, *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )

    def test_cli_build_retries_checkpoints_resumes_and_completes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = os.path.join(temp_dir, "calculator")
            first = self._run(
                "build",
                "--idea",
                "Build a production-quality tested Python calculator module",
                "--workspace",
                workspace,
                "--model",
                "scripted-model",
                "--base-url",
                self.base_url,
                "--retry-initial",
                "0",
                "--retry-max",
                "0",
                "--max-new-steps",
                "2",
                "--allow-host-commands",
                "--yes",
                "--json",
            )
            self.assertEqual(first.returncode, 0, first.stderr)
            first_state = json.loads(first.stdout)
            self.assertEqual(first_state["status"], "RUNNING")
            self.assertEqual(first_state["step"], 2)
            self.assertEqual(first_state["retry"]["total_retries"], 1)
            self.assertTrue(os.path.isfile(os.path.join(workspace, "app.py")))

            resumed = self._run(
                "resume",
                "--workspace",
                workspace,
                "--json",
            )
            self.assertEqual(resumed.returncode, 0, resumed.stderr)
            state = json.loads(resumed.stdout)

            self.assertEqual(state["status"], "COMPLETED")
            self.assertEqual(state["step"], 7)
            self.assertEqual(_BuildHandler.request_count, 8)
            self.assertTrue(os.path.isfile(os.path.join(workspace, "test_app.py")))
            self.assertTrue(os.path.isfile(os.path.join(workspace, "COMPLETION_REPORT.md")))
            self.assertTrue(os.path.isdir(os.path.join(workspace, "enterprise_state")))
            self.assertFalse(os.path.exists(os.path.join(workspace, "agent_config.json")))
            self.assertFalse(os.path.exists(os.path.join(workspace, ".swarm_lock")))
            blackboard = json.load(
                open(
                    os.path.join(workspace, "enterprise_state", "BLACKBOARD_STATUS.json"),
                    "r",
                    encoding="utf-8",
                )
            )
            self.assertEqual(blackboard["status"], "COMPLETED")

            state_text = open(
                os.path.join(workspace, ".sudarshan", "engine_state.json"),
                "r",
                encoding="utf-8",
            ).read()
            self.assertNotIn("api_key", state_text.lower())
            run_config = json.load(
                open(
                    os.path.join(workspace, ".sudarshan", "run_config.json"),
                    "r",
                    encoding="utf-8",
                )
            )
            self.assertEqual(run_config["provider"]["base_url"], self.base_url)
            self.assertIn("api_key_env", run_config["provider"])
            self.assertNotIn("api_key", run_config["provider"])


if __name__ == "__main__":
    unittest.main()
