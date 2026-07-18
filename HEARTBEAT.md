# SUDARSHAN V16.9 — HEARTBEAT INJECTION BLOCK
# ═══════════════════════════════════════════════════════════════
# INSTALLATION: Append this entire block to your existing Daemon,
# Lifecycle, or Cron configuration. If your platform has no daemon
# system, implement these as periodic checks in your Main Thread's
# event loop. This adds lifecycle management for Sudarshan Swarms.
# ═══════════════════════════════════════════════════════════════

<!-- SUDARSHAN_V16.9_HEARTBEAT_INJECT_START -->

## SUDARSHAN PROTOCOL: SWARM LIFECYCLE DAEMON

### Overview
These are periodic checks that keep the Sudarshan Swarm healthy. The Main Thread (or
your platform's daemon system) MUST execute these at the specified intervals while any
Swarm is active.

---

### Check 1: Zombie Prune (Every 5 Minutes)
```
IF file_exists(".swarm_lock"):
    lock_data = read_json(".swarm_lock")
    age_seconds = current_epoch - lock_data.last_active_timestamp
    current_phase = lock_data.phase  # V16.9: CRITICAL — must check phase

    # Phase-aware prune: long-running phases get more slack before pruning
    PHASE_GRACE = {
        "phase_0_research":    900,    # 15 min
        "phase_1_contract":    900,    # 15 min
        "phase_2_execution":   900,    # 15 min
        "phase_3_cicd":        900,    # 15 min
        "phase_4_integration": 900,    # 15 min
        "phase_5_delivery":   5400,   # 90 min (Phase 5 can run up to 2h)
        "completed":           60,     # 1 min after done
        "halted":              60,     # 1 min after halted
    }
    max_age = PHASE_GRACE.get(current_phase, 900)

    IF age_seconds > max_age:
        your_platform.kill_all_subagents()
        delete(".swarm_lock")
        LOG "[HEARTBEAT] Zombie swarm pruned after {age_seconds}s inactivity (phase: {current_phase})"
    # ELSE: still within grace period — skip prune even if orchestrator temporarily
    # disappears from list_subagents() (prevents Phase 5 orphaning mid-delivery)
```

**Why:** LLM sessions can silently die from 503 timeouts, OOM kills, or API rate limits.
Without this check, `.swarm_lock` persists forever, blocking all future `/taskmanager`
invocations. The phase-aware grace periods prevent the prune from killing a legitimate
Phase 5 delivery run (which can take up to 2 hours) if `list_subagents()` temporarily
misreports the orchestrator's status.

---

### Check 2: Swarm Heartbeat Touch (Every 5 Minutes)
```
IF file_exists(".swarm_lock"):
    active_agents = your_platform.list_subagents()

    IF any orchestrator in active_agents:
        # Swarm is alive — keep the lock fresh
        lock_data = read_json(".swarm_lock")
        lock_data.last_active_timestamp = current_epoch
        write_json(".swarm_lock", lock_data)
    # If no active agents, do nothing — let Zombie Prune handle it
```

**Why:** Prevents the Zombie Prune from killing a slow but still-active Swarm.

---

### Check 3: Relay-Baton Watchdog (Continuous)
```
IF received_signal("[SYSTEM: RELAY_BATON]"):
    wait(30 seconds)

    active_agents = your_platform.list_subagents()
    IF no orchestrator in active_agents:
        # The relay was dropped — respawn manually
        baton = read_json("enterprise_state/BATON_STATE.json")
        your_platform.spawn_subagent(
            payload="RESUME SEQUENCE: Read enterprise_state/BATON_STATE.json
                     and enterprise_state/JIRA_DAG.json. Continue execution."
        )
        update .swarm_lock with fresh last_active_timestamp
        LOG "[HEARTBEAT] Relay-Baton dropped. Respawned Orchestrator."
```

**Why:** If the Main Thread misses a relay-baton signal (e.g., due to network hiccup),
the Swarm silently dies mid-execution with no recovery.

---

### Check 4: Budget Watchdog (Every 15 Minutes — V16.9)
```
# Call the deterministic budget enforcer (reads BLACKBOARD_STATUS.json metadata)
TRY:
    result = run("python3 taskmanager.py --check-budget --workspace .")
    IF result.exit_code == 3:
        emit "[SYSTEM: BUDGET_EXCEEDED]"
        your_platform.kill_all_subagents()
        serialize state to enterprise_state/BATON_STATE.json
        delete(".swarm_lock")

    ELSE IF result.stdout contains "[SYSTEM: BUDGET_WARNING]":
        emit "[SYSTEM: BUDGET_WARNING]"
        # Log and notify L1, but do NOT halt the Swarm

    ELSE IF result.exit_code not in (0, 3):
        # taskmanager.py missing, python3 not in PATH, or script crashed
        LOG "[HEARTBEAT] Budget check FAILED: exit={result.exit_code} stderr={result.stderr}"
        emit "[SYSTEM: BUDGET_WARNING]"  # Fail-safe: warn L1, don't ignore
        notify L1: "Budget enforcement unavailable — taskmanager.py may be missing"

EXCEPT Exception as e:
    LOG "[HEARTBEAT] Budget watchdog exception: {e}"
    emit "[SYSTEM: BUDGET_WARNING]"
    notify L1: "Budget enforcement unavailable"
```

**Why:** The budget limits are stored in `BLACKBOARD_STATUS.json.metadata.budget` (initialized by
`taskmanager.py --init`). The `--check-budget` command does the math deterministically
(no LLM self-assessment). The LLM must honor these signals — Observer Node CANNOT override
budget kills; only L1 can restart via `/taskmanager --force`. Budget enforcement is a
no-op if taskmanager.py is absent or broken — the fail-safe warns L1 so the human can act.

---

### Check 5: Hourly Status Push (Every 60 Minutes)
```
IF file_exists("isolated_tasks/live_status.json"):
    status = read_json("isolated_tasks/live_status.json")
    ts = status.get("timestamp")

    # V16.9: Type guard — reject null, string, or malformed timestamps
    IF not isinstance(ts, (int, float)):
        LOG "[HEARTBEAT] WARN: live_status.json timestamp is malformed (type: {type(ts).__name__}). Skipping hourly check."
        SKIP hourly push
        RETURN

    last_update = int(ts)
    elapsed_since_update = current_epoch - last_update

    IF (current_epoch - last_push_epoch) >= 3600:
        FORMAT status as summary bullet points
        PUSH to L1 user via platform notification channel
        last_push_epoch = current_epoch

    IF elapsed_since_update > 3600:
        LOG "[HEARTBEAT] WARN: No Swarm status update in 60+ minutes. May be stalled."
```

---

### Check 6: Phase 0 Timeout Watchdog (V16.9 — Every 5 Minutes)
```
IF file_exists(".swarm_lock"):
    lock_data = read_json(".swarm_lock")
    blackboard = read_json("enterprise_state/BLACKBOARD_STATUS.json")

    IF lock_data.phase == "phase_0_research":
        phase_0_start = lock_data.created_at  # Static — not refreshed by heartbeat touch
        elapsed = current_epoch - phase_0_start

        IF elapsed >= MAX_PHASE_0_DURATION_SECONDS (default: 3600):
            # Phase 0 has hit the time ceiling
            blackboard.status = "PHASE_TIMEOUT"
            blackboard.blocker_description = "Phase 0 exceeded time limit"
            write_json("enterprise_state/BLACKBOARD_STATUS.json", blackboard)
            emit "[SYSTEM: PHASE_TIMEOUT]"
            LOG "[HEARTBEAT] Phase 0 timeout. Forcing gate check."
```

**Why:** Phase 0 has no natural upper bound. Without a time ceiling, a looping or stalled
Orchestrator can silently burn tokens for hours. This check forces a Phase 0 exit
decision (LOCK_PHASE_0 / EXPAND_RESEARCH / ESCALATE_TO_L1) when the ceiling hits.
The quality floor is separately enforced by the Judge Probe's coverage criteria.

---

### Implementation Note
These checks are written as behavioral directives. Your platform can implement them as:
- **Inline checks** in the Main Thread's event loop (simplest)
- **A standalone daemon script** if your platform supports background processes
- **Cron jobs / scheduled tasks** on the host OS

The packaged Sudarshan overlay now includes `heartbeat_daemon.py` implementing the
Phase 0 timeout watchdog and budget watchdog directly. Host platforms should prefer
that script for baseline lifecycle enforcement, then extend it with platform-native
agent listing/killing hooks if deeper integration is available.

The key constraint is that Check 1 (Zombie Prune) MUST run regardless of other checks,
as it is the only defense against orphaned `.swarm_lock` files.

<!-- SUDARSHAN_V16.9_HEARTBEAT_INJECT_END -->
