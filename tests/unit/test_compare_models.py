"""P0.7 scoring logic (genai/eval/compare_models.py), without calling any LLM."""

from typing import Any

from common.schemas import Policy
from genai.eval.compare_models import CASES, score


def _policy(zone: str | None, apps: list[str] | None, objectives: list[dict[str, Any]]) -> Policy:
    return Policy.model_validate(
        {
            "policy_id": "pol_t",
            "intent_text": "t",
            "scope": {"zone": zone, "app_class": apps},
            "objectives": objectives,
            "created_by": "llm.intent",
        }
    )


def test_exact_match_scores_both() -> None:
    p = _policy("lab", ["video"], [{"kpi": "latency_ms", "op": "<=", "value": 50}])
    assert score(p, "lab", {"video"}, {("latency_ms", "<=", 50.0)}) == (True, True)


def test_missing_app_class_fails_scope_only() -> None:
    p = _policy("lab", None, [{"kpi": "latency_ms", "op": "<=", "value": 50}])
    assert score(p, "lab", {"video"}, {("latency_ms", "<=", 50.0)}) == (False, True)


def test_missing_objective_fails_objectives_only() -> None:
    p = _policy("lab", ["video"], [{"kpi": "latency_ms", "op": "<=", "value": 50}])
    expected = {("latency_ms", "<=", 50.0), ("priority", "=", "high")}
    assert score(p, "lab", {"video"}, expected) == (True, False)


def test_priority_values_compare_as_strings() -> None:
    p = _policy(None, ["bulk"], [{"kpi": "priority", "op": "=", "value": "low"}])
    assert score(p, None, {"bulk"}, {("priority", "=", "low")}) == (True, True)


def test_invalid_output_scores_nothing() -> None:
    assert score(None, "lab", {"video"}, {("latency_ms", "<=", 50.0)}) == (False, False)


def test_every_case_expectation_is_itself_a_valid_policy() -> None:
    for intent, zone, apps, objectives in CASES:
        _policy(
            zone,
            sorted(apps) if apps else None,
            [{"kpi": k, "op": o, "value": v} for k, o, v in objectives],
        )
        assert intent
