"""P5.1 LLM client (genai/llm/client.py), with a fake transport: no network, no Ollama."""

from __future__ import annotations

import io
import json
import urllib.error
from email.message import Message
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from genai.llm.client import (
    LLMClient,
    LLMConfig,
    LLMOutputError,
    LLMUnavailableError,
    ToolCall,
    TransportError,
    ollama_transport,
)

CLOUD = "cloud-model"
LOCAL = "local-model"


class Answer(BaseModel):
    """Stand-in for a schema like Policy: one required integer field."""

    value: int


class FakeTransport:
    """Replays scripted replies per model; records every request it receives."""

    def __init__(self, replies: dict[str, list[Any]]) -> None:
        self.replies = {model: list(items) for model, items in replies.items()}
        self.requests: list[tuple[str, dict[str, Any], float]] = []

    def __call__(self, path: str, payload: dict[str, Any], timeout_s: float) -> dict[str, Any]:
        self.requests.append((path, payload, timeout_s))
        reply = self.replies[payload["model"]].pop(0)
        if isinstance(reply, Exception):
            raise reply
        message = reply if isinstance(reply, dict) else {"role": "assistant", "content": reply}
        return {
            "message": message,
            "prompt_eval_count": 11,
            "eval_count": 7,
        }


def _config() -> LLMConfig:
    return LLMConfig(
        base_url="http://ollama.test",
        model=CLOUD,
        fallback_model=LOCAL,
        cloud_timeout_s=15,
        timeout_s=60,
        temperature=0,
        max_repair_retries=2,
        keep_alive="30m",
    )


def _client(transport: FakeTransport, tmp_path: Path) -> LLMClient:
    return LLMClient(_config(), transport=transport, log_path=tmp_path / "llm_calls.jsonl")


MESSAGES = [{"role": "user", "content": "give me 42"}]


def test_cloud_reply_is_validated_and_returned(tmp_path: Path) -> None:
    transport = FakeTransport({CLOUD: [json.dumps({"value": 42})]})

    result = _client(transport, tmp_path).complete_json(MESSAGES, Answer, prompt_version="t/v1")

    assert result.value == Answer(value=42)
    assert result.model == CLOUD
    assert result.fell_back is False
    path, payload, timeout_s = transport.requests[0]
    assert path == "/api/chat"
    assert payload["format"] == Answer.model_json_schema()
    assert payload["options"] == {"temperature": 0}
    assert payload["stream"] is False
    assert payload["keep_alive"] == "30m"
    assert timeout_s == 15


@pytest.mark.parametrize(
    "failure",
    [TransportError("timed out"), TransportError("HTTP 410: model retired")],
    ids=["timeout", "http-error"],
)
def test_cloud_failure_falls_back_to_local_model(tmp_path: Path, failure: Exception) -> None:
    transport = FakeTransport({CLOUD: [failure], LOCAL: [json.dumps({"value": 7})]})

    result = _client(transport, tmp_path).complete_json(MESSAGES, Answer, prompt_version="t/v1")

    assert result.value == Answer(value=7)
    assert result.model == LOCAL
    assert result.fell_back is True
    assert [(p["model"], t) for _, p, t in transport.requests] == [(CLOUD, 15), (LOCAL, 60)]


def test_both_models_unreachable_raises_unavailable(tmp_path: Path) -> None:
    transport = FakeTransport(
        {CLOUD: [TransportError("no internet")], LOCAL: [TransportError("ollama not running")]}
    )

    with pytest.raises(LLMUnavailableError, match="ollama not running"):
        _client(transport, tmp_path).complete_json(MESSAGES, Answer, prompt_version="t/v1")


def test_invalid_reply_is_repaired_on_the_same_model(tmp_path: Path) -> None:
    transport = FakeTransport({CLOUD: ['{"value": "not a number"}', '{"value": 3}']})

    result = _client(transport, tmp_path).complete_json(MESSAGES, Answer, prompt_version="t/v1")

    assert result.value == Answer(value=3)
    assert result.model == CLOUD
    repair_messages = transport.requests[1][1]["messages"]
    assert repair_messages[: len(MESSAGES)] == MESSAGES
    assert repair_messages[-2] == {"role": "assistant", "content": '{"value": "not a number"}'}
    assert repair_messages[-1]["role"] == "user"
    assert "value" in repair_messages[-1]["content"]  # names the failing field


def test_second_repair_can_still_succeed(tmp_path: Path) -> None:
    transport = FakeTransport({CLOUD: ["not json", '{"value": "x"}', '{"value": 5}']})

    result = _client(transport, tmp_path).complete_json(MESSAGES, Answer, prompt_version="t/v1")

    assert result.value == Answer(value=5)
    assert len(transport.requests) == 3


