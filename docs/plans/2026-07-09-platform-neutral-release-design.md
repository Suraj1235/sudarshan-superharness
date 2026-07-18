# Platform Neutral Release Design

Sudarshan is being released as a platform-neutral superharness rather than an OpenClaw-only overlay. The core remains the deterministic state machine: file-backed state, gates, DAGs, strike ledgers, budget checks, research manifests, and baton resume.

The OpenClaw integration stays as a compatibility adapter. New host runtimes integrate through `platform_harness.py`, `generic_router_bridge.py`, `PLATFORM_CONTRACT.md`, and `SUDARSHAN_HOST_CONTRACT.json`.

The release must be honest: Sudarshan is not magic and cannot guarantee flawless model output. Its novelty is giving powerful models a stricter operating environment so long-running builds can preserve state through context loss, interruption, retries, and verification pressure.
