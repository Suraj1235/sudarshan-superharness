import json
import os
import subprocess
import sys
import tempfile
import unittest

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.9 and 3.10
    import tomli as tomllib

from autonomous_engine import AutonomousEngine, EngineConfig
from providers import ModelResponse
from sudarshan_cli import _apply_saved_run_config, build_parser


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLI = os.path.join(ROOT, "sudarshan_cli.py")


class _OneActionProvider:
    model = "scripted-model"

    def complete(self, _messages, **_kwargs):
        return ModelResponse(
            text=json.dumps(
                {
                    "action": "set_plan",
                    "tasks": [{"id": "T1", "description": "Build", "status": "pending"}],
                }
            ),
            input_tokens=1,
            output_tokens=1,
            provider="scripted",
            model=self.model,
        )


def run_cli(*args, env=None):
    return subprocess.run(
        [sys.executable, CLI, *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=30,
    )


class TestSudarshanCLI(unittest.TestCase):
    def test_resume_provider_switch_does_not_reuse_old_provider_endpoint_or_key_name(self):
        with tempfile.TemporaryDirectory() as workspace:
            state_dir = os.path.join(workspace, ".sudarshan")
            os.makedirs(state_dir)
            with open(
                os.path.join(state_dir, "run_config.json"), "w", encoding="utf-8"
            ) as handle:
                json.dump(
                    {
                        "schema_version": 1,
                        "provider": {
                            "kind": "openai-compatible",
                            "base_url": "https://old-provider.example/v1",
                            "api_key_env": "OLD_PROVIDER_KEY",
                            "timeout_seconds": 45,
                        },
                        "engine": {"max_steps": 77},
                    },
                    handle,
                )
            args = build_parser().parse_args(
                ["resume", "--workspace", workspace, "--provider", "gemini"]
            )

            _apply_saved_run_config(args)

            self.assertEqual(args.provider, "gemini")
            self.assertIsNone(args.base_url)
            self.assertIsNone(args.api_key_env)
            self.assertEqual(args.provider_timeout, 120.0)
            self.assertEqual(args.max_steps, 77)

    def test_doctor_has_no_openclaw_docker_or_searxng_prerequisite(self):
        result = run_cli("doctor", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertTrue(report["ready"])
        self.assertFalse(report["requirements"]["openclaw"])
        self.assertEqual(report["requirements"]["python"]["status"], "ready")
        self.assertEqual(report["optional"]["docker"]["required"], False)
        self.assertEqual(report["optional"]["searxng"]["required"], False)

    def test_estimate_writes_auditable_json(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = os.path.join(temp_dir, "estimate.json")
            result = run_cli(
                "estimate",
                "--idea",
                "Build a React dashboard with an API and tests",
                "--model",
                "example-model",
                "--input-price",
                "1.5",
                "--output-price",
                "6",
                "--output",
                output,
                "--json",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            printed = json.loads(result.stdout)
            with open(output, "r", encoding="utf-8") as handle:
                written = json.load(handle)
            self.assertEqual(printed, written)
            self.assertEqual(written["model"], "example-model")

    def test_build_dry_run_needs_no_key_and_does_not_mutate_workspace(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = os.path.join(temp_dir, "new-project")
            result = run_cli(
                "build",
                "--idea",
                "Build a tested CLI",
                "--workspace",
                workspace,
                "--model",
                "example-model",
                "--dry-run",
                "--json",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertTrue(report["dry_run"])
            self.assertFalse(os.path.exists(workspace))

    def test_build_rejects_parallel_timeline_claim_for_sequential_engine(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = os.path.join(temp_dir, "new-project")
            result = run_cli(
                "build",
                "--idea",
                "Build a tested CLI",
                "--workspace",
                workspace,
                "--model",
                "example-model",
                "--concurrency",
                "2",
                "--dry-run",
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("sequential", result.stderr.lower())
            self.assertFalse(os.path.exists(workspace))

    def test_remote_build_rejects_missing_environment_key_before_writing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = os.path.join(temp_dir, "project")
            env = os.environ.copy()
            env.pop("SUDARSHAN_TEST_MISSING_KEY", None)
            result = run_cli(
                "build",
                "--idea",
                "Build a tested CLI",
                "--workspace",
                workspace,
                "--model",
                "example-model",
                "--base-url",
                "https://example.com/v1",
                "--api-key-env",
                "SUDARSHAN_TEST_MISSING_KEY",
                "--yes",
                env=env,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("SUDARSHAN_TEST_MISSING_KEY", result.stderr)
            self.assertFalse(os.path.exists(os.path.join(workspace, ".sudarshan")))

    def test_native_provider_defaults_use_their_standard_key_environment(self):
        for provider, key_name in (
            ("anthropic", "ANTHROPIC_API_KEY"),
            ("gemini", "GEMINI_API_KEY"),
        ):
            with self.subTest(provider=provider), tempfile.TemporaryDirectory() as temp_dir:
                workspace = os.path.join(temp_dir, "project")
                env = os.environ.copy()
                env.pop(key_name, None)
                result = run_cli(
                    "build",
                    "--idea",
                    "Build a tested CLI",
                    "--workspace",
                    workspace,
                    "--model",
                    "example-model",
                    "--provider",
                    provider,
                    "--yes",
                    env=env,
                )
                self.assertEqual(result.returncode, 2)
                self.assertIn(key_name, result.stderr)
                self.assertFalse(os.path.exists(os.path.join(workspace, ".sudarshan")))

    def test_build_requires_explicit_host_command_consent(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = os.path.join(temp_dir, "project")
            result = run_cli(
                "build",
                "--idea",
                "Build a tested CLI",
                "--workspace",
                workspace,
                "--model",
                "local-model",
                "--base-url",
                "http://127.0.0.1:1/v1",
                "--yes",
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("host commands", result.stderr.lower())
            self.assertFalse(os.path.exists(os.path.join(workspace, ".sudarshan")))

    def test_command_provider_bridges_an_arbitrary_agent_framework(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = os.path.join(temp_dir, "project")
            bridge = os.path.join(temp_dir, "bridge.py")
            with open(bridge, "w", encoding="utf-8") as handle:
                handle.write(
                    "import json, sys\n"
                    "json.load(sys.stdin)\n"
                    "action = {'action': 'set_plan', 'tasks': "
                    "[{'id': 'T1', 'description': 'Bridge task', 'status': 'pending'}]}\n"
                    "print(json.dumps({'text': json.dumps(action), "
                    "'input_tokens': 5, 'output_tokens': 2}))\n"
                )
            result = run_cli(
                "build",
                "--idea",
                "Build through an external framework",
                "--workspace",
                workspace,
                "--model",
                "framework-model",
                "--provider",
                "command",
                "--provider-command-json",
                json.dumps([sys.executable, bridge]),
                "--verify-command-json",
                json.dumps([sys.executable, "-c", "raise SystemExit(0)"]),
                "--max-new-steps",
                "1",
                "--allow-host-commands",
                "--yes",
                "--json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            state = json.loads(result.stdout)
            self.assertEqual(state["status"], "RUNNING")
            self.assertEqual(state["plan"][0]["description"], "Bridge task")
            self.assertEqual(len(state["required_verification_commands"]), 1)
            with open(
                os.path.join(workspace, ".sudarshan", "run_config.json"),
                "r",
                encoding="utf-8",
            ) as handle:
                run_config = json.load(handle)
            self.assertEqual(run_config["provider"]["kind"], "command")

    def test_checked_in_command_bridge_demo_completes_a_verified_build(self):
        bridge = os.path.join(ROOT, "examples", "demo_command_bridge.py")
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = os.path.join(temp_dir, "project")
            result = run_cli(
                "build",
                "--idea",
                "Build a tested calculator library",
                "--workspace",
                workspace,
                "--model",
                "demo-model",
                "--provider",
                "command",
                "--provider-command-json",
                json.dumps([sys.executable, bridge]),
                "--allow-host-commands",
                "--yes",
                "--json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            state = json.loads(result.stdout)
            self.assertEqual(state["status"], "COMPLETED")
            self.assertEqual(state["step"], 6)
            self.assertTrue(os.path.isfile(os.path.join(workspace, "COMPLETION_REPORT.md")))

    def test_status_reads_durable_engine_state(self):
        with tempfile.TemporaryDirectory() as workspace:
            engine = AutonomousEngine(
                EngineConfig(
                    workspace_root=workspace,
                    directive="Build a demo",
                    model="scripted-model",
                ),
                _OneActionProvider(),
            )
            engine.run(max_new_steps=1)

            result = run_cli("status", "--workspace", workspace, "--json")

            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["status"], "RUNNING")
            self.assertEqual(report["step"], 1)
            self.assertEqual(report["plan"][0]["id"], "T1")

    def test_packaging_and_install_manifest_include_standalone_runtime(self):
        with open(os.path.join(ROOT, "pyproject.toml"), "rb") as handle:
            project = tomllib.load(handle)
        self.assertEqual(project["project"]["scripts"]["sudarshan"], "sudarshan_cli:main")
        self.assertEqual(project["project"]["authors"][0]["name"], "Suraj Kuncham")

        with open(os.path.join(ROOT, "install_manifest.json"), "r", encoding="utf-8") as handle:
            manifest = json.load(handle)
        for path in (
            "estimator.py",
            "providers.py",
            "engine_tools.py",
            "process_runner.py",
            "autonomous_engine.py",
            "sudarshan_cli.py",
            "pyproject.toml",
        ):
            self.assertIn(path, manifest["required_root_files"])


if __name__ == "__main__":
    unittest.main()
