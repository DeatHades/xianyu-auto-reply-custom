"""Strict helpers for AI-assisted keyword rule selection."""

from __future__ import annotations

import json
import math
from typing import Any, Iterable


SEMANTIC_KEYWORD_CONFIDENCE_THRESHOLD = 0.90
SEMANTIC_KEYWORD_MAX_CANDIDATES = 100


def parse_semantic_keyword_selection(
    raw_output: Any,
    candidate_ids: Iterable[int],
    threshold: float = SEMANTIC_KEYWORD_CONFIDENCE_THRESHOLD,
) -> tuple[int | None, float | None, str]:
    """Return only a validated candidate ID; model text is never a reply."""

    if not isinstance(raw_output, str):
        return None, None, "invalid_result"

    value = raw_output.strip()
    if not value.startswith("{") or not value.endswith("}"):
        return None, None, "invalid_result"

    try:
        payload = json.loads(value)
    except (TypeError, ValueError):
        return None, None, "invalid_result"

    if not isinstance(payload, dict):
        return None, None, "invalid_result"
    if not set(payload).issubset({"matched", "rule_id", "confidence"}):
        return None, None, "invalid_result"
    if type(payload.get("matched")) is not bool:  # bool must not be coerced
        return None, None, "invalid_result"
    if payload["matched"] is False:
        return None, None, "no_match"

    rule_id = payload.get("rule_id")
    confidence = payload.get("confidence")
    if isinstance(rule_id, bool) or not isinstance(rule_id, int):
        return None, None, "invalid_result"
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        return None, None, "invalid_result"

    normalized_confidence = float(confidence)
    if not math.isfinite(normalized_confidence) or not 0.0 <= normalized_confidence <= 1.0:
        return None, None, "invalid_result"
    if rule_id not in set(candidate_ids):
        return None, normalized_confidence, "invalid_result"
    if normalized_confidence < threshold:
        return None, normalized_confidence, "low_confidence"
    return rule_id, normalized_confidence, "matched"
