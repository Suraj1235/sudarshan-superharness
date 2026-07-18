#!/usr/bin/env python3
"""Durable standalone execution loop for Sudarshan software builds."""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, Iterator, List, Optional, Sequence

from engine_tools import ToolPolicyError, WorkspaceTools
from protocol_runtime import ProtocolStateBridge
from providers import ModelResponse, Provider, ProviderError
from quality_gate import detect_verification_commands
from safe_edit import LockRefresher, acquire_lock, release_lock


ENGINE_SCHEMA_VERSION = 1
TERMINAL_STATUSES = {"COMPLETED", "FAILED", "BUDGET_EXCEEDED", "MAX_STEPS"}
SUPPORTED_ACTIONS = {
    "delete_file",
    "edit_file",
    "finish",
    "list_files",
    "read_file",
    "request_human",
    "run_command",
    "set_plan",
    "set_verification",
    "write_file",
}


SYSTEM_PROMPT = """You are the execution model inside Sudarshan, a deterministic software-build harness.
Build the requested software in the provided workspace. Work incrementally, inspect before changing,
keep a concrete plan, write tests, run real verification, and repair failures before finishing.

Return exactly one JSON object per turn. No prose and no Markdown fences. Allowed actions:
{"action":"list_files","path":"."}
{"action":"read_file","path":"relative/path","max_chars":12000}
{"action":"write_file","path":"relative/path","content":"complete file content"}
{"action":"edit_file","path":"relative/path","old_text":"exact existing text","new_text":"replacement","expected_replacements":1}
{"action":"delete_file","path":"relative/path"}
{"action":"run_command","argv":["python","-m","pytest","-q"],"cwd":".","timeout_seconds":120}
{"action":"set_plan","tasks":[{"id":"T1","description":"...","status":"pending|in_progress|done|blocked","depends_on":[]}]}
{"action":"set_verification","commands":[["python","-m","pytest","-q"]]}
{"action":"request_human","question":"one concrete blocker question"}
{"action":"finish","summary":"what was built and verified"}

Rules:
- Set a plan before modifying files or running commands.
- Derive plan items from every material requirement and preserve them; never delete or rewrite
  committed tasks to make the plan appear complete. Dependencies must finish first.
- Inspect existing files and conventions before choosing architecture or dependencies.
- Prefer the smallest complete design that satisfies the brief; avoid placeholder implementations,
  fake integrations, silent exception handling, hardcoded credentials, and unjustified TODOs.
- Treat user input, network data, file paths, and subprocess output as untrusted. Add validation,
  least-privilege defaults, clear errors, and secret-safe configuration where applicable.
- Add tests for acceptance criteria, edge cases, and meaningful failure paths. For applications,
  include the setup/run documentation and deployment or environment configuration users need.
- Run the strongest available lint, type, test, build, and integration checks. A prior successful
  command is stale after relevant code changes; rerun verification before finish.
- Use argument arrays; shell strings are invalid.
- Never claim success from inspection alone. Run the declared verification commands.
- Keep all paths relative to the workspace.
- Mark every plan item done before finish.
- If a tool fails, analyze the observation and repair the cause.
"""


class ActionValidationError(ValueError):
    pass


class EngineBusyError(RuntimeError):
    """Raised when another process owns the workspace execution lease."""

    pass


