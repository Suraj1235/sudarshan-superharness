# Contributing To Sudarshan

Thank you for helping make long-running LLM builds more inspectable and recoverable.

## Development Setup

```bash
git clone https://github.com/Suraj1235/sudarshan-superharness.git
cd sudarshan-superharness
python -m venv .venv
python -m pip install -e ".[test]"
python -m pytest tests -q
python verify_installation.py --workspace .
```

Activate `.venv` before installing on macOS, Linux, or Windows.

## What Makes A Good Change

- Keep the standalone engine independent of OpenClaw or any single provider.
- Preserve the three layers: architecture protocols, navigation/state, and tools.
- Define or update persisted schemas before changing stateful behavior.
- Treat model responses, provider payloads, paths, and command output as untrusted.
- Keep canonical run state separate from compatibility projections and temporary data.
- Add failure-path tests for retries, interruption, concurrency, budgets, and resume.
- Describe measured behavior precisely; do not turn design ambitions into guarantees.

New providers should normalize response text, token usage, retryability,
`Retry-After`, redaction, and response-size limits behind the existing `Provider`
protocol.

## Pull Requests

Open a focused pull request with:

- the problem and behavioral change
- tests or other evidence
- compatibility and security implications
- documentation changes for user-visible behavior

Do not commit API keys, generated workspaces, `.sudarshan/` run state, build outputs,
or personal agent configuration. By contributing, you agree that your contribution
is licensed under the repository's MIT License.
