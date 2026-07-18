---
name: adversarial-auditor
description: >
  Adversarial code audit for Phase 2-3. Activate when reviewing completed Grunt work.
  Must produce either GREEN_LIGHT or REJECTION.md with specific, actionable findings.
---

## Steps

[RT1] READ BEFORE ATTACKING:
  Read the Grunt's assigned DAG node description.
  Read the 1-degree subgraph context the Grunt received.
  Read EVERY file the Grunt created or modified (use standard platform tools like `cat` or `read_file`. Do NOT use `safe_edit.py` to read).
  DO NOT start auditing until you understand the intended behavior.

[RT2] OWASP LLM TOP 10 SCAN (mandatory, in order):
  For each file written by the Grunt:

  LLM01 — Prompt injection surfaces: any user input passed to string interpolation?
  LLM02 — Sensitive data exposure: any API keys, tokens, or PII in logs/responses?
  LLM05 — Output handling: any LLM outputs rendered without sanitization?
  LLM06 — Excessive agency: does this component do MORE than its DAG node description?
  General: hardcoded credentials — INSTANT FAIL, no exceptions

[RT3] CLASSICAL SECURITY SCAN:
  SQL injection: any raw string interpolation in DB queries? (must use parameterized)
  XSS: any user input rendered as innerHTML? (must use textContent or sanitize)
  CSRF: any state-mutating endpoint without CSRF token?
  Auth bypass: any endpoint that should require auth but doesn't?
  Race conditions: any shared state mutated by concurrent operations without locking?

[RT4] DEBUGGING EXECUTION — actually run the code:
  For Python: `python3 -c "import ast; ast.parse(open('file.py').read())"`
  For JavaScript: `node --check [grunt_file]` (syntax validation)
  For TypeScript: `npx tsc --noEmit [grunt_file]` (type check without building)
  Run the Grunt's own test file if it exists: `python3 -m pytest [test_file] -v`
  Record: which tests pass, which fail, error messages verbatim

[RT5] BEHAVIORAL TESTING — write a proof-of-concept for any found vulnerability:
  For each security finding: write the MINIMAL code that demonstrates the exploit.
  Example for SQL injection: show the exact input string that would extract data.
  This is NOT optional. The Staff Engineer needs a reproducible case, not a description.
  Write exploits to RED_TEAM_POC.md (never to actual source files)

[RT6] UNHANDLED EDGE CASES:
  For each function: what happens when the input is null/undefined/empty?
  For each async operation: what happens if the promise rejects?
  For each HTTP call: what happens if the external service returns 429 or 503?
  For each DB operation: what happens if the connection times out?
  If any of these produce an unhandled exception → document as FAIL

[RT7] PATCH VERIFICATION (when reviewing a fix after previous rejection):
  Re-run RT2-RT6 on ONLY the changed lines.
  Verify the specific vulnerability from the previous REJECTION.md is no longer reproducible.
  Do NOT issue GREEN_LIGHT if the fix introduces a new issue (even minor).

[RT8] SKILL COMPLIANCE CHECK (NEW in V16.9):
  Verify the producing agent followed their injected skill:
  - Does the agent's output reference skill step IDs?
  - Does the artifact match the required schema?
  If the agent skipped skill steps → raise REJECTION with "SKILL_NONCOMPLIANCE"

[RT9] VERDICT:
  GREEN_LIGHT: All RT2-RT8 checks PASS. Execute `safe_edit.py --greenlight`.
  REJECTION.md: List every finding by step ID (e.g., RT3-SQL, RT6-ASYNC).
    For each: severity (CRITICAL/HIGH/MEDIUM), exact file + line number, description,
    proof-of-concept (from RT5), and suggested fix direction (NOT the full fix —
    the Grunt must implement it to maintain ownership).

[RT10] WRITE AUTOPSY.md if escalating to Staff Engineer:
  If GREEN_LIGHT cannot be issued after 3 Grunt patch attempts, write AUTOPSY.md:
  - Check if AUTOPSY.md already exists. If yes: append under a new "## Escalation Round N" header.
    This preserves full failure history across repeated escalations.
  - Content for each escalation:
    - Grunt ID, DAG Node, Red Team Finding, Failure Type (OWASP/Logic/Concurrency/Memory/Edge Case)
    - Root cause: which assumption was wrong?
    - Proof-of-concept (from RT5) — reproducible by Staff Engineer
    - What fixes were attempted and their results
    - Staff Engineer resolution plan (approach, NOT the fix itself)
    - Any CONTRACT_MUTATION_EVENTs this fix introduces (for Orchestrator propagation)
  Write to WORKSPACE_ROOT/AUTOPSY.md (Staff Engineer reads this before acting)
