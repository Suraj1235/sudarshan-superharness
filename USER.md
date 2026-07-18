# SUDARSHAN V16.9 — USER INJECTION BLOCK
# ═══════════════════════════════════════════════════════════════
# INSTALLATION: Append this entire block to your existing User
# configuration file (e.g., USER.md, auth config, or system prompt).
# Do NOT replace your existing user definitions — APPEND below them.
# ═══════════════════════════════════════════════════════════════

<!-- SUDARSHAN_V16.9_USER_INJECT_START -->

## SUDARSHAN PROTOCOL: L1 ACCESS & BUDGET ENFORCEMENT

### Authorization Gate
The `/taskmanager` command is a **privileged L1-exclusive operation**. Before executing
any `/taskmanager` invocation, you MUST verify that the requesting user matches your
existing L1/admin authorization. If your platform has its own auth system, defer to it.
Sudarshan does not replace your auth — it gates behind it.

### Budget Enforcement (Configurable)
During Swarm execution, the Orchestrator MUST respect these token burn limits.
Adjust these values based on your platform's pricing and your user's budget:

```json
{
  "sudarshan_budget": {
    "max_daily_token_burn_usd": 25.00,
    "max_session_token_burn_usd": 10.00,
    "alert_threshold_percent": 80,
    "hard_kill_on_exceed": true
  }
}
```

> **Runtime Config Location:** At `taskmanager.py --init`, these values are seeded into
> `enterprise_state/BLACKBOARD_STATUS.json.metadata.budget`. The `--check-budget` command
> reads from there (not from this USER.md block) for deterministic enforcement.

**Enforcement Rules:**
- Before every critical action, call `python3 taskmanager.py --check-budget`.
- At `alert_threshold_percent`, emit `[SYSTEM: BUDGET_WARNING]` to the Main Thread.
- If `hard_kill_on_exceed` is `true` and session burn exceeds `max_session_token_burn_usd`,
  emit `[SYSTEM: BUDGET_EXCEEDED]`, gracefully halt the Swarm, and serialize state to
  `enterprise_state/BATON_STATE.json` for resumption.
- The Observer Node CANNOT override budget kills. Only L1 can restart via `/taskmanager --force`.

### Notification Routing
When the Swarm emits system events (HaaS requests, hourly updates, task completion),
route them through your platform's existing notification channels. If your platform
has no push notification capability, emit all events as `[SYSTEM: ...]` tags in stdout
for the Main Thread to surface in chat.

### API Secret Handling
- `.env` files MUST NEVER be committed to git (enforced in Phase 1 Gate 1).
- API keys provided via Human-as-a-Service (HaaS) are written to
  `isolated_tasks/HUMAN_INPUT.txt` and MUST be consumed and deleted within 60 seconds.

<!-- SUDARSHAN_V16.9_USER_INJECT_END -->
