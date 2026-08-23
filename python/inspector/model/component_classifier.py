"""
model/component_classifier.py
------------------------------
For each RawComponent, sends ONE LLM call and returns classification info
used to populate Component.component_type, applicable_tests, test_parameters,
and pin_function on every Pin.

Confidence gating:
  high   → use all applicable_tests, thresholds as-is
  medium → use all applicable_tests, widen thresholds 20%
  low    → continuity only, flagged in report

Fallback (LLM unavailable or bad JSON):
  component_type = "unknown"
  applicable_tests = ["continuity"]
  confidence = "low"
"""

from __future__ import annotations

import json
import logging
import re
from typing import Optional

from inspector.parser.kicad_sch_parser import RawComponent
from inspector.llm_planner.llm_client import LLMClient

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompt template
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are an electronics component classifier for a PCB testing system.
Given a component's reference, value, library symbol, and pin list, you must
return ONLY a valid JSON object — no prose, no markdown fences, no explanation.

The JSON must have exactly these keys:
{
  "component_type": "<diode|led|resistor|capacitor|ic|connector|switch|unknown>",
  "applicable_tests": ["<continuity|isolation|diode_forward|diode_reverse>"],
  "test_parameters": {},
  "pin_roles": {"<pin_number>": "<anode|cathode|input|output|gnd|vcc|passive>"},
  "confidence": "<high|medium|low>",
  "reasoning": "<one sentence>"
}

Rules:
- component_type: choose the single best match
- applicable_tests: list only tests that make physical sense for this component
- test_parameters for diodes/LEDs: include vf_min_v and vf_max_v
- test_parameters for resistors: include resistance_ohm if value is parseable
- test_parameters for capacitors: leave empty {}
- pin_roles: map every pin_number string to its electrical role
- confidence: high if you are certain, medium if plausible, low if guessing
"""

USER_PROMPT_TEMPLATE = """\
Classify this component:
  ref:        {ref}
  value:      {value}
  lib_symbol: {lib_symbol}
  pins:       {pins_json}
"""

# ---------------------------------------------------------------------------
# Fallback result
# ---------------------------------------------------------------------------

FALLBACK_RESULT = {
    "component_type": "unknown",
    "applicable_tests": ["continuity"],
    "test_parameters": {},
    "pin_roles": {},
    "confidence": "low",
    "reasoning": "LLM unavailable or returned invalid JSON — continuity only",
}

# ---------------------------------------------------------------------------
# Threshold widening for medium confidence
# ---------------------------------------------------------------------------

THRESHOLD_KEYS_TO_WIDEN = ["vf_min_v", "vf_max_v", "resistance_ohm"]
WIDEN_FACTOR = 0.20   # ±20%


def _widen_thresholds(params: dict) -> dict:
    """Widen numeric thresholds by 20% for medium-confidence components."""
    widened = dict(params)
    if "vf_min_v" in widened:
        widened["vf_min_v"] = round(widened["vf_min_v"] * (1 - WIDEN_FACTOR), 4)
    if "vf_max_v" in widened:
        widened["vf_max_v"] = round(widened["vf_max_v"] * (1 + WIDEN_FACTOR), 4)
    return widened


# ---------------------------------------------------------------------------
# JSON extraction (strips markdown fences if model adds them anyway)
# ---------------------------------------------------------------------------

def _extract_json(text: str) -> Optional[dict]:
    # Strip ```json ... ``` or ``` ... ``` wrappers
    text = re.sub(r"```(?:json)?", "", text).strip()
    # Find first { ... } block
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group())
    except json.JSONDecodeError as exc:
        logger.debug("JSON parse error: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

VALID_COMPONENT_TYPES = {"diode", "led", "resistor", "capacitor", "ic",
                          "connector", "switch", "unknown"}
VALID_TESTS = {"continuity", "isolation", "diode_forward", "diode_reverse"}
VALID_CONFIDENCE = {"high", "medium", "low"}


def _validate(data: dict) -> bool:
    if data.get("component_type") not in VALID_COMPONENT_TYPES:
        return False
    if not isinstance(data.get("applicable_tests"), list):
        return False
    if any(t not in VALID_TESTS for t in data["applicable_tests"]):
        return False
    if data.get("confidence") not in VALID_CONFIDENCE:
        return False
    return True


# ---------------------------------------------------------------------------
# Main classifier
# ---------------------------------------------------------------------------

class ComponentClassifier:
    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client

    def classify(self, component: RawComponent) -> dict:
        """
        Returns a classification dict with keys:
          component_type, applicable_tests, test_parameters,
          pin_roles, confidence, reasoning

        Never raises — returns FALLBACK_RESULT on any error.
        """
        pins_summary = [
            {"pin_number": p.pin_number, "pin_name": p.pin_name, "pin_type": p.pin_type}
            for p in component.pins
        ]
        user_prompt = USER_PROMPT_TEMPLATE.format(
            ref=component.ref,
            value=component.value,
            lib_symbol=component.lib_symbol,
            pins_json=json.dumps(pins_summary, indent=2),
        )

        raw = self.llm.complete(SYSTEM_PROMPT, user_prompt)
        if raw is None:
            logger.warning("LLM unavailable for %s — using fallback", component.ref)
            return dict(FALLBACK_RESULT)

        result = _extract_json(raw)
        if result is None or not _validate(result):
            logger.warning(
                "Invalid LLM response for %s — using fallback. Raw: %.200s",
                component.ref, raw
            )
            return dict(FALLBACK_RESULT)

        # Confidence gating
        confidence = result["confidence"]
        if confidence == "low":
            result["applicable_tests"] = ["continuity"]
            logger.info("%s classified as low-confidence — continuity only", component.ref)
        elif confidence == "medium":
            result["test_parameters"] = _widen_thresholds(
                result.get("test_parameters", {})
            )
            logger.info("%s classified as medium-confidence — thresholds widened 20%%", component.ref)

        logger.info(
            "%s → type=%s  tests=%s  confidence=%s",
            component.ref,
            result["component_type"],
            result["applicable_tests"],
            confidence,
        )
        return result

    def classify_all(self, components: dict[str, RawComponent]) -> dict[str, dict]:
        """
        Classify every component in the schematic.
        Returns dict[ref → classification_dict].
        """
        results = {}
        for ref, comp in components.items():
            results[ref] = self.classify(comp)
        return results
