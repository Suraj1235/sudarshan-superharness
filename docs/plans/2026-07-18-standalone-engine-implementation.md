# Standalone Engine Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a zero-dependency standalone Sudarshan engine that estimates and executes resumable provider-neutral software builds from an idea, PRD, or technical specification.

**Architecture:** Preserve the existing deterministic state machine and add a small execution plane around it. Models emit validated JSON actions; stdlib Python executes confined tools, persists state after every step, enforces budgets, and retries transient provider failures.

**Tech Stack:** Python 3.9+ standard library, `unittest`/`pytest`, HTTP JSON APIs, TOML packaging metadata.

---

### Task 1: Explainable Build Estimator

**Files:**
- Create: `estimator.py`
- Create: `tests/test_estimator.py`

**Steps:**
1. Write failing tests for idea/file intake, low-likely-high ordering, deterministic output, pricing, and invalid input.
2. Run `python -m pytest tests/test_estimator.py -q` and confirm failures are caused by the missing module.
3. Implement immutable estimate inputs, explicit coefficients, scope-signal scoring, and JSON-serializable output.
4. Rerun the targeted tests and confirm they pass.

### Task 2: Provider Protocol And Resilient HTTP Adapter

**Files:**
- Create: `providers.py`
- Create: `tests/test_providers.py`

**Steps:**
1. Write failing tests using a local HTTP server for request shape, usage extraction, secret redaction, 429 classification, `Retry-After`, permanent authentication failures, and malformed responses.
2. Confirm the tests fail before implementation.
3. Implement `Provider`, `ModelResponse`, normalized provider exceptions, and `OpenAICompatibleProvider` using `urllib.request`.
4. Confirm all provider tests pass.

### Task 3: Sandboxed Engine Tools

**Files:**
- Create: `engine_tools.py`
- Create: `tests/test_engine_tools.py`

**Steps:**
1. Write failing tests for path traversal, atomic writes, bounded reads, command allowlisting, argument-array validation, timeout handling, and capped output.
2. Confirm the tests fail for missing behavior.
3. Implement the minimal confined tool executor with no shell interpolation.
4. Confirm targeted tests pass.

### Task 4: Durable Autonomous Loop

**Files:**
- Create: `autonomous_engine.py`
- Create: `tests/test_autonomous_engine.py`

**Steps:**
1. Write failing tests for JSON action parsing, checkpoint-after-every-step, resume, rate-limit backoff, budget stop, human-input pause, finish rejection when verification fails, and successful completion.
2. Run the tests and verify expected failures.
3. Implement versioned engine state/events, prompt assembly, action dispatch, retry policy, usage accounting, and completion gates.
4. Run targeted tests until green, then run estimator/provider/tool tests together.

### Task 5: Turnkey CLI And Packaging

**Files:**
- Create: `sudarshan_cli.py`
- Create: `pyproject.toml`
- Create: `tests/test_sudarshan_cli.py`
- Modify: `install_manifest.json`
- Modify: `verify_installation.py`

**Steps:**
1. Write failing CLI tests for `doctor`, `estimate`, dry-run `build`, provider validation, status, and resume.
2. Implement input-source exclusivity, environment-only secrets, config loading, command dispatch, and console entry point.
3. Add new release files to the manifest and verifier.
4. Confirm CLI tests and manifest tests pass.

### Task 6: End-To-End Scripted Build

**Files:**
- Create: `tests/test_standalone_e2e.py`
- Create: `examples/demo_spec.md`

**Steps:**
1. Write a scripted-provider integration test that creates source and test files, experiences a synthetic 429, resumes, runs verification, and emits a completion report.
2. Confirm the test initially fails.
3. Make only integration fixes required by the scenario.
4. Run the E2E test and inspect all generated state artifacts.

### Task 7: Public Release Surface

**Files:**
- Modify: `README.md`
- Modify: `INSTALL_SUDARSHAN.md`
- Modify: `PLATFORM_CONTRACT.md`
- Modify: `SUDARSHAN.md`
- Create: `SECURITY.md`
- Create: `CONTRIBUTING.md`
- Create: `.github/workflows/ci.yml`

**Steps:**
1. Document the true one-command journey, estimator semantics, supported provider contract, retry behavior, safety model, and limitations.
2. Add highly visual Mermaid architecture and lifecycle diagrams with copy-paste quickstarts.
3. Add contribution/security guidance and cross-platform CI.
4. Run doc parity and installation verification.

### Task 8: Release Verification And Publishing

**Steps:**
1. Run the complete Python suite with duration reporting.
2. Run installation verifier, package build/install smoke test, compile checks, secret scan, and scripted E2E build.
3. Inspect the final diff and release tree for generated artifacts and misleading claims.
4. Initialize Git, commit intentional release files, create a public GitHub repository, push `main`, and verify the remote README and metadata.
