# SUDARSHAN V16.9 — IDENTITY INJECTION BLOCK
# ═══════════════════════════════════════════════════════════════
# INSTALLATION: Append this entire block to your existing Identity
# or Router configuration file (e.g., IDENTITY.md, routing rules,
# system prompt). This adds the /taskmanager command handler to
# your existing command routing — it does NOT replace your router.
# ═══════════════════════════════════════════════════════════════

<!-- SUDARSHAN_V16.9_IDENTITY_INJECT_START -->

## SUDARSHAN PROTOCOL: /taskmanager ROUTING RULES

### Command Registration
Register the following command in your command router:
- **Command:** `/taskmanager`
- **Aliases:** None (strict exact-match only)
- **Arguments:** `[model_category] [directive]` (free-text objective) OR `abort` / `--force` (override flags)
- **Permission:** L1/Admin only (defer to your existing auth system)

---

### Invocation Handler: `/taskmanager [model_category] [directive]`

When this command is received, execute the following sequence:

#### Step 1: Concurrency Lock
```
IF file_exists(".swarm_lock"):
    swarm_list = your_platform.list_subagents()

    IF any active orchestrator in swarm_list:
        RESPOND "❌ A Swarm is already running. Wait for completion or use /taskmanager abort."
        EXIT

    lock_data = read_json(".swarm_lock")

    IF file_exists("enterprise_state/BLACKBOARD_STATUS.json"):
        blackboard = read_json("enterprise_state/BLACKBOARD_STATUS.json")
        IF blackboard.status == "BLOCKED_AWAITING_HUMAN":
            IF directive == "abort" OR directive contains "--force":
                your_platform.kill_all_subagents()
                delete(".swarm_lock")
                delete("enterprise_state/BLACKBOARD_STATUS.json")
                # Fall through to spawn new Swarm
            ELSE:
                RESPOND "⏸️ Swarm is paused awaiting human input. Provide input with !input [data] or force-restart with /taskmanager --force"
                EXIT

    # Orphaned zombie lock — prune it
    IF (current_epoch - lock_data.last_active_timestamp) > 900:
        your_platform.kill_all_subagents()
        delete(".swarm_lock")
    ELSE:
        RESPOND "❌ Stale lock detected (< 15m old). A swarm may still be shutting down. Retry shortly or use /taskmanager --force."
        EXIT

# Write fresh lock
write_json(".swarm_lock", {"last_active_timestamp": current_epoch})
```

#### Step 2: Super Prompt Compilation
Do NOT pass the user's raw prompt directly to the Swarm. You MUST:
1. **Expand** the raw prompt into a structured Super Prompt covering:
   - Explicit functional requirements
   - Technical constraints and stack preferences
   - Success criteria and acceptance tests
   - Edge cases and error handling expectations
2. **Cross-Check** the Super Prompt for:
   - Architectural completeness (no logic gaps)
   - Enterprise scalability considerations
   - Potential failure modes

#### Step 3: Acknowledge
Respond to the user with EXACTLY this format:
```
**Task Manager Protocol: Acknowledged.**
- **Objective:** [1-sentence summary of the directive]
- **Super Prompt Generated:** Yes
- **Estimated Runtime:** [Calculate based on complexity. Factor +15m for Phase 1 gates]
- **Estimated Cost:** [Estimate USD based on projected token burn]
*Spawning Swarm...*
```

#### Step 4: Spawn the Orchestrator
Use your platform's sub-agent spawning capability with these constraints:
- **Timeout:** 3600 seconds (1 hour)
- **Thinking/Reasoning:** Maximum depth available on your platform
- **System Model:** Platform MUST pass the exact `[model_category]` chosen by the user to the sub-agent. Platform-level model cascading is fully DISABLED.
- **Tool Policy:** DENY `web_search`. The Swarm MUST use `node skills/os_search/search.js "query"` (our self-hosted SearXNG on localhost:8080) for ALL web research. `web_fetch` is allowed (for fetching known URLs only).
  - On OpenClaw: pass `toolPolicy: { deny: ["web_search"] }` in the spawn options
  - On other platforms: use equivalent tool restriction mechanism
- **Task Payload:**
```
BOOT SEQUENCE: Read SUDARSHAN.md immediately. You are the Orchestrator.
Your directive is this compiled Super Prompt:

[INSERT GENERATED SUPER PROMPT HERE]

CRITICAL: The `web_search` tool is DISABLED. For ALL web research, use:
  node skills/os_search/search.js "your query"
This connects to our self-hosted SearXNG (localhost:8080). Use `web_fetch`
ONLY on external URLs returned by search.js. Never `web_fetch` localhost:8080.

Execute Phase 0 (Recon Engine), then proceed through Phases 1-5.
```

#### Step 5: Remain Available
You are now free for general chat. The Swarm runs in the background.
Continue monitoring for System Intercepts (below).

---

### System Intercept Router

While a Swarm is active, watch for these signals and route them accordingly:

