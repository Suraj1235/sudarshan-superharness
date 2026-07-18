---
name: dag-architect
description: >
  Mathematically sound DAG construction for Phase 1. Activate when building
  the JIRA_DAG.json. Produces JIRA_DAG.json (enterprise_state/), DAG_RATIONALE.md,
  and openapi.yaml scaffold (workspace root).
---

## Steps

[DA1] Start from SCOPE_MANIFEST.json → CORE features only.
  Each feature → expand into atomic tasks.
  ATOMICITY RULE: Each node = completable by one Grunt in a single session.
  If a task requires > 3 files to be created or > 200 lines of new code → split it.

[DA2] For dependencies, apply the STRICT DEFINITION:
  "Node B depends on Node A" = B literally CANNOT START without A's output files existing.
  NOT: "B is logically related to A" — this is false dependency (costs parallelism).
  NOT: "We should do A before B for safety" — this is caution, not dependency.

[DA3] PARALLELISM CHECK: For every pair of nodes (A, B) that share no dependency:
  Ask: "Can a Grunt start B today while another Grunt works on A?"
  If yes → they should be parallel. Forced sequencing = token waste.

[DA4] TOKEN COST ESTIMATION:
  For each node, estimate: input context (subgraph tokens) + expected output tokens.
  Flag any node where input_tokens > 40,000 as "OVERSIZED — needs sub-splitting."
  Oversized nodes cause context overflow when Grunts receive their subgraph.

[DA5] Run validation BEFORE presenting to PM:
  `python3 dag_validator.py enterprise_state/JIRA_DAG.json`
  If circular dependency → fix it. PM should never see a broken DAG.

[DA6] Write JIRA_DAG.json:
  Output the complete DAG to enterprise_state/JIRA_DAG.json
  Format: `{ "nodes": [{ "id", "title", "squad", "status": "PENDING", "priority",
    "dependencies": [], "assigned_to": null, "description" }, ...],
    "metadata": { "project": "...", "total_nodes": N } }`
  Assign squads (backend, frontend, integration, devops) based on node type.

[DA7] Write DAG_RATIONALE.md:
  For each dependency edge, one sentence explaining WHY it's a true dependency.
  Format: `## Edge: [Node A] → [Node B]: [one-sentence justification]`
  This document is what the PM audits in Gate 3.
  Write to WORKSPACE_ROOT/DAG_RATIONALE.md

[DA8] Scaffold openapi.yaml if backend exists:
  If any node has squad=backend, ensure WORKSPACE_ROOT/openapi.yaml exists
  (created as empty scaffold by taskmanager.py --init).
  PM Node fills in the paths and schemas during Gate 4.
