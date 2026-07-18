#!/usr/bin/env python3
"""Explainable pre-build token, cost, and elapsed-time estimates."""

from __future__ import annotations

import hashlib
import math
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple


@dataclass(frozen=True)
class ProjectBrief:
    text: str
    source_kind: str
    source_name: str
    sha256: str


_CAPABILITY_PATTERNS: Dict[str, Tuple[str, int]] = {
    "frontend": (r"\b(ui|ux|frontend|react|next(?:\.js)?|vue|svelte|dashboard|website|page)\b", 2),
    "backend": (r"\b(api|backend|server|endpoint|rest|graphql|microservice)\b", 3),
    "database": (r"\b(database|postgres(?:ql)?|mysql|sqlite|mongo(?:db)?|redis|storage|schema)\b", 2),
    "authentication": (r"\b(auth(?:entication|orization)?|oauth|log[ -]?in|sign[ -]?in|sso|rbac|permissions?|jwt|security)\b", 2),
    "payments": (r"\b(payment|billing|stripe|checkout|subscription|invoice)\b", 2),
    "realtime": (r"\b(realtime|real-time|websocket|streaming|notification|chat)\b", 2),
    "ai": (r"\b(ai|llm|model|embedding|rag|agent|inference)\b", 3),
    "mobile": (r"\b(mobile|ios|android|react native|flutter)\b", 3),
    "integrations": (r"\b(webhooks?|third-party|external api|service integration|sync(?:hronization)?)\b", 2),
    "deployment": (r"\b(deploy(?:ment)?|docker|kubernetes|ci/?cd|continuous integration|continuous delivery|release pipeline|pipeline|cloud|infrastructure)\b", 2),
    "testing": (r"\b(tests?|testing|unit tests?|integration tests?|e2e|end-to-end|playwright|quality|verification|qa)\b", 2),
}


def load_project_brief(
    *,
    idea: Optional[str] = None,
    prd_path: Optional[str] = None,
    spec_path: Optional[str] = None,
) -> ProjectBrief:
    """Load exactly one user input without changing or summarizing it."""
    supplied = [("idea", idea), ("prd", prd_path), ("spec", spec_path)]
    selected = [(kind, value) for kind, value in supplied if value is not None]
    if len(selected) != 1:
        raise ValueError("provide exactly one of idea, prd_path, or spec_path")

    source_kind, value = selected[0]
    if source_kind == "idea":
        text = str(value)
        source_name = "inline idea"
    else:
        path = Path(os.path.abspath(str(value)))
        if not path.is_file():
            raise ValueError(f"{source_kind} file does not exist: {path}")
        text = path.read_text(encoding="utf-8")
        source_name = path.name

    text = text.strip()
    if not text:
        raise ValueError("project brief is empty")
    return ProjectBrief(
        text=text,
        source_kind=source_kind,
        source_name=source_name,
        sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
    )


def _range_int(likely: int, low_factor: float, high_factor: float) -> Dict[str, int]:
    return {
        "low": max(1, int(round(likely * low_factor))),
        "likely": max(1, int(likely)),
        "high": max(1, int(round(likely * high_factor))),
    }


def _range_cost(
    input_range: Dict[str, int],
    output_range: Dict[str, int],
    input_price: float,
    output_price: float,
) -> Dict[str, float]:
    return {
        key: round(
            (input_range[key] * input_price + output_range[key] * output_price) / 1_000_000,
            4,
        )
        for key in ("low", "likely", "high")
    }


