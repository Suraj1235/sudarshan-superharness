# Standalone Engine Design

## Objective

Turn Sudarshan from a host contract plus deterministic toolkit into a self-contained execution engine. A new user provides an idea, PRD, or technical specification and an API configuration; Sudarshan estimates token use, cost, and elapsed time before launch, then drives a model through a durable, workspace-confined build loop without requiring OpenClaw. Host commands are never described as sandboxed: they run only with explicit operator consent and should be isolated with a VM or container when the build is untrusted.

## Chosen Architecture

The engine uses a provider-neutral JSON action protocol rather than vendor-specific tool calling. Each model turn returns one action: inspect files, write a file, run a command, update the plan, request human input, or finish. Sudarshan validates and executes the action, persists the result, and sends the observation into the next turn.

This preserves the existing product thesis: models reason, while deterministic code owns state, tools, budgets, retries, and completion gates. OpenClaw and other agent frameworks remain optional host adapters.

## User Journey

1. `sudarshan estimate` accepts `--idea`, `--prd`, or `--spec` and emits a versioned estimate with assumptions and ranges.
2. `sudarshan build` validates provider configuration, shows or writes the estimate, bootstraps existing Sudarshan state, and starts the engine.
3. The engine creates a build plan, executes one validated action at a time, records token/cost usage, and checkpoints after every turn.
4. Transient API failures and rate limits are retried with `Retry-After` support and capped exponential backoff. The user can select bounded or indefinite retry.
5. `sudarshan resume` reconstructs the conversation from durable state and continues.
6. A build can finish only after declared verification commands pass and a completion report is written.

## Components

- `estimator.py`: deterministic, explainable range estimates from scope signals and model pricing.
- `providers.py`: stdlib HTTP providers, normalized responses/errors, and a pluggable provider protocol.
- `engine_tools.py`: workspace-confined file and subprocess tools with atomic writes and timeouts.
- `autonomous_engine.py`: action validation, durable event/state storage, retry policy, budget enforcement, and completion checks.
- `sudarshan_cli.py`: `doctor`, `estimate`, `build`, `resume`, and `status` commands.
- `pyproject.toml`: zero-dependency package and `sudarshan` console entry point.

## Provider Strategy

The first release supports OpenAI-compatible chat-completion APIs, Anthropic Messages, Gemini `generateContent`, and a subprocess command bridge. The provider interface remains public so additional native APIs and agent frameworks can be added without changing the engine. API keys are read from a named environment variable and are never written to disk or logs.

## Safety And Failure Handling

- All file paths are resolved under the selected build workspace.
- Commands use argument arrays with `shell=False`, explicit timeouts, output caps, and a configurable allowlist.
- Model output is treated as untrusted JSON and schema-validated before execution.
- Every action and observation is checkpointed atomically.
- HTTP 408/409/425/429 and 5xx responses plus network failures are transient; authentication and malformed requests fail fast.
- Cost and token ceilings are checked before each model call and after each response.
- "Production-grade" is a verification target, not a guarantee: completion requires the project's declared checks to pass.

## Estimation Model

Estimates are ranges, never false precision. Scope signals produce a weighted work-unit count. Work units map to planning, implementation, repair, review, and integration turns. Per-turn context/output assumptions produce low/likely/high token ranges; provider pricing produces cost ranges; concurrency, expected latency, and retry allowance produce elapsed-time ranges. The JSON artifact records every coefficient so users can audit or override assumptions.

## Verification

Unit tests cover estimates, path confinement, action parsing, provider error normalization, retry timing, checkpoint/resume, budgets, and CLI behavior. Integration tests use a local scripted HTTP server and a scripted provider to perform a real multi-step build in a temporary workspace, including a forced 429 followed by recovery and a verification command.
