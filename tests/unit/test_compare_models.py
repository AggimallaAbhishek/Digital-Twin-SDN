"""P0.7 model comparison (genai/eval/compare_models.py), without calling any LLM."""

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pytest
import yaml

from common.schemas import Policy
from genai.eval import compare_models
from genai.eval.compare_models import CASES, SYSTEM_PROMPT, score
from tests.unit.test_collector import FakeOpener  # the shared urlopen fake


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


def _expected_policy(case: tuple[str, str | None, set[str] | None, set[Any]]) -> Policy:
    """The policy a perfect model would return for `case`."""
    _intent, zone, apps, objectives = case
    return _policy(
        zone,
        sorted(apps) if apps else None,
        [{"kpi": k, "op": o, "value": v} for k, o, v in sorted(objectives)],
    )


def test_every_case_expectation_is_itself_a_valid_policy() -> None:
    for case in CASES:
        assert score(_expected_policy(case), *case[1:]) == (True, True)


# ------------------------------------------------------------------ against a fake Ollama
class FakeOllama:
    """Answers /api/chat with the expected policy for each case (or `content` if set),
    and /api/ps with one loaded model; records every chat request."""

    def __init__(self) -> None:
        self.content: str | None = None
        self.error: Exception | None = None
        self.chats: list[dict[str, Any]] = []
        self.loaded = {"name": "qwen2.5:3b", "model": "qwen2.5:3b"}  # what /api/ps names it

    def post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        assert path == "/api/chat"
        self.chats.append(payload)
        if self.error is not None:
            raise self.error
        if self.content is not None:
            return {"message": {"content": self.content}}
        intent = payload["messages"][1]["content"]
        case = next(c for c in CASES if c[0] == intent)
        return {"message": {"content": _expected_policy(case).model_dump_json()}}

    def get(self, path: str) -> dict[str, Any]:
        assert path == "/api/ps"
        return {"models": [{**self.loaded, "size": 2.5e9}]}  # 2.5 GB resident


@pytest.fixture
def ollama(monkeypatch: pytest.MonkeyPatch) -> FakeOllama:
    fake = FakeOllama()
    monkeypatch.setattr(compare_models, "_post", fake.post)
    monkeypatch.setattr(compare_models, "_get", fake.get)
    return fake


def test_a_case_asks_for_schema_constrained_json_at_temperature_0(ollama: FakeOllama) -> None:
    policy, _seconds, error = compare_models.run_case("qwen2.5:3b", CASES[0][0])
    assert policy is not None
    assert error == ""
    (chat,) = ollama.chats
    assert chat["model"] == "qwen2.5:3b"
    assert chat["messages"][0] == {"role": "system", "content": SYSTEM_PROMPT}
    assert chat["format"] == Policy.model_json_schema()
    assert chat["options"] == {"temperature": 0}
    assert chat["stream"] is False


def test_output_that_is_not_a_policy_is_reported_not_raised(ollama: FakeOllama) -> None:
    ollama.content = '{"policy_id": "pol_x"}'
    policy, _seconds, error = compare_models.run_case("qwen2.5:3b", CASES[0][0])
    assert policy is None
    assert "validation error(s)" in error
    assert '{"policy_id": "pol_x"}' in error


@pytest.mark.parametrize(
    "error", [urllib.error.URLError("connection refused"), TimeoutError("timed out")]
)
def test_an_unreachable_model_is_reported_not_raised(ollama: FakeOllama, error: Exception) -> None:
    ollama.error = error
    policy, _seconds, message = compare_models.run_case("qwen2.5:3b", CASES[0][0])
    assert policy is None
    assert message.startswith("request failed:")


def test_a_model_is_warmed_up_then_asked_every_case(ollama: FakeOllama) -> None:
    results = compare_models.evaluate_model("qwen2.5:3b")
    intents = [chat["messages"][1]["content"] for chat in ollama.chats]
    assert intents[1:] == [case[0] for case in CASES]  # after one warm-up call
    assert all(r.valid and r.scope_ok and r.objectives_ok for r in results)
    assert len(results) == len(CASES)


