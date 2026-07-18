# Installing Sudarshan

The standalone CLI is the canonical installation. OpenClaw and the historical
multi-agent host profile are optional compatibility paths.

## Requirements

- Python 3.9 or newer
- An LLM endpoint, local model, or command bridge when starting a build

Git, Node.js, Docker, SearXNG, and OpenClaw are optional. Model-requested host
commands may need project-specific tools such as Git, Node.js, Cargo, or Go.

## Install From Git

```bash
git clone https://github.com/Suraj1235/sudarshan-superharness.git
cd sudarshan-superharness
python -m venv .venv
```

Activate the environment:

```bash
# macOS / Linux
source .venv/bin/activate

# Windows PowerShell
.venv\Scripts\Activate.ps1
```

Install and inspect the runtime:

```bash
python -m pip install -e .
sudarshan doctor
sudarshan --version
```

## First Run

Estimate before spending tokens:

```bash
sudarshan estimate --prd ./PRD.md --model YOUR_MODEL_ID --json
```

Run against an OpenAI-compatible endpoint:

```bash
export SUDARSHAN_API_KEY="your-key"
sudarshan build --prd ./PRD.md --workspace ./builds/product \
  --provider openai-compatible \
  --base-url https://YOUR_PROVIDER/v1 \
  --model YOUR_MODEL_ID \
  --allow-host-commands
```

PowerShell uses `$env:SUDARSHAN_API_KEY = "your-key"` for the environment
variable. Native `anthropic` and `gemini` providers default to
`ANTHROPIC_API_KEY` and `GEMINI_API_KEY` respectively.

`--allow-host-commands` permits model-requested subprocesses under your current
user account. It is not an OS sandbox. Use a disposable VM, container, or
low-privilege account for untrusted builds.

## Resume And Human Input

```bash
sudarshan status --workspace ./builds/product
sudarshan resume --workspace ./builds/product
sudarshan input --workspace ./builds/product --value "Use PostgreSQL"
```

Run state is stored under `<workspace>/.sudarshan/`. API keys are read from the
environment on each invocation and are not stored in that state.

## Verify A Source Checkout

```bash
python -m pip install -e ".[test]"
python -m pytest tests -q
python verify_installation.py --workspace .
```

## Optional OpenClaw Compatibility Install

The legacy installer applies the protocol overlay to a fresh OpenClaw-style
agent root containing `agent_config.json` and an `identity/` directory:

```bash
python install.py \
  --agent-root /path/to/openclaw-agent \
  --noninteractive \
  --skip-searxng
```

Windows and POSIX wrappers are also provided:

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1 `
  -AgentRoot C:\path\to\openclaw-agent -NonInteractive -SkipSearXNG
```

```bash
sh ./install.sh --agent-root /path/to/openclaw-agent --noninteractive --skip-searxng
```

Verify the overlay with:

```bash
python verify_installation.py --workspace /path/to/openclaw-agent
```

This adapter installs the role protocols, task manager, Observer, templates,
plugin schemas, and router hooks. It does not make the host-dependent autonomous
multi-agent profile a production guarantee. See `OPENCLAW_DEPLOYMENT_RUNBOOK.md`
and `PLATFORM_CONTRACT.md` for that compatibility boundary.

## Optional SearXNG Stack

The standalone engine does not require SearXNG. To start the historical research
stack, set a strong secret and run the loopback-only Compose profile:

```bash
cd infrastructure/searxng
export SEARXNG_SECRET="$(python -c 'import secrets; print(secrets.token_hex(32))')"
docker compose up -d
```

Do not expose this stack publicly without a reverse proxy, authentication,
monitoring, and an operator-managed update process.

## Troubleshooting

| Symptom | Check |
|---|---|
| `sudarshan` is not found | Activate the virtual environment and rerun `python -m pip install -e .` |
| Provider rejects authentication | Confirm the selected key environment variable and endpoint |
| A local endpoint is rejected | Use `localhost`, `127.0.0.1`, or `::1`; remote endpoints require HTTPS |
| A build will not run commands | Add `--allow-host-commands` only after reviewing the security boundary |
| Resume cannot find a run | Pass the same workspace used by `build` |
| OpenClaw installer reports missing config | Point `--agent-root` at a supported fresh agent root |
