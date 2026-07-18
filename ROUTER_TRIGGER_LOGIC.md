# SUDARSHAN V16.9 — ROUTER TRIGGER LOGIC (Reference)

> **Note:** This file is a **reference document** for developers. The actual routing
> logic that the LLM reads at runtime is in `IDENTITY.md` (the injection block).
> If there is any conflict between this file and `IDENTITY.md`, **IDENTITY.md wins**.

---

## The /taskmanager Protocol (Hard-Coded Execution Lock)

- **Trigger:** `/taskmanager [directive]` (L1 Exclusive).
- **Airgap Mandate:** The Sudarshan Protocol is STRICTLY AIRGAPPED behind the exact
  string `/taskmanager`. No semantic mapping from casual requests.
- **Concurrency Lock:** ONE Task Manager swarm at a time. Use `.swarm_lock`.
- **Anti-Chatbot Mandate:** The main thread MUST NOT execute directives directly.
- **Installed Bridge:** Fresh installs patch `agent_config.json` so `/taskmanager`, `!status`, and `!input` route through `openclaw_router_bridge.py`.

## Action Sequence

1. **Check concurrency lock:**
   - If `.swarm_lock` exists but no Orchestrator running → check `enterprise_state/BLACKBOARD_STATUS.json`
   - If `BLOCKED_AWAITING_HUMAN` → wait (unless `--force` or `abort`)
   - If zombie (>900s since `last_active_timestamp`) → kill + delete lock
   - If running → reject the command
   - If clear → write fresh `.swarm_lock`

2. **Bootstrap workspace (recommended):**
    ```
    python3 taskmanager.py --init "[directive]"
    ```
   This creates `enterprise_state/` scaffolds, compiles the Super Prompt, acquires
    the `.swarm_lock`, and outputs the exact boot payload.

   **Offline smoke-test path:**
   ```
   python3 taskmanager.py --workspace <workspace> --skip-preflight --frontend-only --init "[directive]"
   ```
   This is intended for installer certification and local smoke tests when the operator
   has intentionally skipped Docker/SearXNG provisioning.

3. **Issue Initialization Acknowledgment** (exact format in `IDENTITY.md` §3)

4. **Spawn the Orchestrator** via your platform's sub-agent system with the boot
   payload from step 2. Constraints: `timeout=3600s`, max reasoning depth.

5. **Remain available** for general chat.

6. **Monitor** `enterprise_state/BLACKBOARD_STATUS.json` for system intercepts.

## System Intercepts (Main Thread Router)

| Signal | Source | Action |
|---|---|---|
| `[SYSTEM: HAAS_REQUEST]` | Swarm | Spawn Observer Node (see `IDENTITY.md` §Observer) |
| `[SYSTEM: ESCALATE_TO_STAFF_ENGINEER]` | taskmanager.py | Record Staff Engineer intervention. At 4th intervention, also triggers `12_STRIKE_CEILING_HIT`. |
| `[SYSTEM: 12_STRIKE_CEILING_HIT]` | taskmanager.py | Halt Swarm, serialize BATON_STATE, preserve the workspace, write `RECOVERY_MANIFEST.json`, and emit `[SYSTEM: HAAS_REQUEST]`. |
| `[SYSTEM: L1_ESCALATION]` | Observer | Ping L1 user for human input |
| `[SYSTEM: RELAY_BATON]` | Swarm/Observer | Spawn fresh Orchestrator with `BATON_STATE` |
| `[SYSTEM: HOURLY_UPDATE]` | Swarm | Push summary to L1 user |
| `[SYSTEM: TASK_COMPLETE]` | Swarm | Delete `.swarm_lock`, deliver `COMPLETION_REPORT.md` |
| `[SYSTEM: BUDGET_WARNING]` | taskmanager.py --check-budget | Warn L1 user (spend >= alert_threshold_percent) |
| `[SYSTEM: BUDGET_EXCEEDED]` | taskmanager.py --check-budget | Halt Swarm, serialize BATON_STATE, notify L1 |
| `[SYSTEM: PHASE_0_SEARCH_LIMIT_HIT]` | taskmanager.py | Force `--check-gate 0` immediately |
| `[SYSTEM: PHASE_TIMEOUT]` | HEARTBEAT | Write timeout to BLACKBOARD, force gate check |
| `[SYSTEM: JUDGE_PROBE_READY]` | Orchestrator | Spawn Judge Probe (see `IDENTITY.md` §Judge Probe) |
| `!status` | L1 User | Read `isolated_tasks/live_status.json`, format as progress |
| `!input [data]` | L1 User | Write to `isolated_tasks/HUMAN_INPUT.txt`, wake Swarm |

## Relay-Baton Resume

When resuming (manually or after `RELAY_BATON`):
```
python3 taskmanager.py --resume
```
This reads `enterprise_state/BATON_STATE.json`, refreshes `.swarm_lock`, and outputs
the resume payload for a fresh Orchestrator spawn.

## Gate Verification (The Killer Feature)

The Orchestrator should use these for deterministic binary gate checks:
```
python3 taskmanager.py --check-gate 0   # Judge Probe verdict + scope validation
python3 taskmanager.py --check-gate 1   # Git foundation + state files
python3 taskmanager.py --check-gate 2   # Pre-Mortem + DAG_RATIONALE.md
python3 taskmanager.py --check-gate 3   # PM_AUDIT_REPORT.json AA1-AA5
python3 taskmanager.py --check-gate 4   # Spectral lint on openapi.yaml
python3 taskmanager.py --check-gate-ui-spec  # UI_SPEC.json validation (Gate 4b)
python3 taskmanager.py --check-gate dag # DAG mathematical validation
python3 taskmanager.py --check-gate ports # Dev ports clean (Phase 5)
python3 taskmanager.py --record-search  # Increment Phase 0 search counter
python3 taskmanager.py --tag-phase N    # Create phase boundary git tag
python3 taskmanager.py --check-budget   # Budget check (exit 0=OK, exit 3=EXCEEDED)
```

Exit code 0 = PASS, exit code 1 = FAIL, exit code 2 = ESCALATE_TO_L1 (Gate 0 only).
This gives the LLM a deterministic answer instead of probabilistic self-assessment.

## Override Commands

| Command | Effect |
|---|---|
| `/taskmanager abort` | Kill all sub-agents, delete `.swarm_lock`, clear blackboard |
| `/taskmanager --force` | Same as abort + immediately ready for new invocation |
