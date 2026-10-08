"""P5.3 intent engine (genai/intent/engine.py): text -> Policy -> actions -> twin verdicts."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import pytest

from common.schemas import Policy
from genai.intent.compiler import FlowRef
from genai.intent.engine import PROMPT_VERSION, IntentEngine
from genai.llm.client import LLMOutputError, LLMResult, LLMUnavailableError
from genai.tools.mock_backend import MockBackend
from genai.tools.tools import ToolLayer

NOW = datetime(2026, 10, 8, 10, 0, tzinfo=UTC)
FLOWS = [FlowRef("sta1-bulk", "bulk", "lab"), FlowRef("sta3-video", "video", "lab")]
TEXT = "Give video calls in the lab priority."


def _policy(**changes: Any) -> Policy:
    raw: dict[str, Any] = {
        "policy_id": "pol_lab_video",
        "intent_text": "the model's paraphrase",
        "scope": {"zone": "lab", "app_class": ["video"]},
        "objectives": [{"kpi": "priority", "op": "=", "value": "high"}],
        "created_by": "llm.intent",
    }
    return Policy.model_validate(raw | changes)


class FakeClient:
    """Returns a fixed policy, or raises a fixed error."""

    def __init__(self, reply: Policy | Exception) -> None:
        self.reply = reply
        self.calls: list[tuple[list[dict[str, str]], str]] = []

    def complete_json(
        self, messages: Sequence[dict[str, str]], schema: type[Policy], *, prompt_version: str
    ) -> LLMResult[Policy]:
        assert schema is Policy
        self.calls.append((list(messages), prompt_version))
        if isinstance(self.reply, Exception):
            raise self.reply
        return LLMResult(value=self.reply, model="fake-model", fell_back=False)


class FakeTools:
    """Records tool calls; simulate_in_twin accepts everything unless told otherwise."""

    def __init__(self, reply: dict[str, Any] | None = None) -> None:
        self.reply = reply
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((name, arguments))
        if self.reply is not None:
            return self.reply
        return {"action_id": arguments["action"]["action_id"], "accepted": True}


def test_an_intent_becomes_verified_actions() -> None:
    client, tools = FakeClient(_policy()), FakeTools()
    result = IntentEngine(client, tools).handle(TEXT, FLOWS, NOW)
    assert result.error == ""
    assert result.model == "fake-model"
    [action] = result.actions
    assert [name for name, _ in tools.calls] == ["simulate_in_twin"]
    assert tools.calls[0][1]["action"]["action_id"] == action.action_id
    assert result.verdicts[action.action_id]["accepted"] is True
    messages, version = client.calls[0]
    assert version == PROMPT_VERSION
    assert messages[0]["role"] == "system"
    assert messages[-1] == {"role": "user", "content": TEXT}


def test_the_policy_keeps_the_operators_words() -> None:
    result = IntentEngine(FakeClient(_policy()), FakeTools()).handle(TEXT, FLOWS, NOW)
    assert result.policy is not None
    assert result.policy.intent_text == TEXT


@pytest.mark.parametrize(
    "error", [LLMOutputError("still invalid"), LLMUnavailableError("both models down")]
)
def test_no_valid_policy_never_reaches_the_compiler_or_the_twin(error: Exception) -> None:
    tools = FakeTools()
    result = IntentEngine(FakeClient(error), tools).handle(TEXT, FLOWS, NOW)
    assert result.policy is None
    assert result.actions == []
    assert tools.calls == []
    assert str(error) in result.error


def test_a_policy_the_compiler_refuses_is_reported_and_not_simulated() -> None:
    everywhere = _policy(scope={"zone": None, "app_class": None})
    tools = FakeTools()
    result = IntentEngine(FakeClient(everywhere), tools).handle(TEXT, FLOWS, NOW)
    assert result.policy is not None
    assert "all traffic everywhere" in result.error
    assert tools.calls == []


def test_kpi_targets_compile_to_standing_objectives_only() -> None:
    target = _policy(objectives=[{"kpi": "latency_ms", "op": "<=", "value": 50}])
    tools = FakeTools()
    result = IntentEngine(FakeClient(target), tools).handle(TEXT, FLOWS, NOW)
    assert result.error == ""
    assert result.actions == []
    assert [o.kpi for o in result.standing] == ["latency_ms"]
    assert tools.calls == []


def test_a_twin_error_is_kept_as_that_actions_verdict() -> None:
    tools = FakeTools(reply={"error": "twin unavailable"})
    result = IntentEngine(FakeClient(_policy()), tools).handle(TEXT, FLOWS, NOW)
    [action] = result.actions
    assert result.verdicts[action.action_id] == {"error": "twin unavailable"}


@pytest.mark.parametrize("text", ["", "   ", "x" * 1001])
def test_empty_or_overlong_text_is_refused_before_any_call(text: str) -> None:
    client = FakeClient(_policy())
    result = IntentEngine(client, FakeTools()).handle(text, FLOWS, NOW)
    assert "intent" in result.error
    assert client.calls == []


def test_end_to_end_over_the_tool_layer() -> None:
    tools = ToolLayer(MockBackend())  # the real P5.2 tool layer, recorded data
    result = IntentEngine(FakeClient(_policy()), tools).handle(TEXT, FLOWS, NOW)
    [action] = result.actions
    verdict = result.verdicts[action.action_id]
    assert verdict["action_id"] == action.action_id
    assert verdict["accepted"] is True