def estimate_build(
    brief: ProjectBrief,
    *,
    model: str = "unspecified",
    input_price_per_million: float = 0.0,
    output_price_per_million: float = 0.0,
    concurrency: int = 1,
) -> Dict[str, object]:
    """Return an auditable range estimate rather than a false point prediction."""
    if any(
        not math.isfinite(float(value)) or value < 0
        for value in (input_price_per_million, output_price_per_million)
    ):
        raise ValueError("pricing values must be non-negative")
    if concurrency < 1:
        raise ValueError("concurrency must be at least one")
    if not isinstance(brief, ProjectBrief):
        raise TypeError("brief must be a ProjectBrief")

    normalized = brief.text.lower()
    words = re.findall(r"\b[\w'-]+\b", brief.text)
    bullet_count = sum(
        1 for line in brief.text.splitlines() if re.match(r"^\s*(?:[-*]|\d+[.)])\s+", line)
    )
    detected = []
    capability_units = 0
    for name, (pattern, weight) in _CAPABILITY_PATTERNS.items():
        if re.search(pattern, normalized, flags=re.IGNORECASE):
            detected.append(name)
            capability_units += weight

    document_units = max(1, math.ceil(len(words) / 120))
    requirement_units = min(12, bullet_count)
    work_units = 3 + document_units + requirement_units + capability_units

    likely_turns = 8 + work_units * 4
    context_tokens_per_turn = min(24_000, 4_500 + len(words) * 5 + len(detected) * 450)
    output_tokens_per_turn = 1_800
    likely_input = likely_turns * context_tokens_per_turn
    likely_output = likely_turns * output_tokens_per_turn

    input_range = _range_int(likely_input, 0.55, 1.9)
    output_range = _range_int(likely_output, 0.55, 1.9)
    total_range = {
        key: input_range[key] + output_range[key] for key in ("low", "likely", "high")
    }
    cost_range = _range_cost(
        input_range,
        output_range,
        float(input_price_per_million),
        float(output_price_per_million),
    )

    minutes_per_turn = 1.35
    likely_minutes = max(1, math.ceil(likely_turns * minutes_per_turn / concurrency))
    elapsed_range = _range_int(likely_minutes, 0.65, 2.6)

    confidence_reasons = []
    if len(words) < 40:
        confidence_reasons.append("brief has fewer than 40 words")
    if len(detected) < 3:
        confidence_reasons.append("few stack or capability signals were detected")
    if bullet_count < 3:
        confidence_reasons.append("few independently stated requirements were detected")

    if len(words) < 40 or len(detected) < 2:
        confidence = "low"
    elif len(words) < 250 or len(detected) < 5 or bullet_count < 3:
        confidence = "medium"
    else:
        confidence = "high"
    if not confidence_reasons:
        confidence_reasons.append("detailed structured brief with multiple capability signals")

    return {
        "schema_version": 1,
        "brief": {
            "source_kind": brief.source_kind,
            "source_name": brief.source_name,
            "sha256": brief.sha256,
            "word_count": len(words),
        },
        "model": model or "unspecified",
        "currency": "USD",
        "confidence": confidence,
        "confidence_reasons": confidence_reasons,
        "scope": {
            "work_units": work_units,
            "detected_capabilities": detected,
            "requirement_lines": bullet_count,
            "estimated_model_turns": likely_turns,
        },
        "ranges": {
            "input_tokens": input_range,
            "output_tokens": output_range,
            "total_tokens": total_range,
            "cost_usd": cost_range,
            "elapsed_minutes": elapsed_range,
        },
        "pricing": {
            "input_per_million": float(input_price_per_million),
            "output_per_million": float(output_price_per_million),
        },
        "assumptions": {
            "concurrency": concurrency,
            "excludes_human_wait_time": True,
            "includes_retry_allowance_in_high_range": True,
            "coefficients": {
                "base_work_units": 3,
                "words_per_document_unit": 120,
                "turns_per_work_unit": 4,
                "base_turns": 8,
                "context_tokens_per_turn": context_tokens_per_turn,
                "output_tokens_per_turn": output_tokens_per_turn,
                "minutes_per_turn": minutes_per_turn,
                "low_factor": 0.55,
                "high_token_factor": 1.9,
                "high_time_factor": 2.6,
            },
        },
        "disclaimer": (
            "Estimate only. Actual usage depends on model behavior, repository size, failures, "
            "verification depth, provider latency, and human decisions."
        ),
    }


__all__ = ["ProjectBrief", "estimate_build", "load_project_brief"]
