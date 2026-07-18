---
name: global-cartographer
description: >
  Maintain the global semantic memory map of the system under construction.
  Activate at Phase 1 lock and remain running throughout Phase 2-4.
  Updates ARCHITECTURE_STATE.md on every Red Team GREEN LIGHT.
---

## Steps

[GC1] AT PHASE 1 LOCK — initial population:
  Read JIRA_DAG.json, UI_SPEC.json, openapi.yaml, schema.prisma (if exists)
  Populate ARCHITECTURE_STATE.md:
  - System block diagram (ASCII art): show all services and their connections
  - Component Registry: every DAG node → expected file path(s) → status: PENDING
  - Contract Surface: every openapi.yaml endpoint → consuming frontend page
  - Known Issues: empty initially

[GC2] ON EVERY RED TEAM GREEN LIGHT:
  Update Component Registry: node status PENDING → COMPLETE, add actual file paths
  If new files were created NOT in the DAG → flag as "unplanned" in Known Issues
  If a Grunt modified a contract (changed an API signature) → publish CONTRACT_MUTATION_EVENT

[GC3] CONTRACT MUTATION TRACKING:
  A CONTRACT_MUTATION represents a breaking change to an interface.
  When detected: write to BLACKBOARD_STATUS.json `{ "event": "CONTRACT_MUTATION", "affected": [...] }`
  The Orchestrator reads this and halts ONLY the squads consuming that contract.
  Other squads continue uninterrupted.

[GC4] ARCHITECTURAL DRIFT DETECTION:
  Compare the current file system against the original DAG plan every 3 completed nodes.
  Flag: files that exist but aren't in the plan, plan nodes that haven't started in expected order.
  Write summary to Known Issues with severity WARN.

[GC4.5] CONTEXT WINDOW PRESERVATION (Self-Truncation):
  ARCHITECTURE_STATE.md is injected into the Orchestrator's context on every relay-baton
  resume. If it grows unboundedly, the Orchestrator will hit token limits and die.
  This step is your immune system against context death.

  TRIGGER: Count the discrete bullet points / log entries under the "## Known Issues & Event Log"
  section. If this count exceeds 50 entries, execute the compaction procedure below.
  Do NOT use line counts or character counts as the trigger — count discrete entries only.

  PRESERVATION LOCK (IMMUTABLE — do NOT touch these):
    - The System Block Diagram (ASCII art)
    - The Component Registry (DAG node → file path → status mapping)
    - The Contract Surface (endpoint → consuming page mapping)
    These are live semantic maps. Summarizing or truncating them destroys the project.

  COMPACTION PROCEDURE:
    1. Read the oldest 40 entries from the Event Log.
    2. Synthesize them into a dense, comprehensive technical summary — NOT a sparse bullet list.
       The summary MUST retain: precise architectural decisions made, tools/libraries that were
       evaluated and discarded, key pivot points, and any resolved contract mutations.
       Target: exactly 5 detailed paragraphs that a new Orchestrator could read to fully
       reconstruct the project's architectural history up to that point.
    3. Replace the oldest 40 raw entries with a single "### Historical Summary (Compacted)" block
       containing the 5 paragraphs. The remaining 10+ recent entries stay untouched.
    4. Execute this replacement ONLY via `safe_edit.py`. Raw file overwrites are BANNED to
       ensure atomic writes and prevent corruption if generation crashes mid-stream.

  PLATFORM OVERRIDE: If the underlying agent framework (e.g., OpenClaw) has native
  auto-compaction or memory summarization features, they MUST be disabled for the Observer
  Node's session. SUDARSHAN manages its own state lifecycle — external compaction will
  aggressively delete semantic state and cause architectural amnesia.

[GC5] ON HAAS INTERCEPT — diagnostic context:
  When the Observer intercepts a HAAS_REQUEST, read ARCHITECTURE_STATE.md to provide
  the human (or resolving agent) with: system state, what was in progress, what failed,
  and the most recent architectural context.
  This is the key capability — without it, human-in-the-loop is uninformed.
