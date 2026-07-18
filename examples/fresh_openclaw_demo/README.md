# Fresh OpenClaw Demo

This example documents the minimal end-to-end Sudarshan smoke path for a blank OpenClaw agent.

## Flow

1. Install Sudarshan into a blank agent:

```bash
python install.py --agent-root /path/to/agent --noninteractive --skip-searxng
```

2. Verify the install:

```bash
python verify_installation.py --workspace /path/to/agent
```

3. Bootstrap a workspace from the installed overlay:

```bash
cd /path/to/agent/sudarshan
python taskmanager.py --workspace /path/to/agent/workspace --skip-preflight --frontend-only --init "Build a demo dashboard"
```

4. Inspect:

- `/path/to/agent/workspace/enterprise_state/BLACKBOARD_STATUS.json`
- `/path/to/agent/workspace/isolated_tasks/live_status.json`
- `/path/to/agent/workspace/PRE_MORTEM.md`

This path is the minimal certification-grade smoke test for a fresh install.
