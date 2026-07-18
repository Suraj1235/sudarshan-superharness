# Sudarshan Optional Host Contract

The standalone `sudarshan` CLI does not require a host framework. It directly owns
provider calls, durable state, workspace tools, budgets, retries, human pauses, and
verification.

This contract applies only when embedding the historical multi-agent profile in a
host runtime. That host can be OpenClaw, a custom LLM API harness, an MCP-enabled
desktop app, a CI worker pool, or any framework capable of running isolated agent
sessions.

## Host Capabilities For The Multi-Agent Profile

| Capability | Required behavior |
|---|---|
| `spawn_subagent` | Start an isolated worker with a task, model, timeout, reasoning level, and tool policy. |
| `list_subagents` | Report active worker sessions for status and zombie cleanup. |
| `kill_subagent` | Stop a single worker. |
| `kill_all_subagents` | Stop all workers for abort and cleanup flows. |
| `stream_output` | Surface worker stdout/stderr to the controller. |
| `intercept_system_signals` | Detect exact strings such as `[SYSTEM: RELAY_BATON]` and route them to handlers. |
| `workspace_filesystem_rw` | Let Sudarshan and workers read/write the workspace. |
| `shell_exec` | Execute Python, Node, git, docker, npm, and npx commands. |

## Neutral Spawn Envelope

`platform_harness.py` emits a JSON-compatible request:

```json
{
  "platform": "generic",
  "task": "Build a production dashboard",
  "model": "gpt-5",
  "runtime": {
    "reasoning": "max",
    "timeout_seconds": 3600
  },
  "context": {
    "sharing": "none",
    "workspace_root": "/path/to/workspace",
    "read_first": [
      "SUDARSHAN.md",
      "enterprise_state/BATON_STATE.json",
      "enterprise_state/SUPER_PROMPT_MUTATIONS.json"
    ]
  },
  "tool_policy": {
    "deny": ["web_search"]
  }
}
```

Host adapters translate this envelope into their native API. These capabilities are
not prerequisites for the standalone engine or command-provider bridge.

## Signals

| Signal | Expected host action |
|---|---|
| `[SYSTEM: HAAS_REQUEST]` | Spawn or run the Observer, then escalate to a human only if unresolved. |
| `[SYSTEM: RELAY_BATON]` | Run `taskmanager.py --resume` and spawn a fresh orchestrator. |
| `[SYSTEM: JUDGE_PROBE_READY]` | Spawn a judge worker to produce `RESEARCH_VERDICT.json`. |
| `[SYSTEM: BUDGET_WARNING]` | Notify the operator. |
| `[SYSTEM: BUDGET_EXCEEDED]` | Halt, serialize state, and require operator approval. |
| `[SYSTEM: TASK_COMPLETE]` | Clean up workers, delete `.swarm_lock`, and deliver `COMPLETION_REPORT.md`. |

## Adapter Guidance

1. Call `SudarshanHarness(host_root).build_spawn_request(...)`.
2. Translate the neutral envelope into your framework's spawn call.
3. Preserve `context.sharing = none` unless your runtime can prove strict context isolation.
4. Deny native `web_search` for Sudarshan workers; use `skills/os_search/search.js`.
5. Route signals literally. Do not rely on an LLM to notice them in prose.
