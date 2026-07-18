#!/usr/bin/env python3
"""Turnkey command line interface for the standalone Sudarshan engine."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Dict, Optional, Sequence
from urllib.parse import urlparse

from autonomous_engine import AutonomousEngine, EngineConfig
from estimator import estimate_build, load_project_brief
from providers import (
    AnthropicProvider,
    CommandProvider,
    GeminiProvider,
    OpenAICompatibleProvider,
)
from protocol_assets import load_version, templates_root


ROOT = Path(__file__).resolve().parent


def _write_json_atomic(path: Path, data: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            delete=False,
            dir=str(path.parent),
            prefix=f".{path.name}.",
            suffix=".tmp",
        ) as handle:
            temp_name = handle.name
            json.dump(data, handle, indent=2, ensure_ascii=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if temp_name and os.path.exists(temp_name):
            os.unlink(temp_name)


def _print_json(value: object) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=True))


def _add_input_arguments(parser: argparse.ArgumentParser) -> None:
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--idea", help="Inline project idea or requirements")
    group.add_argument("--prd", help="Path to a product requirements document")
    group.add_argument("--spec", help="Path to a technical specification")


def _load_brief(args: argparse.Namespace):
    return load_project_brief(idea=args.idea, prd_path=args.prd, spec_path=args.spec)


def _estimate_from_args(args: argparse.Namespace):
    return estimate_build(
        _load_brief(args),
        model=args.model,
        input_price_per_million=args.input_price,
        output_price_per_million=args.output_price,
        concurrency=args.concurrency,
    )


def _is_local_endpoint(base_url: str) -> bool:
    return urlparse(base_url).hostname in {"localhost", "127.0.0.1", "::1"}


def _provider_from_args(args: argparse.Namespace, model: str):
    provider_kind = args.provider or "openai-compatible"
    if provider_kind == "command":
        if not args.provider_command_json:
            raise ValueError("command provider requires --provider-command-json")
        try:
            command = json.loads(args.provider_command_json)
        except json.JSONDecodeError as exc:
            raise ValueError(f"provider command must be a JSON argument array: {exc.msg}") from None
        return CommandProvider(
            command=command,
            model=model,
            timeout_seconds=args.provider_timeout,
            cwd=args.provider_command_cwd,
        )
    defaults = {
        "openai-compatible": ("https://api.openai.com/v1", "SUDARSHAN_API_KEY"),
        "anthropic": ("https://api.anthropic.com", "ANTHROPIC_API_KEY"),
        "gemini": ("https://generativelanguage.googleapis.com/v1beta", "GEMINI_API_KEY"),
    }
    default_base_url, default_key_name = defaults[provider_kind]
    base_url = args.base_url or os.environ.get("SUDARSHAN_BASE_URL") or default_base_url
    key_name = args.api_key_env or default_key_name
    api_key = os.environ.get(key_name, "")
    if not api_key and (provider_kind != "openai-compatible" or not _is_local_endpoint(base_url)):
        raise ValueError(f"provider API key is missing; set environment variable {key_name}")
    if provider_kind == "anthropic":
        return AnthropicProvider(
            api_key=api_key,
            base_url=base_url,
            model=model,
            timeout_seconds=args.provider_timeout,
        )
    if provider_kind == "gemini":
        return GeminiProvider(
            api_key=api_key,
            base_url=base_url,
            model=model,
            timeout_seconds=args.provider_timeout,
        )
    return OpenAICompatibleProvider(
        api_key=api_key,
        base_url=base_url,
        model=model,
        timeout_seconds=args.provider_timeout,
    )


def _engine_config_from_args(args: argparse.Namespace, directive: str, model: str) -> EngineConfig:
    max_retries = None if args.max_retries < 0 else args.max_retries
    retry_window = None if args.retry_forever else args.retry_window_seconds
    required_verification = _parse_verification_commands(args.verify_command_json or [])
    return EngineConfig(
        workspace_root=args.workspace,
        directive=directive,
        model=model,
        max_steps=args.max_steps,
        max_cost_usd=args.max_cost,
        max_input_tokens=args.max_input_tokens,
        max_output_tokens=args.max_output_tokens,
        input_price_per_million=args.input_price,
        output_price_per_million=args.output_price,
        retry_initial_seconds=args.retry_initial,
        retry_max_seconds=args.retry_max,
        max_retry_attempts=max_retries,
        max_retry_elapsed_seconds=retry_window,
        command_timeout_seconds=args.command_timeout,
        allow_host_commands=bool(args.allow_host_commands),
        required_verification_commands=required_verification,
    )


def _parse_verification_commands(values: Sequence[str]):
    commands = []
    for raw in values:
        try:
            command = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"verification command must be a JSON argument array: {exc.msg}") from None
        if not isinstance(command, list) or not command or any(
            not isinstance(value, str) or not value for value in command
        ):
            raise ValueError("verification command must be a non-empty JSON argument array")
        commands.append(tuple(command))
    return tuple(commands)


def _add_provider_arguments(parser: argparse.ArgumentParser, *, resume: bool = False) -> None:
    parser.add_argument(
        "--provider",
        choices=("openai-compatible", "anthropic", "gemini", "command"),
        default=None if resume else "openai-compatible",
    )
    parser.add_argument("--base-url", help="Provider API base URL")
    parser.add_argument(
        "--api-key-env",
        default=None,
        help="Environment variable containing the API key (never the key itself)",
    )
    parser.add_argument(
        "--provider-command-json",
        help="JSON argument array for a command/framework provider bridge",
    )
    parser.add_argument("--provider-command-cwd")
    parser.add_argument("--provider-timeout", type=float, default=None if resume else 120.0)


def _add_runtime_arguments(parser: argparse.ArgumentParser, *, resume: bool = False) -> None:
    default = (lambda value: None) if resume else (lambda value: value)
    parser.add_argument("--max-steps", type=int, default=default(200))
    parser.add_argument("--max-cost", type=float)
    parser.add_argument("--max-input-tokens", type=int)
    parser.add_argument("--max-output-tokens", type=int)
    parser.add_argument("--input-price", type=float, default=default(0.0))
    parser.add_argument("--output-price", type=float, default=default(0.0))
    parser.add_argument("--retry-initial", type=float, default=default(5.0))
    parser.add_argument("--retry-max", type=float, default=default(300.0))
    parser.add_argument(
        "--max-retries",
        type=int,
        default=default(-1),
        help="Transient retries before failure; -1 keeps retrying periodically",
    )
    parser.add_argument(
        "--retry-window-seconds",
        type=float,
        default=default(21_600.0),
        help="Maximum elapsed transient-retry window (default: 6 hours)",
    )
    parser.add_argument(
        "--retry-forever",
        action="store_true",
        default=None if resume else False,
        help="Keep retrying transient provider failures until interrupted",
    )
    parser.add_argument(
        "--verify-command-json",
        action="append",
        default=None if resume else [],
        help="Immutable operator verification command as a JSON argument array; repeatable",
    )
    parser.add_argument("--command-timeout", type=float, default=default(300.0))
    parser.add_argument("--max-new-steps", type=int)


def _save_run_config(
    workspace: Path,
    args: argparse.Namespace,
    provider,
    config: EngineConfig,
) -> None:
    if isinstance(provider, CommandProvider):
        provider_config = {
            "kind": "command",
            "command": provider.command,
            "cwd": provider.cwd,
            "timeout_seconds": provider.timeout_seconds,
        }
    else:
        if isinstance(provider, AnthropicProvider):
            kind = "anthropic"
            default_key_name = "ANTHROPIC_API_KEY"
        elif isinstance(provider, GeminiProvider):
            kind = "gemini"
            default_key_name = "GEMINI_API_KEY"
        else:
            kind = "openai-compatible"
            default_key_name = "SUDARSHAN_API_KEY"
        provider_config = {
            "kind": kind,
            "base_url": provider.base_url,
            "api_key_env": args.api_key_env or default_key_name,
            "timeout_seconds": provider.timeout_seconds,
        }
    _write_json_atomic(
        workspace / ".sudarshan" / "run_config.json",
        {
            "schema_version": 1,
            "provider": provider_config,
            "engine": {
                "max_steps": args.max_steps,
                "max_cost": args.max_cost,
                "max_input_tokens": args.max_input_tokens,
                "max_output_tokens": args.max_output_tokens,
                "input_price": args.input_price,
                "output_price": args.output_price,
                "retry_initial": args.retry_initial,
                "retry_max": args.retry_max,
                "max_retries": args.max_retries,
                "retry_window_seconds": args.retry_window_seconds,
                "retry_forever": bool(args.retry_forever),
                "command_timeout": args.command_timeout,
                "allow_host_commands": bool(args.allow_host_commands),
                "required_verification_commands": [
                    list(command) for command in config.required_verification_commands
                ],
            },
        },
    )


def _apply_saved_run_config(args: argparse.Namespace) -> None:
    path = Path(args.workspace).resolve() / ".sudarshan" / "run_config.json"
    saved: Dict[str, object] = {}
    if path.is_file():
        saved = json.loads(path.read_text(encoding="utf-8"))
        if saved.get("schema_version") != 1:
            raise ValueError(f"unsupported run configuration at {path}")
    provider = saved.get("provider") if isinstance(saved.get("provider"), dict) else {}
    engine = saved.get("engine") if isinstance(saved.get("engine"), dict) else {}
    saved_kind = provider.get("kind", "openai-compatible")
    provider_changed = args.provider is not None and args.provider != saved_kind
    key_defaults = {
        "openai-compatible": "SUDARSHAN_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "gemini": "GEMINI_API_KEY",
    }
    provider_defaults = {
        "provider": args.provider if provider_changed else saved_kind,
        "base_url": None if provider_changed else provider.get("base_url"),
        "api_key_env": (
            None
            if provider_changed
            else provider.get("api_key_env", key_defaults.get(saved_kind))
        ),
        "provider_command_json": (
            None
            if provider_changed
            else (
                json.dumps(provider.get("command"))
                if provider.get("command") is not None
                else None
            )
        ),
        "provider_command_cwd": None if provider_changed else provider.get("cwd"),
        "provider_timeout": 120.0 if provider_changed else provider.get("timeout_seconds", 120.0),
    }
    defaults = {
        **provider_defaults,
        "max_steps": engine.get("max_steps", 200),
        "max_cost": engine.get("max_cost"),
        "max_input_tokens": engine.get("max_input_tokens"),
        "max_output_tokens": engine.get("max_output_tokens"),
        "input_price": engine.get("input_price", 0.0),
        "output_price": engine.get("output_price", 0.0),
        "retry_initial": engine.get("retry_initial", 5.0),
        "retry_max": engine.get("retry_max", 300.0),
        "max_retries": engine.get("max_retries", -1),
        "retry_window_seconds": engine.get("retry_window_seconds", 21_600.0),
        "retry_forever": engine.get("retry_forever", False),
        "command_timeout": engine.get("command_timeout", 300.0),
        "allow_host_commands": engine.get("allow_host_commands", False),
        "verify_command_json": [
            json.dumps(command)
            for command in engine.get("required_verification_commands", [])
        ],
    }
    for name, value in defaults.items():
        if getattr(args, name, None) is None:
            setattr(args, name, value)


def cmd_doctor(args: argparse.Namespace) -> int:
    required_files = [
        "autonomous_engine.py",
        "engine_tools.py",
        "estimator.py",
        "providers.py",
        "taskmanager.py",
    ]
    missing = [name for name in required_files if not (ROOT / name).exists()]
    if not Path(templates_root()).is_dir():
        missing.append("templates")
    python_ready = sys.version_info >= (3, 9)
    report = {
        "version": load_version(),
        "ready": python_ready and not missing,
        "requirements": {
            "python": {
                "status": "ready" if python_ready else "unsupported",
                "version": ".".join(str(value) for value in sys.version_info[:3]),
                "minimum": "3.9",
            },
            "core_files": {"status": "ready" if not missing else "missing", "missing": missing},
            "openclaw": False,
        },
        "optional": {
            "git": {"required": False, "available": shutil.which("git") is not None},
            "node": {"required": False, "available": shutil.which("node") is not None},
            "docker": {"required": False, "available": shutil.which("docker") is not None},
            "searxng": {"required": False, "status": "not_checked"},
        },
    }
    if args.json:
        _print_json(report)
    else:
        print(f"Sudarshan {report['version']} doctor: {'READY' if report['ready'] else 'NOT READY'}")
        print("OpenClaw: optional")
        print("Docker, Node, and SearXNG: optional capabilities")
        if missing:
            print("Missing core files: " + ", ".join(missing))
    return 0 if report["ready"] else 1


def cmd_estimate(args: argparse.Namespace) -> int:
    estimate = _estimate_from_args(args)
    if args.output:
        _write_json_atomic(Path(args.output).resolve(), estimate)
    if args.json:
        _print_json(estimate)
    else:
        ranges = estimate["ranges"]
        print(f"Model: {estimate['model']} | Confidence: {estimate['confidence']}")
        print(
            "Tokens (likely): "
            f"{ranges['total_tokens']['likely']:,} "
            f"[{ranges['total_tokens']['low']:,} - {ranges['total_tokens']['high']:,}]"
        )
        print(
            "Elapsed (likely): "
            f"{ranges['elapsed_minutes']['likely']} minutes "
            f"[{ranges['elapsed_minutes']['low']} - {ranges['elapsed_minutes']['high']}]"
        )
        print(
            "Cost (likely): "
            f"${ranges['cost_usd']['likely']:.4f} "
            f"[${ranges['cost_usd']['low']:.4f} - ${ranges['cost_usd']['high']:.4f}]"
        )
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    if args.concurrency != 1:
        raise ValueError(
            "the standalone engine is sequential; use `sudarshan estimate --concurrency` "
            "only for hypothetical multi-worker host planning"
        )
    brief = _load_brief(args)
    estimate = estimate_build(
        brief,
        model=args.model,
        input_price_per_million=args.input_price,
        output_price_per_million=args.output_price,
        concurrency=args.concurrency,
    )
    if args.dry_run:
        report = {"dry_run": True, "workspace": os.path.abspath(args.workspace), "estimate": estimate}
        if args.json:
            _print_json(report)
        else:
            print("Dry run only; no files were written and no model was called.")
            print(f"Likely tokens: {estimate['ranges']['total_tokens']['likely']:,}")
        return 0

    workspace = Path(args.workspace).resolve()
    state_path = workspace / ".sudarshan" / "engine_state.json"
    if state_path.exists():
        raise ValueError(f"workspace already has an engine state; use resume: {state_path}")

    provider = _provider_from_args(args, args.model)
    if not args.allow_host_commands:
        raise ValueError(
            "host commands are not OS-sandboxed; review the risk and pass --allow-host-commands"
        )
    if not args.yes:
        likely = estimate["ranges"]["total_tokens"]["likely"]
        answer = input(f"Estimated {likely:,} tokens. Start build in {workspace}? [y/N] ").strip().lower()
        if answer not in {"y", "yes"}:
            print("Build cancelled.")
            return 0

    config = _engine_config_from_args(args, brief.text, args.model)
    workspace.mkdir(parents=True, exist_ok=True)
    _write_json_atomic(workspace / ".sudarshan" / "estimate.json", estimate)
    _save_run_config(workspace, args, provider, config)
    engine = AutonomousEngine(config, provider)
    state = engine.run(max_new_steps=args.max_new_steps)
    if args.json:
        _print_json(state)
    else:
        print(
            f"Sudarshan {state['status']} at step {state['step']} | "
            f"tokens {state['usage']['input_tokens'] + state['usage']['output_tokens']} | "
            f"cost ${state['usage']['cost_usd']:.6f}"
        )
        if state.get("human_request"):
            print("Human input required: " + state["human_request"]["question"])
    if state["status"] == "BUDGET_EXCEEDED":
        return 3
    return 0 if state["status"] in {"COMPLETED", "RUNNING", "WAITING_HUMAN", "PAUSED"} else 1


def _load_state(workspace: str) -> Dict[str, object]:
    path = Path(workspace).resolve() / ".sudarshan" / "engine_state.json"
    if not path.is_file():
        raise FileNotFoundError(f"no Sudarshan engine state found at {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def cmd_status(args: argparse.Namespace) -> int:
    state = _load_state(args.workspace)
    if args.json:
        _print_json(state)
    else:
        usage = state.get("usage") or {}
        print(f"Status: {state.get('status')} | Step: {state.get('step')}")
        print(
            f"Tokens: {int(usage.get('input_tokens', 0)) + int(usage.get('output_tokens', 0))} "
            f"| Cost: ${float(usage.get('cost_usd', 0)):.6f}"
        )
        if state.get("human_request"):
            print("Waiting for: " + state["human_request"]["question"])
    return 0


def cmd_resume(args: argparse.Namespace) -> int:
    state = _load_state(args.workspace)
    if state.get("status") == "WAITING_HUMAN":
        print("Human input required: " + state["human_request"]["question"])
        return 0
    _apply_saved_run_config(args)
    if not args.allow_host_commands:
        raise ValueError(
            "host commands are not OS-sandboxed; pass --allow-host-commands after reviewing the risk"
        )
    provider = _provider_from_args(args, str(state["model"]))
    config = _engine_config_from_args(args, str(state["directive"]), str(state["model"]))
    engine = AutonomousEngine(config, provider)
    resumed = engine.run(max_new_steps=args.max_new_steps)
    if args.json:
        _print_json(resumed)
    else:
        print(f"Sudarshan {resumed['status']} at step {resumed['step']}")
    if resumed["status"] == "BUDGET_EXCEEDED":
        return 3
    return 0 if resumed["status"] in {"COMPLETED", "RUNNING", "WAITING_HUMAN", "PAUSED"} else 1


class _NoopProvider:
    model = "noop"

    def complete(self, _messages, **_kwargs):
        raise RuntimeError("noop provider cannot perform model calls")


def cmd_input(args: argparse.Namespace) -> int:
    state = _load_state(args.workspace)
    runtime = state.get("limits") or {}
    config = EngineConfig(
        workspace_root=args.workspace,
        directive=str(state["directive"]),
        model=str(state["model"]),
        max_steps=int(runtime.get("max_steps") or 200),
        max_cost_usd=runtime.get("max_cost_usd"),
        max_input_tokens=runtime.get("max_input_tokens"),
        max_output_tokens=runtime.get("max_output_tokens"),
    )
    engine = AutonomousEngine(config, _NoopProvider())
    engine.provide_human_input(args.value)
    print("Human input recorded. Run `sudarshan resume` to continue.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sudarshan",
        description="Provider-neutral autonomous software-build superharness",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {load_version()}")
    commands = parser.add_subparsers(dest="command", required=True)

    doctor = commands.add_parser("doctor", help="Check the minimal standalone runtime")
    doctor.add_argument("--json", action="store_true")
    doctor.set_defaults(handler=cmd_doctor)

    estimate = commands.add_parser("estimate", help="Estimate tokens, cost, and elapsed time")
    _add_input_arguments(estimate)
    estimate.add_argument("--model", default="unspecified")
    estimate.add_argument("--input-price", type=float, default=0.0)
    estimate.add_argument("--output-price", type=float, default=0.0)
    estimate.add_argument("--concurrency", type=int, default=1)
    estimate.add_argument("--output")
    estimate.add_argument("--json", action="store_true")
    estimate.set_defaults(handler=cmd_estimate)

    build = commands.add_parser("build", help="Estimate and launch a new build")
    _add_input_arguments(build)
    build.add_argument("--workspace", required=True)
    build.add_argument("--model", required=True)
    build.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help="Standalone execution concurrency (currently fixed at 1)",
    )
    build.add_argument("--yes", action="store_true", help="Start without an interactive confirmation")
    build.add_argument(
        "--allow-host-commands",
        action="store_true",
        help="Acknowledge that model-requested commands run with your user privileges",
    )
    build.add_argument("--dry-run", action="store_true")
    build.add_argument("--json", action="store_true")
    _add_provider_arguments(build)
    _add_runtime_arguments(build)
    build.set_defaults(handler=cmd_build)

    resume = commands.add_parser("resume", help="Continue a durable build")
    resume.add_argument("--workspace", required=True)
    resume.add_argument("--allow-host-commands", action="store_true", default=None)
    resume.add_argument("--json", action="store_true")
    _add_provider_arguments(resume, resume=True)
    _add_runtime_arguments(resume, resume=True)
    resume.set_defaults(handler=cmd_resume)

    status = commands.add_parser("status", help="Inspect durable build state")
    status.add_argument("--workspace", required=True)
    status.add_argument("--json", action="store_true")
    status.set_defaults(handler=cmd_status)

    human_input = commands.add_parser("input", help="Answer a paused human request")
    human_input.add_argument("--workspace", required=True)
    human_input.add_argument("--value", required=True)
    human_input.set_defaults(handler=cmd_input)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
