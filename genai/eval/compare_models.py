"""P0.7: compare local Ollama models on intent -> Policy JSON (decisions Q3: Ollama only).

Same prompt and the same JSON-schema-constrained output for every model, temperature 0. Scores:
schema-valid (common.schemas.Policy), correct scope (zone + app classes), correct objectives,
latency, and the model's resident size reported by Ollama.

    uv run python -m genai.eval.compare_models --models gpt-oss:120b-cloud qwen2.5:3b
    uv run python -m genai.eval.compare_models   # main + fallback from config/llm.yaml
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from common.schemas import Policy

OLLAMA_URL = "http://localhost:11434"
LLM_CONFIG = Path(__file__).resolve().parents[2] / "config" / "llm.yaml"
TIMEOUT_S = 300

SYSTEM_PROMPT = """You convert a network operator's intent into ONE JSON policy for a campus Wi-Fi
SDN network. Output only JSON matching the given schema.
- zones: lecture_hall, lab, corridor, library (scope.zone = null means everywhere)
- app classes: video, web, bulk (scope.app_class = null means all traffic)
- objectives: KPI targets {"kpi": latency_ms|throughput_mbps|jitter_ms|loss_pct, "op": "<="|">=",
  "value": number} or a priority {"kpi": "priority", "op": "=", "value": "high"|"normal"|"low"}
- "under/below/at most X" -> "<=", "at least X" -> ">="; units: ms, Mbps, percent
- If the intent names a traffic type, ALWAYS set scope.app_class to it: video/calls/streaming ->
  ["video"], web/browsing -> ["web"], downloads/transfers/backups/bulk -> ["bulk"]
- policy_id: "pol_" + short snake_case words; intent_text: the intent verbatim;
  created_by: "llm.intent"; constraints: []; valid: {"from": null, "until": null}

