# OPENCLAW DEPLOYMENT RUNBOOK

## Goal

Install Sudarshan into a fresh OpenClaw agent and make it operational without manual
kernel file copying.

## Supported Agent Contract

The installer currently supports an OpenClaw agent root with:

```text
agent_config.json
identity/IDENTITY.md
identity/SOUL.md
identity/USER.md
identity/HEARTBEAT.md
```

The installer writes:

```text
<agent-root>/
  sudarshan/
  workspace/
  agent_config.json   # patched in place
```

## Install

```bash
python install.py --agent-root /path/to/openclaw-agent --noninteractive --skip-searxng
```

## Verify

```bash
python verify_installation.py --workspace /path/to/openclaw-agent
```

## Post-install Expectations

The patched `agent_config.json` should now contain:

- `sudarshan.enabled = true`
- command hooks for `/taskmanager`, `!status`, `!input`
- system intercepts for major Sudarshan lifecycle signals
- default denial of `web_search`
- identity paths pointing at `sudarshan/IDENTITY.md`, `sudarshan/SOUL.md`, `sudarshan/USER.md`, and `sudarshan/HEARTBEAT.md`

## Smoke Test

```bash
cd /path/to/openclaw-agent/sudarshan
python -c "import taskmanager; taskmanager.cmd_init('Build a demo app', frontend_only=True, model_id='default')"
```

Expected results:

- `workspace/enterprise_state/BLACKBOARD_STATUS.json` exists
- `workspace/PRE_MORTEM.md` is seeded from template
- `workspace/.swarm_lock` exists after bootstrap

## Current Limits

- The installer does not yet auto-provision SearXNG/Docker.
- Host-specific OpenClaw runtime invocation still depends on the host honoring the patched command and intercept config.
- The heartbeat daemon exists as a real module, but host scheduling of it is still an operator/runtime concern.

## Recommended Productionization Steps

1. Register a host scheduler for `heartbeat_daemon.py`.
2. Ensure the OpenClaw host consumes `agent_config.json` as the authoritative routing config.
3. Add a host-level acceptance test that exercises `/taskmanager`, `!status`, and `!input` through the actual router.
