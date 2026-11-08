"""P6.5 LLM numbers (experiments/analysis/llm_latency.py): per-intent latency, call quality."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from experiments.analysis.llm_latency import LLMCall, call_quality, genai_numbers, per_intent


def test_latency_is_per_intent_with_p95_and_the_10_s_target() -> None:
    report = per_intent([1.0, 2.0, 3.0, 4.0, 12.0, 2.0])
    assert report["intents"] == 6
    assert report["mean_s"] == pytest.approx(4.0)
    assert report["p95_s"] == 12.0  # nearest rank: ceil(0.95 * 6) = 6th of 6
    assert report["max_s"] == 12.0
    assert report["under_10_s"] == pytest.approx(5 / 6)


def test_no_intents_no_latency() -> None:
    assert per_intent([]) == {}


def _call(model: str, *, attempt: int = 1, valid: bool = True, reached: bool = True) -> LLMCall:
    return LLMCall(
        model=model,
        prompt_version="intent_v1",
        latency_s=1.0,
        attempt=attempt,
        valid=valid,
        reached=reached,
    )


def test_call_quality_counts_first_try_validity_and_invalid_outputs_caught() -> None:
    calls = [
        _call("cloud"),
        _call("cloud", valid=False),
        _call("cloud", attempt=2),
        _call("local", valid=False),
    ]
    quality = call_quality(calls)
    assert quality["cloud"] == {
        "calls": 3,
        "valid_first_try": 0.5,
        "invalid_caught": 1,
        "unreachable": 0,
    }
    assert quality["local"] == {
        "calls": 1,
        "valid_first_try": 0.0,
        "invalid_caught": 1,
        "unreachable": 0,
    }


def test_an_unreachable_model_is_not_an_invalid_output_caught() -> None:
    # a cloud timeout then the local fallback: nothing was refused by validation (H3, §5.4)
    calls = [_call("cloud", valid=False, reached=False), _call("cloud"), _call("local")]
    quality = call_quality(calls)
    assert quality["cloud"] == {
        "calls": 2,
        "valid_first_try": 1.0,
        "invalid_caught": 0,
        "unreachable": 1,
    }


@pytest.mark.parametrize(
    ("extra", "reached"),
    [
        ({"error": "", "prompt_tokens": 11, "completion_tokens": 7}, True),
        ({"error": "1 validation error(s)", "prompt_tokens": 11, "completion_tokens": 7}, True),
        # an older log line of a transport error: an error and no reply (no token counts)
        ({"error": "timed out", "prompt_tokens": None, "completion_tokens": None}, False),
        ({}, True),
    ],
)
def test_a_log_line_without_the_reached_field_is_read_from_its_reply(
    extra: dict[str, Any], reached: bool
) -> None:
    base = {"model": "m", "prompt_version": "v", "latency_s": 1, "attempt": 1, "valid": False}
    assert LLMCall.model_validate(base | extra).reached is reached


def test_the_reached_field_wins_when_the_log_has_it() -> None:
    line = {"model": "m", "prompt_version": "v", "latency_s": 1, "attempt": 1, "valid": False}
    line |= {"error": "x", "prompt_tokens": None, "completion_tokens": None, "reached": True}
    assert LLMCall.model_validate(line).reached


def test_the_eval_files_are_validated_and_summarised(tmp_path: Path) -> None:
    report = {
        "cases": 2,
        "correct": 1,
        "accuracy": 0.5,
        "schema_valid": 2,
        "models": {"cloud": 2},
        "misses": ["i02"],
        "seconds": [1.0, 3.0],
    }
    (tmp_path / "intents.json").write_text(json.dumps(report))
    call = {
        "model": "cloud",
        "prompt_version": "intent_v1",
        "latency_s": 1.0,
        "attempt": 1,
        "valid": True,
        "tokens": 9,
    }  # extra fields of the log are ignored
    (tmp_path / "calls.jsonl").write_text(json.dumps(call) + "\n")
    numbers = genai_numbers(tmp_path / "intents.json", tmp_path / "calls.jsonl")
    assert numbers["accuracy"] == 0.5
    assert numbers["latency"]["p95_s"] == 3.0
    assert numbers["calls"]["cloud"]["valid_first_try"] == 1.0


def test_a_malformed_call_log_line_is_an_error_not_a_silent_zero(tmp_path: Path) -> None:
    (tmp_path / "intents.json").write_text(
        json.dumps(
            {
                "cases": 0,
                "correct": 0,
                "accuracy": 0.0,
                "schema_valid": 0,
                "models": {},
                "misses": [],
                "seconds": [],
            }
        )
    )
    (tmp_path / "calls.jsonl").write_text('{"model": "cloud"}\n')
    with pytest.raises(ValidationError):
        genai_numbers(tmp_path / "intents.json", tmp_path / "calls.jsonl")
