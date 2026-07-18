---
name: ui-scout
description: >
  Evidence-based UI/UX design research and structured Delta-Debate for Phase 1.
  Activate when the Creative Director begins Phase 1 design work.
  Produces UI_SPEC.json through a 5-round adversarial debate with the PM Node.
  Delta-Debate produces: DELTA_CRITIQUE_*.json, UI_SPEC_V2.json, DELTA_RULING.json.
---

## Part A: Design Research (Before the Debate)

[US1] PRECEDENT RESEARCH — find 3 production applications with similar UX goals:
  Query pattern: `"{app_type} {industry} best UI design examples 2025"`
  Example for a SaaS dashboard: "SaaS analytics dashboard UI design Dribbble 2025"
  CRITICAL STEP: Synthesize the **Aesthetic Vector**:
  - Analyze the 3 precedents and generate an Aesthetic Vector (e.g., `["Data-Dense", "Monochrome", "High-Contrast"]` for Enterprise, or `["Airy", "Playful", "Rounded"]` for Consumer).
  - IF the User provided explicit UI instructions or references in the Super Prompt directive, you MUST prioritize their vision over the precedents when creating the Aesthetic Vector.
  → Write UI_REFERENCES.json with annotated findings and the synthesized Aesthetic Vector.

[US2] TREND VALIDATION — verify the reference aesthetic is current:
  For each major UI choice from precedents:
  - `node skills/os_search/search.js "{framework} best component library bundle size 2025"`
  - Evaluate: bundle size, weekly npm downloads, TypeScript support, accessibility score
  Selection criteria (in order of priority):
    1. Actively maintained (last release < 60 days)
    2. TypeScript-first
    3. WCAG AA accessible out of the box
    4. Bundle size < 50KB gzipped for core
  Shortlist: Evaluate `shadcn/ui`, `Radix UI`, `Mantine`, `Chakra UI v3`, `HeroUI`. Select the ONE that BEST aligns with your Aesthetic Vector.

[US3] ANIMATION STRATEGY — define interaction language:
  Evaluate framer-motion vs. GSAP vs. CSS transitions based on complexity:
  - Simple hover/fade: CSS transitions (zero bundle cost)
  - Page transitions, component reveals: framer-motion (~45KB)
  - Complex sequences, scroll-driven: GSAP (~100KB, worth it for premium feel)
  Decision → animation_library in UI_SPEC_DRAFT.json

[US4] DESIGN SYSTEM CONSTRUCTION — build the token set:
  COLOR SYSTEM:
  - Choose a primary hue and build a full scale (50→950) using HSL
  - Choose semantic roles: primary, secondary, destructive, muted, background, surface, border
  - Verify 4.5:1 contrast ratio for text on background (WCAG AA)
  - Dark mode variant required: documented as CSS custom properties

  TYPOGRAPHY SYSTEM:
  - Font pair: Display font (headers) + Body font (paragraph text)
  - Query: `node skills/os_search/search.js "best Google Fonts pairing {aesthetic_vector} 2025"`
  - Define scale dynamically based on the Aesthetic Vector (e.g., dense vectors require smaller baselines like 12px, airy vectors allow 16px+ baselines).

  SPACING SYSTEM:
  - Base unit: 4px or 8px (never mix)
  - Multiply the base unit dynamically based on the Aesthetic Vector to generate restrictive (data-dense) or expansive (airy) scales.

  COMPONENT STATES:
  For EVERY interactive component: define default, hover, focus, active, disabled, error states.

[US5] COMPONENT INVENTORY — list every distinct component needed:
  Walk through each page in SCOPE_MANIFEST.json:
  For each page → list all visual elements → group into reusable components
  For each component: name, which pages use it, props/variants, interactive states
  Classify as: LIBRARY (from component_library), CUSTOM (need to build)
  MINIMIZE custom components — each custom = 1 DAG node for the Frontend Squad

[US6] MOTION DESIGN SPECIFICATION — define the interaction grammar:
  - Page entry: fade-in + slide-up 20px, 300ms ease-out
  - List item stagger: 50ms delay between items, max 5 items animated
  - Button press: scale(0.97), 100ms
  - Modal enter: scale(0.95)→scale(1), opacity 0→1, 200ms
  - Success state: checkmark draw animation, 400ms
  Document these as animation_tokens in UI_SPEC_DRAFT.json

