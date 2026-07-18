# OPENCLAW CERTIFICATION CHECKLIST

Use this checklist before claiming a Sudarshan build is ready for fresh-agent installation.

## Install

- `python install.py --agent-root <agent-root> --noninteractive --skip-searxng` exits `0`
- `<agent-root>/sudarshan/` exists
- `<agent-root>/workspace/` exists
- `agent_config.json` contains Sudarshan command hooks and intercepts

## Verify

- `python verify_installation.py --workspace <agent-root>` exits `0`
- all required plugin schemas are present and registered
- identity paths point at the installed Sudarshan overlay

## Runtime Smoke Test

- `python taskmanager.py --workspace <workspace> --skip-preflight --frontend-only --init "Build a demo app"` exits `0`
- `isolated_tasks/live_status.json` exists
- `enterprise_state/BLACKBOARD_STATUS.json` contains the selected model
- `PRE_MORTEM.md` is seeded from template

## Host Integration

- `/taskmanager` resolves to `openclaw_router_bridge.handle_taskmanager`
- `!status` resolves to `openclaw_router_bridge.handle_status`
- `!input` resolves to `openclaw_router_bridge.handle_input`
- system intercepts for HaaS, Relay Baton, Budget Warning/Exceeded, Judge Probe, and Task Complete are registered

## Optional Runtime Readiness

- Node.js available on PATH
- Docker daemon available
- SearXNG reachable on `localhost:8080`

If the optional runtime readiness items are skipped, classify the install as a degraded smoke-test install rather than a fully research-ready production install.
