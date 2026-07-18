---
name: architecture-auditor
description: >
  Adversarial architecture audit for Phase 1 Gate 3. Activate when auditing
  the Orchestrator's EXECUTION_PLAN.md and JIRA_DAG.json. Produces PM_AUDIT_REPORT.json.
---

## Steps

[AA1] DEPENDENCY HEALTH AUDIT:
  For every npm/pip/external package in the plan:
  - `node skills/os_search/search.js "{package}@{version} CVE vulnerability 2025"`
  - `node skills/os_search/search.js "{package} last commit date maintained"`
  FAIL if: any critical CVE unaddressed, or package has no commit in 90+ days

[AA2] SCALABILITY AUDIT against the 100k-user Pre-Mortem:
  - Identify any endpoint that queries without pagination
  - Identify any DB query that could produce N+1 (e.g., loop + findMany inside)
  - Identify any missing index on a foreign key or frequently-filtered column
  WARN if any found. FAIL if > 3 unfixed warnings.

[AA3] OWASP LLM + AGENT SECURITY AUDIT (from OWASP Top 10 2025):
  NOTE: In Phase 1, this audit targets the EXECUTION_PLAN and architecture documents,
  NOT source code (which doesn't exist yet). Verify the plan explicitly mandates env vars
  for all secrets. Code-level credential scanning is deferred to Red Team (RT2-RT3) in Phase 2.
  Check for these OWASP risks in the architecture plan:
  - LLM01 (Prompt Injection): Any user-controlled input passed to LLM without sanitization?
  - LLM02 (Sensitive Data): Any API keys or PII in logs, error messages, or response bodies?
  - LLM06 (Excessive Agency): Does any component have more permissions than its task requires?
  - General: Are auth tokens hardcoded anywhere in the plan? (instant FAIL)
  - General: Are environment variables used for ALL secrets? (must be YES to pass)

[AA4] CONTRACT COMPLETENESS AUDIT for openapi.yaml:
  - Every endpoint must define: 200 response schema, 400 response schema, 500 response schema
  - List endpoints must have: limit, offset or cursor pagination parameters
  - POST endpoints must have: request body schema with required fields marked
  FAIL if any endpoint is missing these

[AA5] DEPLOYMENT REALITY AUDIT:
  Cross-reference plan against deployment_constraints[] in RESEARCH_MANIFEST.json
  Examples:
  - If deploying to Vercel: flag any use of fs.writeFile (forbidden — read-only filesystem)
  - If deploying to Vercel: flag any WebSocket server (not supported on serverless)
  - If deploying to Railway: check memory limits vs. expected RAM footprint
  FAIL if any constraint is violated in the architecture

[AA6] Output PM_AUDIT_REPORT.json:
  Each step AA1-AA5: `{ "result": "PASS|WARN|FAIL", "evidence": "...", "source": "..." }`
  Overall verdict: "APPROVE" (all PASS/WARN) | "REJECT" (any FAIL)
  REJECT = Gate 3 rejection → log in STRIKE_LEDGER.json
  Write to enterprise_state/PM_AUDIT_REPORT.json
