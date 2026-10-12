"""P6.5 LLM numbers (problem statement §5.4) from one intent eval (`make intent-eval`):

- **response time per intent** (< 10 s): the eval's own wall time per intent, retries and a
  fallback included (experiments/results/intents*.json `seconds`);
- **schema-valid on the first try** and **invalid outputs caught** per model: the eval's own
  LLM call log (experiments/results/intent_calls*.jsonl). An invalid output is refused by the
  client's validation before the compiler (RULEBOOK T-5 (e)), so these are the ones H3 counts as
  stopped, not as reaching the network.

Both files are validated on reading (RULEBOOK C-2).
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from controller.executor.live_kpis import p95

TARGET_S = 10.0  # problem statement §5.4


class LLMCall(BaseModel):
    """One line of an LLM call log (genai/llm/client.py), the fields used here."""

    model_config = ConfigDict(extra="ignore", protected_namespaces=())
    model: str
    prompt_version: str
    latency_s: float
    attempt: int
    valid: bool


class IntentReport(BaseModel):
    """experiments/results/intents*.json as genai/eval/run_intents.py --out writes it."""

    model_config = ConfigDict(extra="ignore")
    cases: int
    correct: int
    accuracy: float
    schema_valid: int
    models: dict[str, int]
    misses: list[str]
    seconds: list[float]


def per_intent(seconds: Sequence[float]) -> dict[str, float]:
    """Latency per intent: count, mean, p95 (nearest rank), max and the share under 10 s."""
    if not seconds:
        return {}
    ordered = sorted(seconds)
    return {
        "intents": len(ordered),
        "mean_s": statistics.fmean(ordered),
        "p95_s": p95(ordered),
        "max_s": ordered[-1],
        "under_10_s": sum(s < TARGET_S for s in ordered) / len(ordered),
    }


def call_quality(calls: Sequence[LLMCall]) -> dict[str, dict[str, float]]:
    """Per model: calls, the share valid on the first try, and invalid outputs caught."""
    by_model: dict[str, list[LLMCall]] = defaultdict(list)
    for c in calls:
        by_model[c.model].append(c)
    out = {}
    for model, group in sorted(by_model.items()):
        first = [c for c in group if c.attempt == 1]
        out[model] = {
            "calls": len(group),
            "valid_first_try": sum(c.valid for c in first) / len(first) if first else 0.0,
            "invalid_caught": sum(not c.valid for c in group),
        }
    return out


def genai_numbers(report_file: Path, calls_file: Path) -> dict[str, Any]:  # Any: JSON values
    """The §5.4 numbers of one intent eval (its report and its call log)."""
    report = IntentReport.model_validate_json(report_file.read_text())
    lines = calls_file.read_text().splitlines() if calls_file.exists() else []
    calls = [LLMCall.model_validate_json(line) for line in lines if line.strip()]
    return {
        "accuracy": report.accuracy,
        "correct": report.correct,
        "cases": report.cases,
        "schema_valid": report.schema_valid,
        "models": report.models,
        "misses": report.misses,
        "latency": per_intent(report.seconds),
        "calls": call_quality(calls),
    }
