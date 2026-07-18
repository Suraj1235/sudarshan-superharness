---
name: research-commander
description: >
  Systematic technology recon for Phase 0 research. Activate when beginning
  Phase 0 for any software build directive. Produces RESEARCH_MANIFEST.json.
  Secondary outputs: STRICT_CONSTRAINTS.json, RESEARCH_CACHE/ files.
---

## Steps

[RC1] For each technology in the Super Prompt stack, run:
  `node skills/os_search/search.js "{tech} latest stable version release notes {year}"`
  → Record in stack_matrix: version, any breaking changes in last 6 months
  STOP if version is end-of-life — flag in open_ambiguities immediately

[RC2] For each PAIR of technologies (e.g., Next.js + Prisma, Node + PostgreSQL), run:
  `node skills/os_search/search.js "{tech_a} {tech_b} integration known issues"`
  → web_fetch the top result URL (not localhost:8080)
  → Record incompatibilities in stack_matrix[tech_a].incompatibilities

[RC3] For each external 3rd-party API in the directive:
  `node skills/os_search/search.js "{service} API rate limits pricing tiers {year}"`
  → Extract: requests/minute, requests/day, cost per unit, auth method
  → Append to WORKSPACE_ROOT/STRICT_CONSTRAINTS.json as hard constraints
    (format: `{"service": "...", "constraints": {...}}`)

[RC4] Run deployment constraint scan:
  `node skills/os_search/search.js "{deployment_target} {primary_framework} known issues"`
  Examples: "Vercel Next.js 15 serverless limitations", "Railway Node.js memory limits"
  → Record in deployment_constraints[]

[RC5] Run anti-pattern scan for each major framework:
  `node skills/os_search/search.js "{framework} anti-patterns production pitfalls 2025"`
  → Record top 3 findings per framework in anti_patterns_found[]

[RC6] Derive env_manifest from stack (no searching needed):
  Any external service → requires at least one API key → add to env_manifest[]
  Mark all as provided: false until human confirms

[RC7] Record ALL sources with SRC-XXX IDs in RESEARCH_MANIFEST.json
  This is mandatory — the Judge Probe counts them for Gate 0 validation
  Run `python3 taskmanager.py --record-search` after each search query to track against limits

[RC8] MAP-REDUCE for large payloads (>5,000 tokens of raw findings):
  Chunk the remaining bulk research into topical markdown files inside WORKSPACE_ROOT/RESEARCH_CACHE/
  Naming convention: RESEARCH_CACHE/SRC-XXX-{topic}.md
  The Orchestrator reads these during execution instead of re-searching
  This replaces the old ChromaDB RAG pattern — file-system RAG is auditable by humans