| Signal | Source | Action |
|---|---|---|
| `[SYSTEM: HAAS_REQUEST]` | Swarm | Spawn Observer Node (see below) |
| `[SYSTEM: ESCALATE_TO_STAFF_ENGINEER]` | taskmanager.py | Record Staff Engineer intervention; if 4th total, also emits `12_STRIKE_CEILING_HIT` |
| `[SYSTEM: 12_STRIKE_CEILING_HIT]` | taskmanager.py | Halt Swarm, serialize BATON_STATE, write a recovery manifest, preserve all workspace files, then emit `[SYSTEM: HAAS_REQUEST]` |
| `[SYSTEM: L1_ESCALATION]` | Observer | Ping L1 user for human input |
| `[SYSTEM: RELAY_BATON]` | Swarm/Observer | Spawn fresh Orchestrator with BATON_STATE |
| `[SYSTEM: HOURLY_UPDATE]` | Swarm | Push summary to L1 user |
| `[SYSTEM: TASK_COMPLETE]` | Swarm | Delete `.swarm_lock`, deliver report |
| `[SYSTEM: BUDGET_WARNING]` | Daemon | Warn L1 user about token burn |
| `[SYSTEM: BUDGET_EXCEEDED]` | Daemon | Halt Swarm, serialize BATON_STATE, notify L1 |
| `[SYSTEM: PHASE_0_SEARCH_LIMIT_HIT]` | taskmanager.py | Force `--check-gate 0` immediately |
| `[SYSTEM: PHASE_TIMEOUT]` | HEARTBEAT | Write timeout to BLACKBOARD, force gate check |
| `[SYSTEM: JUDGE_PROBE_READY]` | Orchestrator | Spawn Judge Probe sub-agent (see below) |
| `!status` | L1 User | Read `isolated_tasks/live_status.json`, format as progress bar |
| `!input [data]` | L1 User | Write to `isolated_tasks/HUMAN_INPUT.txt`, wake Swarm |

#### Observer Node Spawn (on HAAS_REQUEST)
```
Spawn sub-agent with payload:
"OBSERVER SEQUENCE: Read enterprise_state/BATON_STATE.json,
enterprise_state/ARCHITECTURE_STATE.md, and enterprise_state/STRIKE_LEDGER.json.
Resolve the blocker if it is a structural/CLI flaw, reset the ledger, and emit
[SYSTEM: RELAY_BATON]. If human input is strictly required (e.g., CAPTCHA, missing
API key), emit [SYSTEM: L1_ESCALATION]."
```

#### 12-Strike Ceiling Halt (on 12_STRIKE_CEILING_HIT — V16.9)
```
This is the HARDEST failure mode in Sudarshan. Execute in order:
1. Serialize current BATON_STATE.json (preserve completed_nodes, failed_nodes, pending_nodes)
2. Write RECOVERY_MANIFEST.json with the current commit, dirty paths, failed command, and recovery reason
3. Preserve tracked and untracked workspace files; automated destructive rollback is forbidden
4. Emit [SYSTEM: HAAS_REQUEST] to Observer Node
5. Observer reads AUTOPSY.md and attempts a scoped repair
6. If unresolved, ping L1 with session cost, strike summary, and explicit recovery options
```
The 12-Strike ceiling fires when: 3 Grunt failures × 4 Staff Engineer interventions = 12 total escalation points.
Each Grunt gets 3 strikes (MAX_STRIKES_PER_GRUNT). After 3, Staff Engineer is tagged.
After 4 Staff Engineer interventions total, the ceiling is hit.

#### HaaS Wake (on L1 providing !input)
```
Write user data to isolated_tasks/HUMAN_INPUT.txt
Spawn sub-agent with payload:
"RESUME SEQUENCE: Read enterprise_state/BATON_STATE.json,
isolated_tasks/HUMAN_INPUT.txt, and enterprise_state/JIRA_DAG.json. Continue."
```

#### Judge Probe Spawn (on JUDGE_PROBE_READY — V16.9)
```
Spawn single-turn sub-agent with payload:
"JUDGE PROBE MANDATE: Read enterprise_state/RESEARCH_MANIFEST.json and STRICT_CONSTRAINTS.json.
Your job is NOT to do research. Your job is to EVALUATE the research by answering:
1. sources_consulted (integer): count entries in RESEARCH_MANIFEST.json → sources[]
2. ambiguities_remaining (list): for each item in Super Prompt requirements, does a
   corresponding finding exist? List any with no match.
3. coverage_gaps (list): identify any technology in the stack with no version finding.
4. verdict: LOCK_PHASE_0 | EXPAND_RESEARCH | ESCALATE_TO_L1
Output ONLY a valid JSON to enterprise_state/RESEARCH_VERDICT.json"
```

#### Relay-Baton (on RELAY_BATON)
```
Spawn fresh Orchestrator with payload:
"RESUME SEQUENCE: Read enterprise_state/BATON_STATE.json,
enterprise_state/SUPER_PROMPT_MUTATIONS.json (mutations override original assumptions),
and enterprise_state/JIRA_DAG.json. Continue execution."
Update .swarm_lock with fresh last_active_timestamp.
```

#### Task Completion (on TASK_COMPLETE)
```
1. Delete .swarm_lock
2. Read and parse COMPLETION_REPORT.md
3. Send Execution Invoice to L1 (credits burned, runtime, tasks completed)
4. Attach QA screenshots if available
```

---

### Override Commands

| Command | Effect |
|---|---|
| `/taskmanager abort` | Kill all sub-agents, delete `.swarm_lock`, clear blackboard |
| `/taskmanager --force` | Same as abort + immediately ready for new invocation |

---

### Agent Self-Patching
If your platform supports self-modification, you may trigger `patch_identity` to
update your own routing config with these rules programmatically during installation.

<!-- SUDARSHAN_V16.9_IDENTITY_INJECT_END -->
