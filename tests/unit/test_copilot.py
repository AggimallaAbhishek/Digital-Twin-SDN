"""P5.5 copilot (genai/agent/copilot.py): a tool-using agent over the P5.2 tool layer.

The LLM is scripted; the tools are the real ToolLayer over the recorded MockBackend.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import pytest

from genai.agent.copilot import Copilot, CopilotConfig, load_copilot_config
from genai.llm.client import LLMResult, ToolCall, ToolTurn
from genai.tools.mock_backend import MockBackend
from genai.tools.tools import ToolLayer

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
CONFIG = CopilotConfig(
    enabled=True, api_url="http://127.0.0.1:8000", max_steps=4, max_tool_chars=4000
)
STEER = {
    "type": "steer_clients",
    "params": {"from_ap": "ap1", "to_ap": "ap2", "stations": ["sta1"]},
    "reason": "ap1 is congested",
}


class ScriptedLLM:
    """Replies with the given turns in order; records the conversation it was sent each time."""

    def __init__(self, *turns: ToolTurn) -> None:
        self.turns = list(turns)
        self.seen: list[list[dict[str, Any]]] = []
        self.tool_names: list[str] = []

    def complete_tools(
        self,
        messages: Sequence[dict[str, Any]],
        tools: Sequence[dict[str, Any]],
        *,
        prompt_version: str,
    ) -> LLMResult[ToolTurn]:
        self.seen.append([dict(m) for m in messages])
        self.tool_names = [t["function"]["name"] for t in tools]
        return LLMResult(value=self.turns.pop(0), model="scripted", fell_back=False)


def _calls(*calls: tuple[str, dict[str, Any]]) -> ToolTurn:
    return ToolTurn("", [ToolCall(name, args) for name, args in calls])


def _ask(llm: ScriptedLLM, question: str = "Why is ap1 slow?") -> dict[str, Any]:
    copilot = Copilot(llm, ToolLayer(MockBackend()), CONFIG, clock=lambda: NOW)
    return copilot.ask(question)


def test_the_answer_comes_with_the_tool_evidence_behind_it() -> None:
    llm = ScriptedLLM(
        _calls(
            ("get_alerts", {"since_s": 300}),
            ("get_metrics", {"entity": "ap1", "metric": "channel_util", "window_s": 60}),
        ),
        ToolTurn("ap1 is busy: channel_util is high.", []),
    )
    reply = _ask(llm)
    assert reply["answer"] == "ap1 is busy: channel_util is high."
    assert [e["tool"] for e in reply["evidence"]] == ["get_alerts", "get_metrics"]
    assert reply["evidence"][0]["result"] == {"alerts": []}
    assert reply["suggested_actions"] == []
    assert reply["model"] == "scripted"
    assert reply["prompt_version"] == "copilot_v2"  # which prompt answered, for the eval
    # the tool results went back to the model, one tool message per call
    second = llm.seen[1]
    assert [m["role"] for m in second] == ["system", "user", "assistant", "tool", "tool"]
    assert second[2]["tool_calls"][0]["function"] == {
        "name": "get_alerts",
        "arguments": {"since_s": 300},
    }
    assert json.loads(second[3]["content"]) == {"alerts": []}
    assert second[3]["tool_name"] == "get_alerts"


def test_a_proposed_action_is_checked_in_the_twin_and_only_suggested() -> None:
    llm = ScriptedLLM(_calls(("simulate_in_twin", STEER)), ToolTurn("Steer sta1 to ap2.", []))
    reply = _ask(llm)
    [suggested] = reply["suggested_actions"]
    action = suggested["action"]
    # the copilot, not the model, stamps the id, source and time
    assert action["action_id"].startswith("act_copilot_")
    assert (action["source"], action["created_at"]) == ("llm.intent", NOW.isoformat())
    assert action["params"] == STEER["params"]
    assert suggested["verdict"]["accepted"] is True
    assert suggested["verdict"]["action_id"] == action["action_id"]


def test_the_copilot_cannot_apply_anything() -> None:
    llm = ScriptedLLM(_calls(("apply_action", {"action_id": "act_x"})), ToolTurn("done", []))
    reply = _ask(llm)
    assert "apply_action" not in llm.tool_names
    assert llm.tool_names == ["get_topology", "get_metrics", "get_alerts", "simulate_in_twin"]
    assert "unknown tool" in reply["evidence"][0]["result"]["error"]


def test_bad_tool_arguments_go_back_to_the_model_as_an_error() -> None:
    bad = {"type": "set_ap_channel", "params": {"ap": "ap1", "channel": 3}, "reason": "x"}
    llm = ScriptedLLM(_calls(("simulate_in_twin", bad)), ToolTurn("Channel 3 is not allowed.", []))
    reply = _ask(llm)
    assert "error" in reply["evidence"][0]["result"]
    assert reply["suggested_actions"] == []
    assert "error" in json.loads(llm.seen[1][-1]["content"])


def test_a_long_tool_result_is_cut_for_the_model_but_kept_whole_as_evidence() -> None:
    llm = ScriptedLLM(_calls(("get_topology", {})), ToolTurn("ok", []))
    copilot = Copilot(
        llm, ToolLayer(MockBackend()), CopilotConfig(True, "http://x", 4, 100), clock=lambda: NOW
    )
    reply = copilot.ask("What is connected?")
    sent = llm.seen[1][-1]["content"]
    assert len(sent) <= 100 + len(" ...(cut)")
    assert sent.endswith("...(cut)")
    assert "aps" in reply["evidence"][0]["result"]


def test_it_stops_after_max_steps() -> None:
    llm = ScriptedLLM(*[_calls(("get_alerts", {"since_s": 60}))] * CONFIG.max_steps)
    reply = _ask(llm)
    assert len(reply["evidence"]) == CONFIG.max_steps
    assert "could not finish" in reply["answer"]


def test_config_loads() -> None:
    config = load_copilot_config(
        {
            "enabled": False,
            "api_url": "http://127.0.0.1:8000",
            "max_steps": 6,
            "max_tool_chars": 6000,
        }
    )
    assert config == CopilotConfig(False, "http://127.0.0.1:8000", 6, 6000)


@pytest.mark.parametrize(
    "change",
    [
        {"enabled": "yes"},
        {"api_url": "file:///x"},
        {"max_steps": 0},
        {"max_tool_chars": 10},
        {"extra": 1},
    ],
)
def test_bad_config_is_refused(change: dict[str, Any]) -> None:
    raw = {
        "enabled": False,
        "api_url": "http://127.0.0.1:8000",
        "max_steps": 6,
        "max_tool_chars": 6000,
    }
    with pytest.raises(ValueError, match=next(iter(change))):  # the error names the bad key
        load_copilot_config(raw | change)