## Part B: Delta-Debate Protocol (5 Rounds with PM Node)

> The PM Node reads UI_SPEC_DRAFT.json and responds with DELTA_CRITIQUE_1.json.
> The Creative Director revises, PM critiques again — up to 5 rounds.
> SHORT-CIRCUIT: If PM issues ruling="ACCEPT" in any critique, the debate ends immediately.

### ROUND 1 (Creative Director opens)

[US7] Output UI_SPEC_DRAFT.json (matching the formal schema in enterprise_state/UI_SPEC.json):
  This is the Creative Director's opening proposal.
  Save as WORKSPACE_ROOT/DELTA_CRITIQUE_1.json by creating a critique file with:
  `{ "round": 1, "role": "creative_director", "verdict": "PROPOSAL",
    "content_summary": "...", "issues_flagged": [], "timestamp": "..." }`
  This is the ROUND 1 OPENING. Now await PM Node's DELTA_CRITIQUE_1.json response.

### PM Node Response (DELTA_CRITIQUE_1.json)

> PM Node reads UI_SPEC_DRAFT.json and writes DELTA_CRITIQUE_1.json:
> `{ "round": 1, "role": "pm_node", "verdict": "ACCEPT" | "REVISIONS_REQUIRED" | "REJECT",
>   "issues": [{ "section": "...", "finding": "...", "severity": "BLOCKER|MAJOR|MINOR" }], ... }`
> - If verdict = "ACCEPT" → SHORT-CIRCUIT. Debate ends. Proceed to DELTA_RULING.
> - If verdict = "REVISIONS_REQUIRED" → Round 2.
> - If verdict = "REJECT" → Escalate to Orchestrator.

### ROUND 2 (Creative Director revises)

[US8] Read DELTA_CRITIQUE_1.json. Revise UI_SPEC_DRAFT.json to address every BLOCKER and MAJOR finding.
  Save revised version as WORKSPACE_ROOT/UI_SPEC_V2.json.
  Then write DELTA_CRITIQUE_2.json (your response):
  `{ "round": 2, "role": "creative_director", "verdict": "REVISIONS_ADDRESSED",
>   "changes": [{ "original_issue": "...", "how_addressed": "..." }], "timestamp": "..." }`

### PM Node Response (DELTA_CRITIQUE_2.json)

> PM Node reads UI_SPEC_V2.json and responds.
> - If verdict = "ACCEPT" → SHORT-CIRCUIT. Proceed to DELTA_RULING.
> - If verdict = "REVISIONS_REQUIRED" → Round 3.

### ROUNDS 3–5

Repeat the revise-and-critique cycle:
- [US9] Creative Director addresses remaining issues → UI_SPEC_V3.json → DELTA_CRITIQUE_3.json
- [US10] PM responds → DELTA_CRITIQUE_3.json response
- [US11] Round 4: UI_SPEC_V4.json → DELTA_CRITIQUE_4.json → PM response
- [US12] Round 5: UI_SPEC_V5.json → DELTA_CRITIQUE_5.json → PM response

If PM still has BLOCKER findings after Round 5:
- Write DELTA_RULING.json with verdict="ESCALATE_TO_ORCHESTRATOR"
- Orchestrator resolves the dispute and sets the final UI direction

### DELTA_RULING (Final)

[US13] PM Node issues DELTA_RULING.json:
  `{ "verdict": "ACCEPT" | "ACCEPT_WITH_REVISIONS" | "ESCALATE_TO_ORCHESTRATOR",
    "final_spec_file": "UI_SPEC_DRAFT.json" | "UI_SPEC_V2.json" | "UI_SPEC_V3.json" | "UI_SPEC_V4.json" | "UI_SPEC_V5.json",
    "debate_rounds_completed": 1..5,
    "binding_modifications": [{ "section": "...", "required_change": "..." }],
    "escalation_note": "..." // only if ESCALATE_TO_ORCHESTRATOR
  }`

[US14] Copy the final spec to enterprise_state/UI_SPEC.json:
  The DELTA_RULING's final_spec_file becomes the canonical UI_SPEC.json.
  The winning file may be UI_SPEC_DRAFT.json (short-circuit in Round 1) or one of V2-V5.
  If ESCALATE_TO_ORCHESTRATOR, Orchestrator determines the final file after dispute resolution.
  Run `python3 taskmanager.py --check-gate-ui-spec` to validate the final spec before proceeding.