@dataclass(frozen=True)
class EngineConfig:
    workspace_root: str
    directive: str
    model: str
    max_steps: int = 200
    max_cost_usd: Optional[float] = None
    max_input_tokens: Optional[int] = None
    max_output_tokens: Optional[int] = None
    input_price_per_million: float = 0.0
    output_price_per_million: float = 0.0
    retry_initial_seconds: float = 5.0
    retry_max_seconds: float = 300.0
    max_retry_attempts: Optional[int] = None
    max_retry_elapsed_seconds: Optional[float] = 21_600.0
    command_timeout_seconds: float = 300.0
    recent_event_limit: int = 16
    max_observation_chars: int = 12_000
    allow_host_commands: bool = False
    required_verification_commands: Sequence[Sequence[str]] = ()
    auto_verification: bool = True
    run_lock_timeout_seconds: float = 0.25

    def __post_init__(self) -> None:
        if not self.directive or not self.directive.strip():
            raise ValueError("directive is required")
        if not self.model or not self.model.strip():
            raise ValueError("model is required")
        if isinstance(self.max_steps, bool) or not isinstance(self.max_steps, int) or self.max_steps < 1:
            raise ValueError("max_steps must be positive")
        if not all(
            math.isfinite(float(value)) and value >= 0
            for value in (self.input_price_per_million, self.output_price_per_million)
        ):
            raise ValueError("pricing must be non-negative")
        if self.max_cost_usd is not None and (
            not math.isfinite(float(self.max_cost_usd)) or self.max_cost_usd < 0
        ):
            raise ValueError("max_cost_usd must be non-negative")
        if any(
            not math.isfinite(float(value)) or value < 0
            for value in (self.retry_initial_seconds, self.retry_max_seconds)
        ):
            raise ValueError("retry delays must be non-negative")
        if self.retry_max_seconds < self.retry_initial_seconds:
            raise ValueError("retry_max_seconds must be at least retry_initial_seconds")
        if self.max_retry_attempts is not None and self.max_retry_attempts < 0:
            raise ValueError("max_retry_attempts must be non-negative or None")
        if self.max_retry_elapsed_seconds is not None and (
            not math.isfinite(float(self.max_retry_elapsed_seconds))
            or self.max_retry_elapsed_seconds <= 0
        ):
            raise ValueError("max_retry_elapsed_seconds must be positive or None")
        for token_limit in (self.max_input_tokens, self.max_output_tokens):
            if token_limit is not None and (
                isinstance(token_limit, bool)
                or not isinstance(token_limit, int)
                or token_limit < 0
            ):
                raise ValueError("token ceilings must be non-negative integers or None")
        if not math.isfinite(float(self.command_timeout_seconds)) or self.command_timeout_seconds <= 0:
            raise ValueError("command timeout must be positive and finite")
        if (
            isinstance(self.recent_event_limit, bool)
            or not isinstance(self.recent_event_limit, int)
            or self.recent_event_limit < 1
        ):
            raise ValueError("recent_event_limit must be a positive integer")
        if (
            isinstance(self.max_observation_chars, bool)
            or not isinstance(self.max_observation_chars, int)
            or self.max_observation_chars < 1
        ):
            raise ValueError("max_observation_chars must be a positive integer")
        if (
            not math.isfinite(float(self.run_lock_timeout_seconds))
            or self.run_lock_timeout_seconds < 0
        ):
            raise ValueError("run_lock_timeout_seconds must be non-negative")
        for command in self.required_verification_commands:
            if not command or any(not isinstance(value, str) or not value for value in command):
                raise ValueError("required verification commands must be argument arrays")
        object.__setattr__(self, "workspace_root", os.path.abspath(self.workspace_root))


def _decode_json_object(raw: str) -> Dict[str, object]:
    if not isinstance(raw, str) or not raw.strip():
        raise ActionValidationError("model response is empty")
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3 and lines[-1].strip() == "```":
            text = "\n".join(lines[1:-1]).strip()
    start = text.find("{")
    if start < 0:
        raise ActionValidationError("model response must contain one JSON object")
    def reject_constant(value: str) -> None:
        raise ActionValidationError(f"non-finite JSON number is not allowed: {value}")

    decoder = json.JSONDecoder(parse_constant=reject_constant)
    try:
        value, end = decoder.raw_decode(text[start:])
    except json.JSONDecodeError as exc:
        raise ActionValidationError(f"invalid JSON action: {exc.msg}") from None
    if text[start + end :].strip():
        raise ActionValidationError("model response must contain only one JSON object")
    if not isinstance(value, dict):
        raise ActionValidationError("action must be a JSON object")

    def require_finite(item: object) -> None:
        if isinstance(item, float) and not math.isfinite(item):
            raise ActionValidationError("non-finite JSON numbers are not allowed")
        if isinstance(item, dict):
            for nested in item.values():
                require_finite(nested)
        elif isinstance(item, list):
            for nested in item:
                require_finite(nested)

    require_finite(value)
    return value