def test_still_invalid_after_two_repairs_fails_safely(tmp_path: Path) -> None:
    transport = FakeTransport({CLOUD: ["not json", "{}", '{"value": "x"}'], LOCAL: []})

    with pytest.raises(LLMOutputError, match="3 attempts"):
        _client(transport, tmp_path).complete_json(MESSAGES, Answer, prompt_version="t/v1")
    assert len(transport.requests) == 3  # no 4th try, and no fallback on invalid output


def _log_lines(tmp_path: Path) -> list[dict[str, Any]]:
    text = (tmp_path / "llm_calls.jsonl").read_text()
    return [json.loads(line) for line in text.splitlines()]


def test_every_call_is_logged_without_prompt_text(tmp_path: Path) -> None:
    transport = FakeTransport(
        {CLOUD: [TransportError("timed out")], LOCAL: ['{"value": "x"}', '{"value": 1}']}
    )

    _client(transport, tmp_path).complete_json(MESSAGES, Answer, prompt_version="intent/v1")

    lines = _log_lines(tmp_path)
    assert [(e["model"], e["fallback"], e["attempt"], e["valid"]) for e in lines] == [
        (CLOUD, False, 1, False),
        (LOCAL, True, 1, False),
        (LOCAL, True, 2, True),
    ]
    assert lines[0]["error"] == "timed out"
    assert lines[0]["prompt_tokens"] is None
    assert lines[2]["error"] == ""
    assert (lines[2]["prompt_tokens"], lines[2]["completion_tokens"]) == (11, 7)
    for entry in lines:
        assert entry["prompt_version"] == "intent/v1"
        assert entry["schema"] == "Answer"
        assert entry["cost_usd"] == 0.0
        assert entry["latency_s"] >= 0
        assert entry["ts"].endswith("+00:00")
    assert "give me 42" not in (tmp_path / "llm_calls.jsonl").read_text()


def test_log_directory_is_created(tmp_path: Path) -> None:
    transport = FakeTransport({CLOUD: ['{"value": 1}']})
    log_path = tmp_path / "logs" / "llm_calls.jsonl"

    LLMClient(_config(), transport=transport, log_path=log_path).complete_json(
        MESSAGES, Answer, prompt_version="t/v1"
    )

    assert log_path.exists()


def test_connection_lost_during_repair_raises_unavailable(tmp_path: Path) -> None:
    transport = FakeTransport({CLOUD: ["not json", TransportError("connection reset")]})

    with pytest.raises(LLMUnavailableError, match="connection reset"):
        _client(transport, tmp_path).complete_json(MESSAGES, Answer, prompt_version="t/v1")
    assert [(e["attempt"], e["error"]) for e in _log_lines(tmp_path)] == [
        (1, "1 validation error(s)"),
        (2, "connection reset"),
    ]


def test_complete_text_returns_plain_reply_with_fallback(tmp_path: Path) -> None:
    transport = FakeTransport({CLOUD: [TransportError("timed out")], LOCAL: ["AP2 is overloaded."]})

    result = _client(transport, tmp_path).complete_text(MESSAGES, prompt_version="rca/v1")

    assert (result.value, result.model, result.fell_back) == ("AP2 is overloaded.", LOCAL, True)
    assert "format" not in transport.requests[1][1]
    assert [(e["schema"], e["valid"]) for e in _log_lines(tmp_path)] == [
        ("text", False),
        ("text", True),
    ]


def test_complete_text_both_unreachable_raises_unavailable(tmp_path: Path) -> None:
    transport = FakeTransport({CLOUD: [TransportError("a")], LOCAL: [TransportError("b")]})

    with pytest.raises(LLMUnavailableError):
        _client(transport, tmp_path).complete_text(MESSAGES, prompt_version="rca/v1")


def test_from_config_reads_the_project_llm_config() -> None:
    client = LLMClient.from_config()

    assert client.config.model == "gpt-oss:120b-cloud"  # ADR-001
    assert client.config.fallback_model == "qwen2.5:3b"
    assert client.config.cloud_timeout_s == 15
    assert client.config.max_repair_retries == 2


class _FakeResponse(io.BytesIO):
    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


