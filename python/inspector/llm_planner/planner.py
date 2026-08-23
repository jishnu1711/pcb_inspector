"""
llm_planner/planner.py
-----------------------
Uses the LLM to re-order TestCases in a TestPattern by priority.

Falls back to a deterministic sort (isolation < diode < continuity) if the
LLM is unavailable or returns an invalid response.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Optional

from inspector.model.types import TestPattern, TestCase
from inspector.llm_planner.llm_client import LLMClient
from inspector.llm_planner.prompts import PLANNER_SYSTEM, PLANNER_USER_TEMPLATE

logger = logging.getLogger(__name__)

# Deterministic priority order used as fallback
_FALLBACK_ORDER = {
    "isolation":     1,
    "diode_forward": 2,
    "diode_reverse": 3,
    "continuity":    4,
}


def _fallback_sort(test_cases: list[TestCase]) -> list[TestCase]:
    """Sort by test_type group, then by existing priority field, then by id."""
    return sorted(
        test_cases,
        key=lambda tc: (
            _FALLBACK_ORDER.get(tc.test_type, 9),
            tc.priority,
            tc.id,
        ),
    )


def _extract_id_list(text: str) -> Optional[list[str]]:
    """Extract a JSON array of strings from LLM output (strips markdown fences)."""
    text = re.sub(r"```(?:json)?", "", text).strip()
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if not match:
        return None
    try:
        result = json.loads(match.group())
        if isinstance(result, list) and all(isinstance(x, str) for x in result):
            return result
    except json.JSONDecodeError:
        pass
    return None


def plan_test_order(
    pattern: TestPattern,
    llm_client: LLMClient,
) -> TestPattern:
    """
    Re-order pattern.test_cases using LLM.
    Updates each TestCase.priority to reflect final position.
    Mutates and returns the same TestPattern object.
    """
    if not pattern.test_cases:
        return pattern

    # Summarise tests for the LLM (keep payload small — no coordinates)
    summary = [
        {
            "id": tc.id,
            "test_type": tc.test_type,
            "net_a": tc.net_a,
            "net_b": tc.net_b,
            "component_ref": tc.component_ref,
            "rationale": tc.rationale,
        }
        for tc in pattern.test_cases
    ]

    user_prompt = PLANNER_USER_TEMPLATE.format(
        test_cases_json=json.dumps(summary, indent=2)
    )

    raw = llm_client.complete(PLANNER_SYSTEM, user_prompt)
    ordered_ids: Optional[list[str]] = None

    if raw is not None:
        ordered_ids = _extract_id_list(raw)
        if ordered_ids is None:
            logger.warning("Planner LLM returned unparseable response — using fallback")

    if ordered_ids is None:
        logger.info("Using deterministic fallback sort for test ordering")
        ordered = _fallback_sort(pattern.test_cases)
    else:
        # Build id → TestCase map; place any IDs missing from LLM response at end
        id_map = {tc.id: tc for tc in pattern.test_cases}
        ordered = []
        seen: set[str] = set()
        for tid in ordered_ids:
            if tid in id_map and tid not in seen:
                ordered.append(id_map[tid])
                seen.add(tid)
        # Append any cases the LLM omitted
        for tc in pattern.test_cases:
            if tc.id not in seen:
                logger.debug("LLM omitted test %s — appending at end", tc.id)
                ordered.append(tc)
        logger.info("Planner: LLM ordered %d tests", len(ordered))

    # Update priority field to reflect execution order (1-based)
    for i, tc in enumerate(ordered, start=1):
        tc.priority = i

    pattern.test_cases = ordered
    return pattern