def parse_action(raw: str) -> Dict[str, object]:
    action = _decode_json_object(raw)
    name = action.get("action")
    if not isinstance(name, str) or name not in SUPPORTED_ACTIONS:
        raise ActionValidationError(f"unsupported action: {name!r}")
    if name in {"read_file", "write_file", "edit_file", "delete_file"}:
        if not isinstance(action.get("path"), str):
            raise ActionValidationError(f"{name} requires a path string")
    if name == "write_file" and not isinstance(action.get("content"), str):
        raise ActionValidationError("write_file requires text content")
    if name == "edit_file":
        if not isinstance(action.get("old_text"), str) or not isinstance(
            action.get("new_text"), str
        ):
            raise ActionValidationError("edit_file requires old_text and new_text strings")
        expected = action.get("expected_replacements", 1)
        if not isinstance(expected, int) or expected < 1:
            raise ActionValidationError("edit_file expected_replacements must be positive")
    if name == "run_command":
        argv = action.get("argv")
        if not isinstance(argv, list) or not argv or any(not isinstance(v, str) for v in argv):
            raise ActionValidationError("run_command requires a non-empty argument array")
        if "cwd" in action and not isinstance(action["cwd"], str):
            raise ActionValidationError("run_command cwd must be a string")
        if "timeout_seconds" in action:
            timeout = action["timeout_seconds"]
            if (
                isinstance(timeout, bool)
                or not isinstance(timeout, (int, float))
                or not math.isfinite(float(timeout))
                or timeout <= 0
            ):
                raise ActionValidationError("run_command timeout_seconds must be positive and finite")
    if name == "set_plan" and not isinstance(action.get("tasks"), list):
        raise ActionValidationError("set_plan requires a tasks array")
    if name == "set_verification" and not isinstance(action.get("commands"), list):
        raise ActionValidationError("set_verification requires a commands array")
    if name == "request_human" and not isinstance(action.get("question"), str):
        raise ActionValidationError("request_human requires a question string")
    if name == "finish" and not isinstance(action.get("summary"), str):
        raise ActionValidationError("finish requires a summary string")
    return action


class _StateStore:
    def __init__(self, workspace_root: str) -> None:
        self.root = Path(workspace_root).resolve() / ".sudarshan"
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_path = self.root / "engine_state.json"
        self.events_path = self.root / "events.jsonl"

    def load(self) -> Optional[Dict[str, object]]:
        if not self.state_path.is_file():
            return None
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    def save(self, state: Dict[str, object]) -> None:
        temp_name = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                delete=False,
                dir=str(self.root),
                prefix=".engine_state.",
                suffix=".tmp",
            ) as handle:
                temp_name = handle.name
                json.dump(state, handle, indent=2, ensure_ascii=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, self.state_path)
        finally:
            if temp_name and os.path.exists(temp_name):
                os.unlink(temp_name)

    def append_event(self, event: Dict[str, object]) -> None:
        with self.events_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(event, ensure_ascii=True, separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())


