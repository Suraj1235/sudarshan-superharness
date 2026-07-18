import json
import os
import sys
import tempfile
import threading
import unittest

from autonomous_engine import (
    ActionValidationError,
    AutonomousEngine,
    EngineConfig,
    EngineBusyError,
    parse_action,
)
from providers import ModelResponse, ProviderError
from safe_edit import acquire_lock, release_lock


class ScriptedProvider:
    model = "scripted-model"

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []
        self.call_options = []

    def complete(self, messages, **kwargs):
        self.calls.append(messages)
        self.call_options.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        if isinstance(outcome, ModelResponse):
            return outcome
        return ModelResponse(
            text=json.dumps(outcome),
            input_tokens=100,
            output_tokens=25,
            provider="scripted",
            model=self.model,
        )


def action_response(action, *, input_tokens=100, output_tokens=25):
    return ModelResponse(
        text=json.dumps(action),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        provider="scripted",
        model="scripted-model",
    )


class TestActionParsing(unittest.TestCase):
    def test_accepts_fenced_single_json_object(self):
        action = parse_action('```json\n{"action":"list_files","path":"."}\n```')
        self.assertEqual(action["action"], "list_files")

    def test_rejects_unknown_actions_and_shell_commands(self):
        with self.assertRaisesRegex(ActionValidationError, "unsupported"):
            parse_action('{"action":"launch_missiles"}')
        with self.assertRaisesRegex(ActionValidationError, "argument array"):
            parse_action('{"action":"run_command","argv":"python -V"}')

    def test_rejects_non_finite_json_numbers(self):
        with self.assertRaisesRegex(ActionValidationError, "non-finite"):
            parse_action(
                '{"action":"run_command","argv":["python","-V"],'
                '"timeout_seconds":NaN}'
            )


