---
name: scope-validator
description: >
  Brutal scope reduction for Phase 0. Activate when the Orchestrator finishes
  research and before architecture begins. Produces SCOPE_MANIFEST.json and PRE_MORTEM.md.
---

## Steps

[SV1] Parse the Super Prompt and list EVERY feature mentioned as a bullet point.
  Be exhaustive — include implicit features (e.g., "user dashboard" implies auth)

[SV2] Classify each feature:
  CORE:          Must ship for the product to be usable. No CORE = no product.
  NICE_TO_HAVE:  Adds value but product works without it.
  OUT_OF_SCOPE:  Not mentioned in the directive — you inferred it. Cut immediately.

[SV3] Estimate DAG node count for CORE features only:
  - 1 simple CRUD endpoint = 1 node
  - Auth system = 3 nodes (setup, middleware, session handling)
  - Frontend page = 1-2 nodes per page
  - DB + migrations = 2 nodes per model cluster
  Total estimate → node_count_estimate

[SV4] SCOPE VIOLENCE RULE: If node_count_estimate > 15, FORCE a cut:
  - Identify the 80/20 split: which CORE features provide >80% of value?
  - Move the remaining CORE features to a "V2 backlog" — they become NICE_TO_HAVE
  - This is not optional — no DAG > 15 nodes for an initial build

[SV5] Output SCOPE_MANIFEST.json:
  `{ "core": [], "nice_to_have": [], "v2_backlog": [], "node_count_estimate": N }`
  Write to enterprise_state/SCOPE_MANIFEST.json

[SV6] Write PRE_MORTEM.md — PM Node alone is authorized to write this:
  This is the adversarial anti-anchoring document. Assume the build WILL fail.
  - List the Top 5 most likely failure modes (tech stack, integration, scope)
  - For each: probability, impact, and which node in the DAG would bear it
  - Flag scope creep traps: the 3 features the human will "definitely need"
  - Flag integration landmines: API contracts most likely to break during E2E
  Write to WORKSPACE_ROOT/PRE_MORTEM.md (not enterprise_state/)
