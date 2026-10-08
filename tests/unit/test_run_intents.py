"""P5.4 intent eval (genai/eval/run_intents.py): loading the test set and scoring, no LLM calls."""

from pathlib import Path
from typing import Any

import pytest

from common.schemas import Policy
from genai.eval.run_intents import INTENTS, Outcome, accuracy, load_cases, main, score
from genai.llm.client import LLMClient, LLMOutputError, LLMResult

LINE = (
    '{"id": "i01", "intent": "Give video in the lab priority.", "expected": '
    '{"scope": {"zone": "lab", "app_class": ["video"]}, '
    '"objectives": [{"kpi": "priority", "op": "=", "value": "high"}]}}'
)


def _policy(
    zone: str | None = "lab",
    apps: list[str] | None = None,
    objectives: list[dict[str, Any]] | None = None,
    constraints: list[dict[str, Any]] | None = None,
) -> Policy:
    return Policy.model_validate(
        {
            "policy_id": "pol_whatever_the_model_chose",
            "intent_text": "anything",
            "scope": {"zone": zone, "app_class": apps if apps is not None else ["video"]},
            "objectives": objectives or [{"kpi": "priority", "op": "=", "value": "high"}],
            "constraints": constraints or [],
            "created_by": "llm.intent",
        }
    )


def test_load_cases_reads_the_expected_policy(tmp_path: Path) -> None:
    path = tmp_path / "intents.jsonl"
    path.write_text(LINE + "\n\n")  # blank lines are skipped
    [case] = load_cases(path)
    assert case.case_id == "i01"
    assert case.intent == "Give video in the lab priority."
    assert case.expected.scope.zone == "lab"
    assert case.expected.intent_text == case.intent


def test_load_cases_rejects_an_expected_policy_the_schema_rejects(tmp_path: Path) -> None:
    path = tmp_path / "intents.jsonl"
    path.write_text(LINE.replace('"value": "high"', '"value": 5'))
    with pytest.raises(ValueError, match="i01"):
        load_cases(path)


def test_load_cases_rejects_duplicate_ids(tmp_path: Path) -> None:
    path = tmp_path / "intents.jsonl"
    path.write_text(LINE + "\n" + LINE + "\n")
    with pytest.raises(ValueError, match="duplicate"):
        load_cases(path)


def test_exact_match_is_correct_whatever_the_order_and_policy_id() -> None:
    objectives: list[dict[str, Any]] = [
        {"kpi": "latency_ms", "op": "<=", "value": 50},
        {"kpi": "priority", "op": "=", "value": "high"},
    ]
    expected = _policy(objectives=objectives, apps=["video", "web"])
    got = _policy(objectives=objectives[::-1], apps=["web", "video"])
    outcome = score(expected, got)
    assert outcome == Outcome(valid=True, scope=True, objectives=True, constraints=True)
    assert outcome.correct


def test_integer_and_float_targets_compare_equal() -> None:
    expected = _policy(objectives=[{"kpi": "latency_ms", "op": "<=", "value": 50}])
    got = _policy(objectives=[{"kpi": "latency_ms", "op": "<=", "value": 50.0}])
    assert score(expected, got).correct


def test_wrong_zone_fails_scope_only() -> None:
    outcome = score(_policy(zone="lab"), _policy(zone="library"))
    assert outcome == Outcome(valid=True, scope=False, objectives=True, constraints=True)
    assert not outcome.correct


def test_everywhere_is_not_the_same_as_a_zone() -> None:
    assert not score(_policy(zone=None), _policy(zone="lab")).scope


def test_extra_objective_fails_objectives() -> None:
    extra: list[dict[str, Any]] = [
        {"kpi": "priority", "op": "=", "value": "high"},
        {"kpi": "loss_pct", "op": "<=", "value": 1},
    ]
    assert not score(_policy(), _policy(objectives=extra)).objectives


def test_constraint_scope_matters() -> None:
    limit = {"kpi": "loss_pct", "op": "<=", "value": 2}
    expected = _policy(constraints=[{**limit, "scope": "all"}])
    got = _policy(constraints=[{**limit, "scope": "policy"}])
    outcome = score(expected, got)
    assert outcome == Outcome(valid=True, scope=True, objectives=True, constraints=False)


def test_no_policy_is_wrong_on_every_count() -> None:
    outcome = score(_policy(), None)
    assert outcome == Outcome(valid=False, scope=False, objectives=False, constraints=False)
    assert not outcome.correct


def test_accuracy_is_the_share_of_fully_correct_outcomes() -> None:
    right = Outcome(valid=True, scope=True, objectives=True, constraints=True)
    wrong = Outcome(valid=True, scope=False, objectives=True, constraints=True)
    assert accuracy([right, right, wrong, wrong]) == 0.5
    assert accuracy([]) == 0.0


def test_the_shipped_test_set_has_30_valid_distinct_intents() -> None:
    cases = load_cases(INTENTS)
    assert len(cases) == 30
    assert len({c.intent for c in cases}) == 30


class _FakeClient:
    """Replies with a fixed policy per intent; the client fails on any other intent."""

    def __init__(self, replies: dict[str, Policy]) -> None:
        self._replies = replies

    def complete_json(
        self, messages: list[dict[str, str]], schema: type[Policy], *, prompt_version: str
    ) -> LLMResult[Policy]:
        assert schema is Policy
        assert prompt_version == "intent_v1"
        reply = self._replies.get(messages[-1]["content"])
        if reply is None:
            raise LLMOutputError("still invalid")
        return LLMResult(value=reply, model="fake", fell_back=False)


def test_main_reports_accuracy_and_misses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lines = [
        LINE,
        LINE.replace("i01", "i02").replace("lab", "library"),
        LINE.replace("i01", "i03").replace("lab priority", "corridor"),
    ]
    path = tmp_path / "intents.jsonl"
    path.write_text("\n".join(lines))
    right, wrong, _ = load_cases(path)
    replies = {right.intent: right.expected, wrong.intent: right.expected}  # i02: wrong zone
    monkeypatch.setattr(LLMClient, "from_config", lambda _path: _FakeClient(replies))
    main(["--intents", str(path)])
    out = capsys.readouterr().out
    assert "MISS i01" not in out
    assert "MISS i02" in out
    assert '"zone":"lab"' in out  # the wrong policy is printed
    assert "MISS i03" in out
    assert "still invalid" in out
    assert "| 2/3 | 1/3 | 2/3 | 2/3 | 1/3 | **33.3%** |" in out