class TestAutonomousEngine(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = self.temp_dir.name

    def tearDown(self):
        self.temp_dir.cleanup()

    def config(self, **overrides):
        values = {
            "workspace_root": self.workspace,
            "directive": "Build a tested calculator",
            "model": "scripted-model",
            "max_steps": 20,
            "retry_initial_seconds": 2,
            "retry_max_seconds": 30,
            "allow_host_commands": True,
        }
        values.update(overrides)
        return EngineConfig(**values)

    def test_engine_config_rejects_invalid_runtime_limits(self):
        with self.assertRaisesRegex(ValueError, "token ceilings"):
            self.config(max_input_tokens=-1)
        with self.assertRaisesRegex(ValueError, "per-call output"):
            self.config(max_output_tokens_per_call=0)
        with self.assertRaisesRegex(ValueError, "command timeout"):
            self.config(command_timeout_seconds=0)

    def test_checkpoints_plan_after_each_step(self):
        provider = ScriptedProvider(
            [
                {
                    "action": "set_plan",
                    "tasks": [
                        {"id": "T1", "description": "Implement calculator", "status": "pending"}
                    ],
                }
            ]
        )
        engine = AutonomousEngine(self.config(), provider)

        state = engine.run(max_new_steps=1)

        self.assertEqual(state["step"], 1)
        self.assertEqual(state["plan"][0]["id"], "T1")
        state_path = os.path.join(self.workspace, ".sudarshan", "engine_state.json")
        with open(state_path, "r", encoding="utf-8") as handle:
            persisted = json.load(handle)
        self.assertEqual(persisted["step"], 1)
        self.assertEqual(persisted["status"], "RUNNING")

    def test_plan_updates_cannot_delete_previously_committed_tasks(self):
        provider = ScriptedProvider(
            [
                {
                    "action": "set_plan",
                    "tasks": [
                        {"id": "T1", "description": "Build", "status": "in_progress"},
                        {"id": "T2", "description": "Test", "status": "pending", "depends_on": ["T1"]},
                    ],
                },
                {
                    "action": "set_plan",
                    "tasks": [{"id": "T1", "description": "Build", "status": "done"}],
                },
            ]
        )
        engine = AutonomousEngine(self.config(), provider)

        state = engine.run(max_new_steps=2)

        self.assertEqual([task["id"] for task in state["plan"]], ["T1", "T2"])
        self.assertFalse(state["recent_events"][-1]["observation"]["ok"])
        self.assertIn("cannot remove", state["recent_events"][-1]["observation"]["error"])

    def test_plan_cannot_complete_task_before_dependencies(self):
        provider = ScriptedProvider(
            [
                {
                    "action": "set_plan",
                    "tasks": [
                        {"id": "T1", "description": "Build", "status": "pending"},
                        {"id": "T2", "description": "Test", "status": "done", "depends_on": ["T1"]},
                    ],
                }
            ]
        )
        engine = AutonomousEngine(self.config(), provider)

        state = engine.run(max_new_steps=1)

        self.assertEqual(state["plan"], [])
        self.assertFalse(state["recent_events"][-1]["observation"]["ok"])
        self.assertIn("unfinished dependencies", state["recent_events"][-1]["observation"]["error"])

    def test_new_engine_instance_resumes_durable_state(self):
        first = AutonomousEngine(
            self.config(),
            ScriptedProvider(
                [
                    {
                        "action": "set_plan",
                        "tasks": [
                            {"id": "T1", "description": "Write app", "status": "in_progress"}
                        ],
                    }
                ]
            ),
        )
        first.run(max_new_steps=1)

        resumed = AutonomousEngine(
            self.config(),
            ScriptedProvider(
                [{"action": "write_file", "path": "app.py", "content": "print('ok')\n"}]
            ),
        )
        state = resumed.run(max_new_steps=1)

        self.assertEqual(state["step"], 2)
        with open(os.path.join(self.workspace, "app.py"), "r", encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "print('ok')\n")

    def test_rate_limit_waits_then_recovers(self):
        waits = []
        now = [1000.0]

        def sleep(seconds):
            waits.append(seconds)
            now[0] += seconds

        provider = ScriptedProvider(
            [
                ProviderError(
                    "rate limited",
                    status_code=429,
                    retryable=True,
                    retry_after_seconds=7,
                ),
                {
                    "action": "set_plan",
                    "tasks": [{"id": "T1", "description": "Recover", "status": "pending"}],
                },
            ]
        )
        engine = AutonomousEngine(self.config(), provider, sleep=sleep, clock=lambda: now[0])

        state = engine.run(max_new_steps=1)

        self.assertEqual(waits, [7.0])
        self.assertEqual(state["status"], "RUNNING")
        self.assertEqual(state["retry"]["total_retries"], 1)

    def test_provider_retry_after_is_not_shortened_by_local_backoff_cap(self):
        waits = []
        now = [1000.0]

        def sleep(seconds):
            waits.append(seconds)
            now[0] += seconds

        provider = ScriptedProvider(
            [
                ProviderError(
                    "rate limited",
                    status_code=429,
                    retryable=True,
                    retry_after_seconds=120,
                ),
                {
                    "action": "set_plan",
                    "tasks": [{"id": "T1", "description": "Recover", "status": "pending"}],
                },
            ]
        )
        engine = AutonomousEngine(
            self.config(retry_initial_seconds=2, retry_max_seconds=30),
            provider,
            sleep=sleep,
            clock=lambda: now[0],
        )

        state = engine.run(max_new_steps=1)

        self.assertEqual(waits, [120.0])
        self.assertEqual(state["retry"]["total_retries"], 1)

    def test_retry_elapsed_window_prevents_unbounded_default_wait(self):
        waits = []
        now = [1000.0]

        def sleep(seconds):
            waits.append(seconds)
            now[0] += seconds

        transient = ProviderError("busy", status_code=503, retryable=True)
        provider = ScriptedProvider([transient, transient])
        engine = AutonomousEngine(
            self.config(
                retry_initial_seconds=2,
                retry_max_seconds=2,
                max_retry_elapsed_seconds=3,
            ),
            provider,
            sleep=sleep,
            clock=lambda: now[0],
        )

        state = engine.run(max_new_steps=1)

        self.assertEqual(waits, [2])
        self.assertEqual(state["status"], "FAILED")
        self.assertIn("retry elapsed-time limit", state["last_error"])

    def test_noncompliant_provider_cannot_execute_action_after_budget_overshoot(self):
        provider = ScriptedProvider(
            [
                action_response(
                    {"action": "write_file", "path": "should-not-exist.txt", "content": "x"},
                    input_tokens=1_000_000,
                    output_tokens=1_000_000,
                )
            ]
        )
        engine = AutonomousEngine(
            self.config(
                input_price_per_million=2,
                output_price_per_million=8,
                max_cost_usd=5,
            ),
            provider,
        )

        state = engine.run(max_new_steps=1)

        self.assertEqual(state["status"], "BUDGET_EXCEEDED")
        self.assertFalse(os.path.exists(os.path.join(self.workspace, "should-not-exist.txt")))
        self.assertEqual(state["usage"]["cost_usd"], 10.0)
        self.assertLess(provider.call_options[0]["max_output_tokens"], 1_000_000)

    def test_remaining_output_budget_is_passed_to_provider(self):
        provider = ScriptedProvider(
            [
                action_response({"action": "list_files", "path": "."}, output_tokens=4),
                action_response({"action": "list_files", "path": "."}, output_tokens=4),
            ]
        )
        engine = AutonomousEngine(self.config(max_output_tokens=10), provider)

        state = engine.run(max_new_steps=2)

        self.assertEqual(
            [options["max_output_tokens"] for options in provider.call_options],
            [10, 6],
        )
        self.assertEqual(state["usage"]["output_tokens"], 8)

    def test_default_per_call_output_cap_is_passed_to_provider(self):
        provider = ScriptedProvider([{"action": "list_files", "path": "."}])
        engine = AutonomousEngine(self.config(), provider)

        engine.run(max_new_steps=1)

        self.assertEqual(provider.call_options[0]["max_output_tokens"], 8192)

    def test_per_call_output_cap_limits_a_larger_cumulative_budget(self):
        provider = ScriptedProvider([{"action": "list_files", "path": "."}])
        engine = AutonomousEngine(
            self.config(
                max_output_tokens=100_000,
                max_output_tokens_per_call=4096,
            ),
            provider,
        )

        engine.run(max_new_steps=1)

        self.assertEqual(provider.call_options[0]["max_output_tokens"], 4096)

    def test_per_call_cap_limits_a_large_affordable_cost_budget(self):
        provider = ScriptedProvider([{"action": "list_files", "path": "."}])
        engine = AutonomousEngine(
            self.config(
                max_cost_usd=100,
                input_price_per_million=1,
                output_price_per_million=4,
            ),
            provider,
        )

        engine.run(max_new_steps=1)

        self.assertEqual(provider.call_options[0]["max_output_tokens"], 8192)

    def test_input_budget_stops_before_oversized_prompt_is_sent(self):
        provider = ScriptedProvider([{"action": "list_files", "path": "."}])
        engine = AutonomousEngine(self.config(max_input_tokens=1), provider)

        state = engine.run(max_new_steps=1)

        self.assertEqual(state["status"], "BUDGET_EXCEEDED")
        self.assertEqual(provider.calls, [])
        self.assertEqual(state["usage"]["input_tokens"], 0)

    def test_cost_budget_caps_provider_output_before_request(self):
        provider = ScriptedProvider(
            [action_response({"action": "list_files", "path": "."}, output_tokens=3)]
        )
        engine = AutonomousEngine(
            self.config(
                max_cost_usd=3,
                input_price_per_million=0,
                output_price_per_million=1_000_000,
            ),
            provider,
        )

        state = engine.run(max_new_steps=1)

        self.assertEqual(provider.call_options[0]["max_output_tokens"], 3)
        self.assertLessEqual(state["usage"]["cost_usd"], 3)

    def test_cost_budget_stops_before_unaffordable_prompt_is_sent(self):
        provider = ScriptedProvider([{"action": "list_files", "path": "."}])
        engine = AutonomousEngine(
            self.config(
                max_cost_usd=1,
                input_price_per_million=1_000_000,
                output_price_per_million=0,
            ),
            provider,
        )

        state = engine.run(max_new_steps=1)

        self.assertEqual(state["status"], "BUDGET_EXCEEDED")
        self.assertEqual(provider.calls, [])
        self.assertEqual(state["usage"]["cost_usd"], 0)

    def test_human_request_pauses_and_can_be_resumed(self):
        engine = AutonomousEngine(
            self.config(),
            ScriptedProvider(
                [{"action": "request_human", "question": "Which database region?"}]
            ),
        )
        state = engine.run(max_new_steps=1)
        self.assertEqual(state["status"], "WAITING_HUMAN")
        self.assertEqual(state["human_request"]["question"], "Which database region?")

        engine.provide_human_input("Use eu-west-1")
        self.assertEqual(engine.state["status"], "RUNNING")
        self.assertIsNone(engine.state["human_request"])
        self.assertIn("eu-west-1", engine.state["recent_events"][-1]["observation"]["input"])

    def test_only_one_engine_process_can_run_a_workspace(self):
        started = threading.Event()
        release = threading.Event()

        class BlockingProvider:
            model = "scripted-model"

            def complete(self, _messages, **_kwargs):
                started.set()
                release.wait(timeout=2)
                return action_response(
                    {
                        "action": "set_plan",
                        "tasks": [{"id": "T1", "description": "Build", "status": "pending"}],
                    }
                )

        config = self.config(run_lock_timeout_seconds=0.05)
        first = AutonomousEngine(config, BlockingProvider())
        second = AutonomousEngine(config, ScriptedProvider([]))
        thread = threading.Thread(target=first.run, kwargs={"max_new_steps": 1})
        thread.start()
        self.assertTrue(started.wait(timeout=1))

        try:
            with self.assertRaises(EngineBusyError):
                second.run(max_new_steps=1)
        finally:
            release.set()
            thread.join(timeout=3)

        self.assertFalse(thread.is_alive())

    def test_human_input_respects_the_workspace_run_lease(self):
        config = self.config(run_lock_timeout_seconds=0.05)
        engine = AutonomousEngine(
            config,
            ScriptedProvider(
                [{"action": "request_human", "question": "Which database region?"}]
            ),
        )
        engine.run(max_new_steps=1)
        lock_target = os.path.join(self.workspace, ".sudarshan", "engine_run")
        lock_id = acquire_lock(lock_target, "other-process", timeout_sec=60)

        try:
            with self.assertRaises(EngineBusyError):
                engine.provide_human_input("Use eu-west-1")
        finally:
            release_lock(lock_target, "other-process", lock_id)

    def test_host_commands_require_explicit_authorization(self):
        provider = ScriptedProvider(
            [
                {
                    "action": "set_plan",
                    "tasks": [{"id": "T1", "description": "Build", "status": "in_progress"}],
                },
                {"action": "run_command", "argv": [sys.executable, "-c", "print('no')"]},
            ]
        )
        engine = AutonomousEngine(self.config(allow_host_commands=False), provider)

        state = engine.run(max_new_steps=2)

        observation = state["recent_events"][-1]["observation"]
        self.assertFalse(observation["ok"])
        self.assertIn("authorization", observation["error"].lower())

    def test_failed_verification_blocks_finish(self):
        provider = ScriptedProvider(
            [
                {
                    "action": "set_plan",
                    "tasks": [{"id": "T1", "description": "Build", "status": "done"}],
                },
                {
                    "action": "set_verification",
                    "commands": [[sys.executable, "-c", "raise SystemExit(3)"]],
                },
                {"action": "finish", "summary": "Done"},
            ]
        )
        engine = AutonomousEngine(self.config(), provider)

        state = engine.run(max_new_steps=3)

        self.assertEqual(state["status"], "RUNNING")
        self.assertIsNone(state["completion"])
        observation = state["recent_events"][-1]["observation"]
        self.assertFalse(observation["ok"])
        self.assertIn("verification", observation["error"].lower())

    def test_model_cannot_weaken_automatic_python_verification(self):
        provider = ScriptedProvider(
            [
                {
                    "action": "set_plan",
                    "tasks": [{"id": "T1", "description": "Build", "status": "in_progress"}],
                },
                {"action": "write_file", "path": "broken.py", "content": "def broken(:\n"},
                {
                    "action": "set_plan",
                    "tasks": [{"id": "T1", "description": "Build", "status": "done"}],
                },
                {
                    "action": "set_verification",
                    "commands": [[sys.executable, "-c", "raise SystemExit(0)"]],
                },
                {"action": "finish", "summary": "Claimed done"},
            ]
        )
        engine = AutonomousEngine(self.config(), provider)

        state = engine.run(max_new_steps=5)

        self.assertEqual(state["status"], "RUNNING")
        observation = state["recent_events"][-1]["observation"]
        self.assertFalse(observation["ok"])
        self.assertIn("verification failed", observation["error"])

    def test_operator_verification_contract_is_immutable(self):
        required = ((sys.executable, "-c", "raise SystemExit(9)"),)
        provider = ScriptedProvider(
            [
                {
                    "action": "set_plan",
                    "tasks": [{"id": "T1", "description": "Build", "status": "done"}],
                },
                {
                    "action": "set_verification",
                    "commands": [[sys.executable, "-c", "raise SystemExit(0)"]],
                },
                {"action": "finish", "summary": "Claimed done"},
            ]
        )
        engine = AutonomousEngine(
            self.config(required_verification_commands=required),
            provider,
        )

        state = engine.run(max_new_steps=3)

        self.assertEqual(state["status"], "RUNNING")
        self.assertEqual(state["required_verification_commands"], [list(required[0])])
        self.assertIn("verification failed", state["recent_events"][-1]["observation"]["error"])

    def test_successful_multi_step_build_requires_plan_and_verification(self):
        verify = (
            "import pathlib; "
            "assert pathlib.Path('calculator.py').read_text(encoding='utf-8').strip() == 'print(2 + 2)'"
        )
        provider = ScriptedProvider(
            [
                {
                    "action": "set_plan",
                    "tasks": [{"id": "T1", "description": "Build calculator", "status": "in_progress"}],
                },
                {"action": "write_file", "path": "calculator.py", "content": "print(2 + 2)\n"},
                {
                    "action": "set_plan",
                    "tasks": [{"id": "T1", "description": "Build calculator", "status": "done"}],
                },
                {"action": "set_verification", "commands": [[sys.executable, "-c", verify]]},
                {"action": "finish", "summary": "Calculator implemented and verified."},
            ]
        )
        engine = AutonomousEngine(self.config(), provider)

        state = engine.run()

        self.assertEqual(state["status"], "COMPLETED")
        self.assertEqual(state["step"], 5)
        self.assertEqual(state["usage"]["input_tokens"], 500)
        report_path = os.path.join(self.workspace, "COMPLETION_REPORT.md")
        self.assertTrue(os.path.isfile(report_path))
        with open(report_path, "r", encoding="utf-8") as handle:
            self.assertIn("- Steps: 5", handle.read())
        self.assertTrue(os.path.isfile(os.path.join(self.workspace, ".sudarshan", "events.jsonl")))
        with open(
            os.path.join(self.workspace, "enterprise_state", "JIRA_DAG.json"),
            "r",
            encoding="utf-8",
        ) as handle:
            dag = json.load(handle)
        self.assertEqual(dag["nodes"][0]["id"], "T1")
        self.assertEqual(dag["nodes"][0]["status"], "DONE")
        with open(
            os.path.join(self.workspace, "enterprise_state", "BLACKBOARD_STATUS.json"),
            "r",
            encoding="utf-8",
        ) as handle:
            blackboard = json.load(handle)
        self.assertEqual(blackboard["status"], "COMPLETED")
        self.assertEqual(blackboard["metadata"]["phase"], "completed")
        self.assertFalse(os.path.exists(os.path.join(self.workspace, ".swarm_lock")))


if __name__ == "__main__":
    unittest.main()