def test_ollama_transport_posts_json_and_parses_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def fake_urlopen(request: Any, timeout: float) -> _FakeResponse:
        seen.update(url=request.full_url, body=json.loads(request.data), timeout=timeout)
        return _FakeResponse(b'{"message": {"content": "hi"}}')

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    reply = ollama_transport("http://ollama.test")("/api/chat", {"model": "m"}, 15)

    assert reply == {"message": {"content": "hi"}}
    assert seen == {"url": "http://ollama.test/api/chat", "body": {"model": "m"}, "timeout": 15}


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (urllib.error.HTTPError("u", 410, "Gone", Message(), None), "HTTP 410"),
        (urllib.error.URLError("connection refused"), "connection refused"),
        (TimeoutError("timed out"), "timed out"),
    ],
    ids=["http-error", "unreachable", "timeout"],
)
def test_ollama_transport_wraps_network_failures(
    monkeypatch: pytest.MonkeyPatch, error: Exception, message: str
) -> None:
    def fake_urlopen(request: Any, timeout: float) -> _FakeResponse:
        raise error

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    with pytest.raises(TransportError, match=message):
        ollama_transport("http://ollama.test")("/api/chat", {}, 15)


def test_ollama_transport_wraps_a_non_json_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("urllib.request.urlopen", lambda request, timeout: _FakeResponse(b"<html>"))

    with pytest.raises(TransportError, match="not JSON"):
        ollama_transport("http://ollama.test")("/api/chat", {}, 15)


TOOLS = [{"type": "function", "function": {"name": "get_alerts", "parameters": {}}}]


def _calls(*calls: tuple[str, Any]) -> dict[str, Any]:
    """An Ollama assistant message asking for tool calls."""
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [{"function": {"name": n, "arguments": a}} for n, a in calls],
    }


def test_tool_calls_are_returned_with_their_arguments(tmp_path: Path) -> None:
    reply = _calls(("get_alerts", {"since_s": 300}), ("get_topology", "{}"))
    transport = FakeTransport({CLOUD: [reply]})
    result = _client(transport, tmp_path).complete_tools(MESSAGES, TOOLS, prompt_version="t/v1")
    assert result.value.tool_calls == [
        ToolCall("get_alerts", {"since_s": 300}),
        ToolCall("get_topology", {}),  # some models send the arguments as a JSON string
    ]
    [(path, payload, _)] = transport.requests
    assert path == "/api/chat"
    assert payload["tools"] == TOOLS
    assert "format" not in payload


def test_a_final_answer_has_no_tool_calls(tmp_path: Path) -> None:
    transport = FakeTransport({CLOUD: ["ap2 is down."]})
    result = _client(transport, tmp_path).complete_tools(MESSAGES, TOOLS, prompt_version="t/v1")
    assert result.value.content == "ap2 is down."
    assert result.value.tool_calls == []


def test_unreadable_tool_arguments_are_kept_for_the_tool_layer_to_refuse(tmp_path: Path) -> None:
    transport = FakeTransport(
        {CLOUD: [_calls(("get_alerts", "{since_s: 3"), ("get_alerts", "[3]"))]}
    )
    result = _client(transport, tmp_path).complete_tools(MESSAGES, TOOLS, prompt_version="t/v1")
    assert result.value.tool_calls == [
        ToolCall("get_alerts", {"unparsed": "{since_s: 3"}),
        ToolCall("get_alerts", {"unparsed": [3]}),
    ]


def test_tool_turns_fall_back_to_the_local_model(tmp_path: Path) -> None:
    transport = FakeTransport(
        {CLOUD: [TransportError("down")], LOCAL: [_calls(("get_alerts", {}))]}
    )
    result = _client(transport, tmp_path).complete_tools(MESSAGES, TOOLS, prompt_version="t/v1")
    assert result.fell_back is True
    assert result.value.tool_calls == [ToolCall("get_alerts", {})]
    assert transport.requests[1][1]["tools"] == TOOLS
    entry = json.loads((tmp_path / "llm_calls.jsonl").read_text().splitlines()[-1])
    assert (entry["schema"], entry["valid"]) == ("tools", True)


def test_tool_calls_are_logged(tmp_path: Path) -> None:  # RULEBOOK L-5
    transport = FakeTransport({CLOUD: [_calls(("get_alerts", {"since_s": 300}))]})
    _client(transport, tmp_path).complete_tools(MESSAGES, TOOLS, prompt_version="t/v1")
    entry = json.loads((tmp_path / "llm_calls.jsonl").read_text().splitlines()[-1])
    assert entry["tool_calls"] == [{"name": "get_alerts", "arguments": {"since_s": 300}}]


def test_json_calls_log_no_tool_calls(tmp_path: Path) -> None:
    transport = FakeTransport({CLOUD: [json.dumps({"value": 42})]})
    _client(transport, tmp_path).complete_json(MESSAGES, Answer, prompt_version="t/v1")
    entry = json.loads((tmp_path / "llm_calls.jsonl").read_text().splitlines()[-1])
    assert entry["tool_calls"] == []
