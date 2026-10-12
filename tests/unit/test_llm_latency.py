"""P6.5 LLM numbers (experiments/analysis/llm_latency.py): per-intent latency, call quality."""

from __future__ import annotations

import json
from pathlib import Path

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


def _call(model: str, *, attempt: int = 1, valid: bool = True) -> LLMCall:
    return LLMCall(
        model=model, prompt_version="intent_v1", latency_s=1.0, attempt=attempt, valid=valid
    )


def test_call_quality_counts_first_try_validity_and_invalid_outputs_caught() -> None:
    calls = [
        _call("cloud"),
        _call("cloud", valid=False),
        _call("cloud", attempt=2),
        _call("local", valid=False),
    ]
    quality = call_quality(calls)
    assert quality["cloud"] == {"calls": 3, "valid_first_try": 0.5, "invalid_caught": 1}
    assert quality["local"] == {"calls": 1, "valid_first_try": 0.0, "invalid_caught": 1}


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
