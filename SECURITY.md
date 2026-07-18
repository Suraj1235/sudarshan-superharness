# Security Policy

## Supported Versions

Sudarshan is currently alpha software. Security fixes are applied to the latest
commit on `main`; older snapshots are not maintained as separate release lines.

## Reporting A Vulnerability

Please do not disclose suspected vulnerabilities in a public issue. Use
[GitHub private vulnerability reporting](https://github.com/Suraj1235/sudarshan-superharness/security/advisories/new)
and include:

- the affected component and version or commit
- a minimal reproduction
- the security impact
- any known workaround

You should receive an acknowledgement within seven days. A fix timeline depends on
severity, reproducibility, and maintainer availability. Coordinated disclosure is
preferred.

## Security Boundary

Sudarshan treats model output as untrusted, confines file tools to the selected
workspace, validates one JSON action at a time, redacts sensitive environment
variables from model-requested subprocesses, and requires explicit consent before
host commands can run.

Host commands execute with the invoking user's operating-system privileges and are
not sandboxed by Sudarshan. Run untrusted autonomous builds in a disposable VM,
container, or dedicated low-privilege account. Do not rely on generated code passing
tests as evidence that it is secure or production-ready.

API keys are expected in environment variables. A report that includes a real key or
token should be revoked before submission.