@pytest.mark.parametrize(
    ("model", "loaded", "gb"),
    [
        ("qwen2.5:3b", {"name": "qwen2.5:3b", "model": "qwen2.5:3b"}, 2.5),
        ("phi3", {"name": "phi3:latest", "model": "phi3:latest"}, 2.5),  # untagged = `:latest`
        ("qwen2.5:3b", {"name": "my-alias", "model": "qwen2.5:3b"}, 2.5),  # matched by `model`
        ("gpt-oss:120b-cloud", {"name": "qwen2.5:3b", "model": "qwen2.5:3b"}, 0.0),  # not loaded
    ],
    ids=["exact", "latest-tag", "model-field", "not-loaded"],
)
def test_resident_size_of_a_loaded_model(
    ollama: FakeOllama, model: str, loaded: dict[str, str], gb: float
) -> None:
    ollama.loaded = loaded
    assert compare_models.resident_gb(model) == pytest.approx(gb)


def test_main_prints_a_table_and_every_miss(
    ollama: FakeOllama, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def post(path: str, payload: dict[str, Any]) -> dict[str, Any]:  # one bad model
        if payload["model"] == "bad":
            return {"message": {"content": "not json"}}
        return ollama.post(path, payload)

    monkeypatch.setattr(compare_models, "_post", post)
    monkeypatch.setattr(sys, "argv", ["compare_models", "--models", "qwen2.5:3b", "bad"])
    compare_models.main()
    out = capsys.readouterr().out
    n = len(CASES)
    good_row = next(line for line in out.splitlines() if line.startswith("| qwen2.5:3b |"))
    assert good_row.startswith(f"| qwen2.5:3b | {n}/{n} | {n}/{n} | {n}/{n} | **{n}/{n}** |")
    assert good_row.endswith("| 2.5 |")  # RAM GB from /api/ps
    assert f"| bad | 0/{n} | 0/{n} | 0/{n} | **0/{n}** |" in out
    assert out.count("[bad] MISS") == n
    assert "[qwen2.5:3b] MISS" not in out


@pytest.mark.usefixtures("ollama")
def test_main_defaults_to_the_configured_main_and_fallback_models(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["compare_models"])
    compare_models.main()
    out = capsys.readouterr().out
    assert Path(__file__).resolve().parents[2] / "config" / "llm.yaml" == compare_models.LLM_CONFIG
    config = yaml.safe_load(compare_models.LLM_CONFIG.read_text())
    assert f"| {config['model']} |" in out
    assert f"| {config['fallback_model']} |" in out


# ------------------------------------------------------------------ the HTTP calls
def test_post_sends_json_to_the_local_ollama(monkeypatch: pytest.MonkeyPatch) -> None:
    opener = FakeOpener(body=b'{"message": {"content": "{}"}}')
    monkeypatch.setattr(urllib.request, "urlopen", opener)
    assert compare_models._post("/api/chat", {"model": "m"}) == {"message": {"content": "{}"}}
    (request,) = opener.requests
    assert isinstance(request, urllib.request.Request)
    assert request.full_url == "http://localhost:11434/api/chat"
    assert isinstance(request.data, bytes)
    assert json.loads(request.data) == {"model": "m"}
    assert request.get_header("Content-type") == "application/json"


def test_get_reads_json_from_the_local_ollama(monkeypatch: pytest.MonkeyPatch) -> None:
    opener = FakeOpener(body=b'{"models": []}')
    monkeypatch.setattr(urllib.request, "urlopen", opener)
    assert compare_models._get("/api/ps") == {"models": []}
    (request,) = opener.requests
    assert getattr(request, "full_url", request) == "http://localhost:11434/api/ps"