class AutonomousEngine:
    def __init__(
        self,
        config: EngineConfig,
        provider: Provider,
        *,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.config = config
        self.provider = provider
        self.sleep = sleep
        self.clock = clock
        self.tools = WorkspaceTools(config.workspace_root)
        self.protocol = ProtocolStateBridge(config.workspace_root)
        self.store = _StateStore(config.workspace_root)
        loaded = self.store.load()
        if loaded is None:
            self.state = self._initial_state()
            self._save()
        else:
            self._validate_loaded_state(loaded)
            loaded.setdefault(
                "required_verification_commands",
                [list(command) for command in config.required_verification_commands],
            )
            self.state = loaded

    def _timestamp(self) -> str:
        return datetime.fromtimestamp(self.clock(), tz=timezone.utc).isoformat()

    def _initial_state(self) -> Dict[str, object]:
        directive = self.config.directive.strip()
        return {
            "schema_version": ENGINE_SCHEMA_VERSION,
            "engine_id": f"engine_{uuid.uuid4().hex[:16]}",
            "created_at": self._timestamp(),
            "updated_at": self._timestamp(),
            "status": "READY",
            "directive": directive,
            "directive_sha256": hashlib.sha256(directive.encode("utf-8")).hexdigest(),
            "model": self.config.model,
            "step": 0,
            "event_count": 0,
            "plan": [],
            "verification_commands": [],
            "required_verification_commands": [
                list(command) for command in self.config.required_verification_commands
            ],
            "usage": {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0},
            "retry": {
                "consecutive_retries": 0,
                "total_retries": 0,
                "next_retry_at": None,
                "first_retry_at": None,
                "last_error": None,
            },
            "human_request": None,
            "completion": None,
            "last_error": None,
            "recent_events": [],
            "limits": {
                "max_steps": self.config.max_steps,
                "max_cost_usd": self.config.max_cost_usd,
                "max_input_tokens": self.config.max_input_tokens,
                "max_output_tokens": self.config.max_output_tokens,
            },
        }

    def _validate_loaded_state(self, state: Dict[str, object]) -> None:
        if state.get("schema_version") != ENGINE_SCHEMA_VERSION:
            raise ValueError("unsupported engine state schema")
        directive_hash = hashlib.sha256(self.config.directive.strip().encode("utf-8")).hexdigest()
        if state.get("directive_sha256") != directive_hash:
            raise ValueError("existing engine state belongs to a different directive")
        if state.get("model") != self.config.model:
            raise ValueError("existing engine state belongs to a different model")

    def _save(self) -> None:
        self.state["updated_at"] = self._timestamp()
        self.store.save(self.state)
        self.protocol.sync(self.state)

    def _bounded_action_for_event(self, action: Optional[Dict[str, object]]) -> object:
        if action is None:
            return None
        result = dict(action)
        content = result.get("content")
        if isinstance(content, str) and len(content) > 2000:
            result["content"] = content[:2000]
            result["content_truncated"] = True
            result["content_sha256"] = hashlib.sha256(content.encode("utf-8")).hexdigest()
        return result

    def _record_event(
        self,
        kind: str,
        *,
        action: Optional[Dict[str, object]] = None,
        observation: Optional[Dict[str, object]] = None,
    ) -> None:
        event_count = int(self.state.get("event_count", 0)) + 1
        event = {
            "event_id": event_count,
            "timestamp": self._timestamp(),
            "step": self.state.get("step", 0),
            "kind": kind,
            "action": self._bounded_action_for_event(action),
            "observation": observation or {},
        }
        self.state["event_count"] = event_count
        recent = list(self.state.get("recent_events") or [])
        recent.append(event)
        self.state["recent_events"] = recent[-self.config.recent_event_limit :]
        self.store.append_event(event)

    def _messages(self) -> List[Dict[str, str]]:
        snapshot = {
            "directive": self.state["directive"],
            "step": self.state["step"],
            "max_steps": self.config.max_steps,
            "plan": self.state["plan"],
            "verification_commands": self.state["verification_commands"],
            "usage": self.state["usage"],
            "workspace": self.tools.list_files(max_entries=300),
            "recent_events": self.state["recent_events"],
        }
        return [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": "CURRENT DURABLE BUILD STATE\n" + json.dumps(snapshot, ensure_ascii=True),
            },
        ]

    def _budget_reason(self) -> Optional[str]:
        usage = self.state["usage"]
        if self.config.max_cost_usd is not None and usage["cost_usd"] >= self.config.max_cost_usd:
            return f"cost ceiling reached: ${usage['cost_usd']:.6f} >= ${self.config.max_cost_usd:.6f}"
        if (
            self.config.max_input_tokens is not None
            and usage["input_tokens"] >= self.config.max_input_tokens
        ):
            return "input token ceiling reached"
        if (
            self.config.max_output_tokens is not None
            and usage["output_tokens"] >= self.config.max_output_tokens
        ):
            return "output token ceiling reached"
        return None

    def _record_usage(self, response: ModelResponse, messages: List[Dict[str, str]]) -> None:
        input_tokens = response.input_tokens
        output_tokens = response.output_tokens
        if input_tokens <= 0:
            input_tokens = math.ceil(sum(len(item.get("content", "")) for item in messages) / 4)
        if output_tokens <= 0:
            output_tokens = math.ceil(len(response.text) / 4)
        usage = self.state["usage"]
        usage["input_tokens"] += int(input_tokens)
        usage["output_tokens"] += int(output_tokens)
        added_cost = (
            input_tokens * self.config.input_price_per_million
            + output_tokens * self.config.output_price_per_million
        ) / 1_000_000
        usage["cost_usd"] = round(float(usage["cost_usd"]) + added_cost, 6)

    def _wait_for_scheduled_retry(self) -> None:
        if self.state.get("status") != "WAITING_RETRY":
            return
        next_retry_at = self.state.get("retry", {}).get("next_retry_at")
        if next_retry_at is not None:
            remaining = max(0.0, float(next_retry_at) - self.clock())
            if remaining:
                self.sleep(remaining)
        self.state["status"] = "RUNNING"
        self.state["retry"]["next_retry_at"] = None
        self._save()

    def _complete_with_retry(self, messages: List[Dict[str, str]]) -> ModelResponse:
        while True:
            try:
                response = self.provider.complete(messages, temperature=0.1)
                self.state["retry"]["consecutive_retries"] = 0
                self.state["retry"]["next_retry_at"] = None
                self.state["retry"]["first_retry_at"] = None
                self.state["retry"]["last_error"] = None
                return response
            except ProviderError as exc:
                if not exc.retryable:
                    raise
                retry = self.state["retry"]
                retry.setdefault("first_retry_at", None)
                if retry["first_retry_at"] is None:
                    retry["first_retry_at"] = self.clock()
                retry["consecutive_retries"] += 1
                retry["total_retries"] += 1
                retry["last_error"] = str(exc)[:1000]
                consecutive = int(retry["consecutive_retries"])
                if (
                    self.config.max_retry_attempts is not None
                    and consecutive > self.config.max_retry_attempts
                ):
                    raise ProviderError(
                        f"retry limit exceeded after {self.config.max_retry_attempts} retries",
                        status_code=exc.status_code,
                        retryable=False,
                    ) from None
                exponential = self.config.retry_initial_seconds * (2 ** max(0, consecutive - 1))
                wait_seconds = min(self.config.retry_max_seconds, exponential)
                if exc.retry_after_seconds is not None:
                    wait_seconds = max(wait_seconds, float(exc.retry_after_seconds))
                if self.config.max_retry_elapsed_seconds is not None:
                    elapsed = self.clock() - float(retry["first_retry_at"])
                    if elapsed + wait_seconds > self.config.max_retry_elapsed_seconds:
                        raise ProviderError(
                            "retry elapsed-time limit exceeded",
                            status_code=exc.status_code,
                            retryable=False,
                        ) from None
                retry["next_retry_at"] = self.clock() + wait_seconds
                self.state["status"] = "WAITING_RETRY"
                self._record_event(
                    "provider_retry",
                    observation={
                        "ok": False,
                        "status_code": exc.status_code,
                        "error": str(exc)[:1000],
                        "wait_seconds": wait_seconds,
                        "attempt": consecutive,
                    },
                )
                self._save()
                self.sleep(wait_seconds)
                self.state["status"] = "RUNNING"
                retry["next_retry_at"] = None
                self._save()

    @staticmethod
    def _validate_plan(tasks: object) -> List[Dict[str, object]]:
        if not isinstance(tasks, list) or not tasks:
            raise ActionValidationError("plan must contain at least one task")
        normalized: List[Dict[str, object]] = []
        ids = set()
        for task in tasks:
            if not isinstance(task, dict):
                raise ActionValidationError("each plan task must be an object")
            task_id = task.get("id")
            description = task.get("description")
            status = task.get("status")
            depends_on = task.get("depends_on", [])
            if not isinstance(task_id, str) or not task_id.strip():
                raise ActionValidationError("each task requires a non-empty id")
            if task_id in ids:
                raise ActionValidationError(f"duplicate task id: {task_id}")
            if not isinstance(description, str) or not description.strip():
                raise ActionValidationError(f"task {task_id} requires a description")
            if status not in {"pending", "in_progress", "done", "blocked"}:
                raise ActionValidationError(f"task {task_id} has invalid status")
            if not isinstance(depends_on, list) or any(not isinstance(v, str) for v in depends_on):
                raise ActionValidationError(f"task {task_id} has invalid dependencies")
            ids.add(task_id)
            normalized.append(
                {
                    "id": task_id,
                    "description": description.strip(),
                    "status": status,
                    "depends_on": list(depends_on),
                }
            )
        for task in normalized:
            missing = [dep for dep in task["depends_on"] if dep not in ids]
            if missing:
                raise ActionValidationError(f"task {task['id']} has missing dependencies: {missing}")
        graph = {task["id"]: task["depends_on"] for task in normalized}
        visiting, visited = set(), set()

        def visit(task_id: str) -> None:
            if task_id in visiting:
                raise ActionValidationError("plan contains a dependency cycle")
            if task_id in visited:
                return
            visiting.add(task_id)
            for dependency in graph[task_id]:
                visit(dependency)
            visiting.remove(task_id)
            visited.add(task_id)

        for task_id in graph:
            visit(task_id)
        statuses = {task["id"]: task["status"] for task in normalized}
        for task in normalized:
            if task["status"] not in {"in_progress", "done"}:
                continue
            unfinished = [
                dependency
                for dependency in task["depends_on"]
                if statuses[dependency] != "done"
            ]
            if unfinished:
                raise ActionValidationError(
                    f"task {task['id']} has unfinished dependencies: {unfinished}"
                )
        return normalized

    def _validate_plan_update(self, plan: List[Dict[str, object]]) -> None:
        existing = {
            task["id"]: task for task in (self.state.get("plan") or [])
        }
        if not existing:
            return
        proposed = {task["id"]: task for task in plan}
        removed = [task_id for task_id in existing if task_id not in proposed]
        if removed:
            raise ActionValidationError(
                f"plan update cannot remove committed tasks: {removed}"
            )
        for task_id, old_task in existing.items():
            new_task = proposed[task_id]
            if new_task["description"] != old_task["description"]:
                raise ActionValidationError(
                    f"plan update cannot rewrite task {task_id} description"
                )
            if new_task["depends_on"] != old_task["depends_on"]:
                raise ActionValidationError(
                    f"plan update cannot rewrite task {task_id} dependencies"
                )
            if old_task["status"] == "done" and new_task["status"] != "done":
                raise ActionValidationError(
                    f"completed task {task_id} cannot return to {new_task['status']}"
                )

    def _require_plan(self) -> None:
        if not self.state.get("plan"):
            raise ActionValidationError("set_plan is required before mutating the workspace")

    def _dispatch(self, action: Dict[str, object]) -> Dict[str, object]:
        name = action["action"]
        if name == "list_files":
            return {"ok": True, "result": self.tools.list_files(str(action.get("path", ".")))}
        if name == "read_file":
            requested = int(action.get("max_chars", self.config.max_observation_chars))
            limit = min(max(1, requested), self.config.max_observation_chars)
            return {"ok": True, "result": self.tools.read_file(str(action["path"]), max_chars=limit)}
        if name == "set_plan":
            plan = self._validate_plan(action["tasks"])
            self._validate_plan_update(plan)
            self.state["plan"] = plan
            return {"ok": True, "result": {"tasks": len(plan)}}
        if name == "request_human":
            question = str(action["question"]).strip()
            if not question:
                raise ActionValidationError("human question must not be empty")
            self.state["human_request"] = {"question": question, "requested_at": self._timestamp()}
            self.state["status"] = "WAITING_HUMAN"
            return {"ok": True, "result": {"paused": True, "question": question}}

        self._require_plan()
        if name == "write_file":
            return {
                "ok": True,
                "result": self.tools.write_file(str(action["path"]), str(action["content"])),
            }
        if name == "edit_file":
            return {
                "ok": True,
                "result": self.tools.edit_file(
                    str(action["path"]),
                    old_text=str(action["old_text"]),
                    new_text=str(action["new_text"]),
                    expected_replacements=int(action.get("expected_replacements", 1)),
                ),
            }
        if name == "delete_file":
            return {"ok": True, "result": self.tools.delete_file(str(action["path"]))}
        if name == "run_command":
            if not self.config.allow_host_commands:
                raise ActionValidationError("host command authorization is required")
            timeout = min(
                float(action.get("timeout_seconds", self.config.command_timeout_seconds)),
                self.config.command_timeout_seconds,
            )
            result = self.tools.run_command(
                action["argv"],
                cwd=str(action.get("cwd", ".")),
                timeout_seconds=timeout,
                max_output_chars=self.config.max_observation_chars,
            )
            return {"ok": result["returncode"] == 0 and not result["timed_out"], "result": result}
        if name == "set_verification":
            commands = action["commands"]
            if not commands:
                raise ActionValidationError("at least one verification command is required")
            normalized: List[List[str]] = []
            for command in commands:
                if not isinstance(command, list) or not command or any(
                    not isinstance(value, str) for value in command
                ):
                    raise ActionValidationError("each verification command must be an argument array")
                normalized.append(self.tools._validate_command(command))
            self.state["verification_commands"] = normalized
            return {"ok": True, "result": {"commands": len(normalized)}}
        if name == "finish":
            if not self.config.allow_host_commands:
                raise ActionValidationError("host command authorization is required for verification")
            incomplete = [task["id"] for task in self.state["plan"] if task["status"] != "done"]
            if incomplete:
                raise ActionValidationError(f"plan is incomplete: {incomplete}")
            required_commands = list(self.state.get("required_verification_commands") or [])
            automatic_commands = (
                detect_verification_commands(self.config.workspace_root)
                if self.config.auto_verification
                else []
            )
            model_commands = list(self.state.get("verification_commands") or [])
            commands = []
            seen_commands = set()
            for command in required_commands + automatic_commands + model_commands:
                key = tuple(command)
                if key not in seen_commands:
                    commands.append(command)
                    seen_commands.add(key)
            if not commands:
                raise ActionValidationError("verification commands are required before finish")
            verification_results = []
            for command in commands:
                result = self.tools.run_command(
                    command,
                    timeout_seconds=self.config.command_timeout_seconds,
                    max_output_chars=self.config.max_observation_chars,
                )
                verification_results.append(result)
                if result["timed_out"] or result["returncode"] != 0:
                    return {
                        "ok": False,
                        "error": "verification failed; repair the project before finishing",
                        "result": result,
                    }
            summary = str(action["summary"]).strip()
            if not summary:
                raise ActionValidationError("finish summary must not be empty")
            report_lines = [
                "# Sudarshan Completion Report",
                "",
                summary,
                "",
                f"- Model: {self.config.model}",
                f"- Steps: {int(self.state['step'])}",
                f"- Input tokens: {self.state['usage']['input_tokens']}",
                f"- Output tokens: {self.state['usage']['output_tokens']}",
                f"- Recorded cost (USD): {self.state['usage']['cost_usd']:.6f}",
                "",
                "## Verification",
                "",
            ]
            for result in verification_results:
                report_lines.append(
                    f"- PASS: `{json.dumps(result['argv'], ensure_ascii=True)}` "
                    f"({result['duration_seconds']}s)"
                )
            report_lines.append("")
            self.tools.write_file("COMPLETION_REPORT.md", "\n".join(report_lines))
            self.state["completion"] = {
                "completed_at": self._timestamp(),
                "summary": summary,
                "verification": verification_results,
            }
            self.state["status"] = "COMPLETED"
            return {"ok": True, "result": {"completed": True, "report": "COMPLETION_REPORT.md"}}
        raise ActionValidationError(f"unsupported action: {name}")

    def _execute_step(self) -> None:
        preexisting_budget_reason = self._budget_reason()
        if preexisting_budget_reason:
            self.state["status"] = "BUDGET_EXCEEDED"
            self.state["last_error"] = preexisting_budget_reason
            self._record_event("budget_stop", observation={"ok": False, "error": preexisting_budget_reason})
            self._save()
            return

        messages = self._messages()
        response = self._complete_with_retry(messages)
        self._record_usage(response, messages)
        self.state["step"] = int(self.state["step"]) + 1
        budget_reason = self._budget_reason()
        if budget_reason:
            self.state["status"] = "BUDGET_EXCEEDED"
            self.state["last_error"] = budget_reason
            self._record_event("budget_stop", observation={"ok": False, "error": budget_reason})
            self._save()
            return

        action = None
        try:
            action = parse_action(response.text)
            observation = self._dispatch(action)
        except (ActionValidationError, ToolPolicyError, ValueError, OSError) as exc:
            observation = {"ok": False, "error": str(exc)[:2000]}
        self._record_event("model_action", action=action, observation=observation)
        self._save()

    def _run_owned(self, *, max_new_steps: Optional[int] = None) -> Dict[str, object]:
        if self.state.get("status") in TERMINAL_STATUSES:
            return self.state
        if self.state.get("status") == "WAITING_HUMAN":
            return self.state
        self._wait_for_scheduled_retry()
        if self.state.get("status") in {"READY", "PAUSED"}:
            self.state["status"] = "RUNNING"
            self._save()
        starting_step = int(self.state["step"])
        try:
            while self.state.get("status") == "RUNNING":
                if max_new_steps is not None and int(self.state["step"]) - starting_step >= max_new_steps:
                    break
                if int(self.state["step"]) >= self.config.max_steps:
                    self.state["status"] = "MAX_STEPS"
                    self.state["last_error"] = f"maximum step count reached: {self.config.max_steps}"
                    self._record_event(
                        "max_steps",
                        observation={"ok": False, "error": self.state["last_error"]},
                    )
                    self._save()
                    break
                self._execute_step()
        except ProviderError as exc:
            self.state["status"] = "FAILED"
            self.state["last_error"] = str(exc)[:1000]
            self._record_event(
                "provider_failure",
                observation={
                    "ok": False,
                    "error": str(exc)[:1000],
                    "status_code": exc.status_code,
                },
            )
            self._save()
        except KeyboardInterrupt:
            self.state["status"] = "PAUSED"
            self._record_event("paused", observation={"ok": True, "reason": "keyboard interrupt"})
            self._save()
        return self.state

    @contextmanager
    def _workspace_lease(self) -> Iterator[None]:
        """Reload and exclusively own canonical state for one mutation window."""
        lock_target = str(self.store.root / "engine_run")
        worker_id = f"{self.state.get('engine_id', 'engine')}-{uuid.uuid4().hex}"
        lease_ttl = max(300, int(self.config.command_timeout_seconds) + 60)
        try:
            lock_id = acquire_lock(
                lock_target,
                worker_id,
                timeout_sec=lease_ttl,
                acquire_timeout_sec=self.config.run_lock_timeout_seconds,
            )
        except TimeoutError as exc:
            raise EngineBusyError(
                "another Sudarshan process is already running this workspace"
            ) from exc

        refresher = LockRefresher(
            f"{lock_target}.lock",
            worker_id,
            lock_id,
            lease_ttl,
        )
        refresher.start()
        try:
            current = self.store.load()
            if current is not None:
                self._validate_loaded_state(current)
                current.setdefault(
                    "required_verification_commands",
                    [list(command) for command in self.config.required_verification_commands],
                )
                self.state = current
            yield
        finally:
            refresher.stop()
            refresher.join(timeout=2)
            release_lock(lock_target, worker_id, lock_id)

    def run(self, *, max_new_steps: Optional[int] = None) -> Dict[str, object]:
        """Run while holding the single-writer lease for this workspace."""
        with self._workspace_lease():
            return self._run_owned(max_new_steps=max_new_steps)

    def provide_human_input(self, value: str) -> None:
        with self._workspace_lease():
            if self.state.get("status") != "WAITING_HUMAN":
                raise ValueError("engine is not waiting for human input")
            answer = value.strip()
            if not answer:
                raise ValueError("human input must not be empty")
            question = self.state.get("human_request") or {}
            self.state["human_request"] = None
            self.state["status"] = "RUNNING"
            self._record_event(
                "human_input",
                observation={
                    "ok": True,
                    "question": question.get("question"),
                    "input": answer,
                },
            )
            self._save()


__all__ = [
    "ActionValidationError",
    "AutonomousEngine",
    "ENGINE_SCHEMA_VERSION",
    "EngineBusyError",
    "EngineConfig",
    "SYSTEM_PROMPT",
    "parse_action",
]