Example intent: "Make web browsing in the library fast: latency at most 80 ms."
Example output: {"policy_id": "pol_library_web_latency", "intent_text": "Make web browsing in
the library fast: latency at most 80 ms.", "scope": {"zone": "library", "app_class": ["web"]},
"objectives": [{"kpi": "latency_ms", "op": "<=", "value": 80}], "constraints": [],
"valid": {"from": null, "until": null}, "created_by": "llm.intent"}"""

# (intent, expected zone, expected app classes, expected objectives as (kpi, op, value))
CASES: list[tuple[str, str | None, set[str] | None, set[tuple[str, str, Any]]]] = [
    (
        "Give video calls in the lab priority and keep latency under 50 ms.",
        "lab",
        {"video"},
        {("latency_ms", "<=", 50.0), ("priority", "=", "high")},
    ),
    (
        "Keep packet loss below 1% for web traffic in the corridor.",
        "corridor",
        {"web"},
        {("loss_pct", "<=", 1.0)},
    ),
    (
        "Video in the lecture hall needs at least 3 Mbps.",
        "lecture_hall",
        {"video"},
        {("throughput_mbps", ">=", 3.0)},
    ),
    (
        "Lower the priority of bulk transfers everywhere.",
        None,
        {"bulk"},
        {("priority", "=", "low")},
    ),
    (
        "In the lecture hall keep video jitter under 30 ms and loss under 2 percent.",
        "lecture_hall",
        {"video"},
        {("jitter_ms", "<=", 30.0), ("loss_pct", "<=", 2.0)},
    ),
]


@dataclass
class CaseResult:
    """Outcome of one intent on one model."""

    valid: bool
    scope_ok: bool
    objectives_ok: bool
    latency_s: float
    error: str = ""


def _post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(  # noqa: S310 - fixed local Ollama URL, not user input
        OLLAMA_URL + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT_S) as resp:  # noqa: S310 - as above
        result: dict[str, Any] = json.loads(resp.read())
        return result


def _get(path: str) -> dict[str, Any]:
    with urllib.request.urlopen(OLLAMA_URL + path, timeout=TIMEOUT_S) as resp:  # noqa: S310
        result: dict[str, Any] = json.loads(resp.read())
        return result


def run_case(model: str, intent: str) -> tuple[Policy | None, float, str]:
    """Ask `model` for a policy; return (parsed policy or None, seconds, error text)."""
    start = time.monotonic()
    try:
        reply = _call_chat(model, intent)
    except (urllib.error.URLError, TimeoutError) as exc:  # HTTPError is a URLError
        return None, time.monotonic() - start, f"request failed: {exc}"
    elapsed = time.monotonic() - start
    content = reply.get("message", {}).get("content", "")
    try:
        return Policy.model_validate_json(content), elapsed, ""
    except ValidationError as exc:
        return None, elapsed, f"{exc.error_count()} validation error(s): {content[:160]}"


def _call_chat(model: str, intent: str) -> dict[str, Any]:
    return _post(
        "/api/chat",
        {
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": intent},
            ],
            "format": Policy.model_json_schema(),
            "stream": False,
            "options": {"temperature": 0},
        },
    )


def score(
    policy: Policy | None,
    zone: str | None,
    apps: set[str] | None,
    objectives: set[tuple[str, str, Any]],
) -> tuple[bool, bool]:
    """Return (scope correct, objectives correct) for a parsed policy."""
    if policy is None:
        return False, False
    got_apps = set(policy.scope.app_class) if policy.scope.app_class else None
    scope_ok = policy.scope.zone == zone and got_apps == apps
    got = {
        (o.kpi, o.op, float(o.value) if not isinstance(o.value, str) else o.value)
        for o in policy.objectives
    }
    return scope_ok, got == objectives


def evaluate_model(model: str) -> list[CaseResult]:
    """Run every case on `model` (after one warm-up call that loads it into memory)."""
    run_case(model, CASES[0][0])  # warm-up: load weights, so latency excludes loading
    results = []
    for intent, zone, apps, objectives in CASES:
        policy, seconds, error = run_case(model, intent)
        scope_ok, obj_ok = score(policy, zone, apps, objectives)
        results.append(CaseResult(policy is not None, scope_ok, obj_ok, seconds, error))
    return results


def resident_gb(model: str) -> float:
    """Resident size of a loaded model in GB, as reported by Ollama /api/ps (0 if not loaded)."""
    wanted = {model, model if ":" in model else f"{model}:latest"}
    for entry in _get("/api/ps").get("models", []):
        if entry.get("name") in wanted or entry.get("model") in wanted:
            return float(entry.get("size", 0)) / 1e9
    return 0.0


def main() -> None:
    """Compare models and print a markdown table plus per-case failures."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--models", nargs="+", help="default: model + fallback_model from config")
    args = parser.parse_args()
    if not args.models:
        config = yaml.safe_load(LLM_CONFIG.read_text())
        args.models = [config["model"], config["fallback_model"]]

    rows = []
    for model in args.models:
        results = evaluate_model(model)
        size = resident_gb(model)
        n = len(results)
        valid = sum(r.valid for r in results)
        scope = sum(r.scope_ok for r in results)
        objectives = sum(r.objectives_ok for r in results)
        correct = sum(r.valid and r.scope_ok and r.objectives_ok for r in results)
        mean_s = sum(r.latency_s for r in results) / n
        max_s = max(r.latency_s for r in results)
        rows.append(
            f"| {model} | {valid}/{n} | {scope}/{n} | {objectives}/{n} | **{correct}/{n}**"
            f" | {mean_s:.1f} | {max_s:.1f} | {size:.1f} |"
        )
        for (intent, *_), r in zip(CASES, results, strict=True):
            if not (r.valid and r.scope_ok and r.objectives_ok):
                print(
                    f"[{model}] MISS {intent!r}: valid={r.valid} scope={r.scope_ok} "
                    f"objectives={r.objectives_ok} {r.error}"
                )
    print(
        "\n| Model | Schema-valid | Scope | Objectives | Fully correct | Mean s | Max s | RAM GB |"
    )
    print("|---|---|---|---|---|---|---|---|")
    print("\n".join(rows))


if __name__ == "__main__":
    main()
