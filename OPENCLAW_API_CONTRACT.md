# SUDARSHAN V16.9 — OPENCLAW API CONTRACT
# ═══════════════════════════════════════════════════════════════
# This document defines the MINIMUM API surface that a host
# platform must expose for Sudarshan to function. If your
# platform does not implement these primitives, Sudarshan
# CANNOT operate and will fail at the invocation stage.
# ═══════════════════════════════════════════════════════════════

> OpenClaw is now one supported adapter profile, not a hard dependency of the
> Sudarshan core. For the platform-neutral contract, see `PLATFORM_CONTRACT.md`
> and `SUDARSHAN_HOST_CONTRACT.json`.

## 1. Required Platform Capabilities

### 1.1 Sub-Agent Spawning
**Primitive:** `spawn_subagent(task, options) → agent_id`

The platform MUST support spawning isolated sub-agents (background sessions) that:
- Run independently of the main conversation thread (asynchronous / non-blocking)
- Support **Parallel Instantiation**: the platform must be able to run 3+ of these sessions simultaneously.
- Have their own context window (not shared with main thread)
- Can read/write files in the workspace
- Can execute shell commands (python3, node, git, docker, npm)
- Support a timeout parameter (minimum 3600 seconds / 1 hour)
- Support a thinking/reasoning depth parameter (use maximum available)
- Support forcing a specific `[model_category]` to disable platform-level cascading.

**OpenClaw equivalent:** `sessions_spawn(task, timeoutSeconds, thinking, model)`

---

### 1.2 Sub-Agent Listing
**Primitive:** `list_subagents() → [agent_id, status, ...]`

The platform MUST support listing all currently active sub-agents spawned by the
current session.

**OpenClaw equivalent:** `subagents(action="list")`

---

### 1.3 Sub-Agent Termination
**Primitive:** `kill_subagent(agent_id)` or `kill_all_subagents()`

The platform MUST support forcefully terminating one or all active sub-agents.

**OpenClaw equivalent:** `subagents(action="kill")`

---

### 1.4 System Intercept Routing & Output Monitoring
**Primitive:** The platform MUST intercept sub-agent stdout/stderr and expose it to the Main Thread.

**The Hidden Requirement:** If a background agent prints `[SYSTEM: HAAS_REQUEST]`, the platform's chat router must physically intercept that exact string, halt the Swarm, and programmatically trigger the Observer Node spawn (as defined in `IDENTITY.md`). If the platform just blindly dumps `[SYSTEM:...]` strings into the user UI without acting on them, the automation loop breaks entirely.

**Installed Sudarshan bridge handlers:** A fresh-agent installation now patches command hooks to:
- `/taskmanager` -> `openclaw_router_bridge.handle_taskmanager`
- `!status` -> `openclaw_router_bridge.handle_status`
- `!input` -> `openclaw_router_bridge.handle_input`

Platforms may bind these handlers natively or adapt them into an equivalent host-side router.

---

### 1.5 File System Access
The platform MUST grant sub-agents read/write access to the workspace directory,
including the ability to:
- Create files and directories
- Execute Python scripts (`python3 script.py`)
- Execute Node.js scripts (`node script.js`)
- Execute shell commands (`git`, `docker`, `npm`, `chmod`)

---

### 1.6 Shell Command Execution
Sub-agents MUST be able to run arbitrary shell commands in the workspace. This includes:
- `python3` (for `safe_edit.py`, `dag_validator.py`, `dag_subgraph.py`)
- `node` (for `search.js`)
- `git` (for shallow commits)
- `docker` / `docker-compose` (for SearXNG, ephemeral DBs)
- `npm` / `npx` (for `spectral-cli`, `kill-port`, dependency management)

---

## 2. Optional Platform Capabilities

### 2.1 Push Notifications
If the platform supports push notifications (e.g., WhatsApp, Slack, email), Sudarshan
will use them for:
- HaaS escalation alerts
- Hourly status updates
- Task completion reports

If unavailable, all notifications are emitted as `[SYSTEM: ...]` tags in chat.

### 2.2 Web Fetching
**Primitive:** `web_fetch(url) → content`

Used by the Research Engine to fetch external documentation after SearXNG returns URLs.
If unavailable, the Orchestrator must use `curl` or Node.js `fetch()` as a fallback.

> **⚠️ IMPORTANT:** `web_fetch` is ALLOWED. `web_search` is BANNED for all Swarm agents.

### 2.3 Web Search Replacement (CRITICAL)
**The platform's native `web_search` tool MUST be DENIED** for all spawned Swarm sub-agents.
Sudarshan replaces it with a self-hosted SearXNG instance via `node skills/os_search/search.js`.

**Why:** Native `web_search` (Brave, Perplexity, Gemini etc.) burns API credits, returns
inconsistent results across providers, and cannot be audited. SearXNG is free, self-hosted,
and fully under the operator's control.

**How to enforce on OpenClaw:**
```json
{
  "toolPolicy": { "deny": ["web_search"] }
}
```
Pass this in the spawn options for ALL sub-agents (Orchestrator, Grunts, Observer, PM, etc.).

**The replacement command:**
```bash
node skills/os_search/search.js "your query"
# Returns structured results from SearXNG on localhost:8080
```
Agents then use `web_fetch` on the returned external URLs to read documentation.

### 2.4 Self-Modification (Identity Patching)
**Primitive:** `patch_identity(content) → success`

Allows Sudarshan to auto-inject its kernel blocks into the platform's identity config
during installation. If unavailable, the agent operator must manually copy the
injection blocks from `IDENTITY.md`, `SOUL.md`, `USER.md`, and `HEARTBEAT.md`.

### 2.5 Installed Plugin Surface

The packaged overlay now ships these plugin schemas under `openclaw_plugins/`:
- `spawn_subagent.json`
- `kill_subagent.json`
- `list_subagents.json`
- `kill_all_subagents.json`
- `patch_identity.json`

The host platform is expected to register these or provide equivalent built-in primitives.

---

## 3. Compatibility Matrix

| Capability | Required? | Sudarshan Component | Fallback |
|---|---|---|---|
| Sub-agent spawning | ✅ REQUIRED | Swarm Orchestration | None — fatal |
| Sub-agent listing | ✅ REQUIRED | Concurrency Lock | None — fatal |
| Sub-agent killing | ✅ REQUIRED | Zombie Prune, Abort | None — fatal |
| Output monitoring | ✅ REQUIRED | System Intercepts | File-based polling |
| File system access | ✅ REQUIRED | All scripts | None — fatal |
| Shell execution | ✅ REQUIRED | All Python/Node tools | None — fatal |
| Push notifications | ⚠️ Optional | HaaS, Hourly Updates | Chat-based fallback |
| Web fetching | ⚠️ Optional | Research Engine | `curl` / `node fetch` |
| Self-modification | ⚠️ Optional | Auto-install | Manual patching |

---

## 4. Platform Validation

After implementing the required capabilities, platforms should run:
```bash
python3 verify_installation.py --workspace /path/to/sudarshan
```
This validates all files and dependencies but does NOT validate platform API
capabilities (since those are platform-internal). Platform vendors should
additionally test:
1. Can a spawned sub-agent read `SUDARSHAN.md` from the workspace?
2. Can a spawned sub-agent execute `python3 safe_edit.py --help`?
3. Can the Main Thread detect `[SYSTEM: RELAY_BATON]` in sub-agent output?
4. Can `kill_all_subagents()` terminate a running sub-agent within 5 seconds?
