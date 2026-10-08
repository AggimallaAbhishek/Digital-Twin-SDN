"""P5.2 LLM tool layer (genai/tools/) against the mock backend (recorded fixtures).

Safety invariants (RULEBOOK L-1, T-5a/c): apply_action refuses any action without an accepted
twin verdict from simulate_in_twin, and high-impact actions until an operator approves them;
the LLM has no tool to approve.
"""

from __future__ import annotations

from typing import Any

import pytest

from common.schemas import Verdict
from genai.tools.mock_backend import MockBackend
from genai.tools.tools import TOOL_NAMES, ToolLayer

STEER = {
    "action_id": "act_test_steer",
    "type": "steer_clients",
    "source": "llm.intent",
    "reason": "ap1 is congested",
    "created_at": "2026-10-08T10:00:00Z",
    "params": {"from_ap": "ap1", "to_ap": "ap3", "stations": ["sta2"]},
}
CHANNEL = {
    **STEER,
    "action_id": "act_test_channel",
    "type": "set_ap_channel",
    "params": {"ap": "ap3", "channel": 11},
}


class SpyBackend(MockBackend):
    """MockBackend that records apply() calls and can be told to reject an action."""

    def __init__(self) -> None:
        super().__init__()
        self.applied: list[str] = []
        self.reject: set[str] = set()

    def simulate(self, action: Any) -> Verdict:
        verdict = super().simulate(action)
        if action.action_id in self.reject:
            return verdict.model_copy(update={"accepted": False, "violations": ["regression"]})
        return verdict

    def apply(self, action_id: str) -> dict[str, Any]:
        self.applied.append(action_id)
        return super().apply(action_id)


@pytest.fixture
def backend() -> SpyBackend:
    return SpyBackend()


@pytest.fixture
def tools(backend: SpyBackend) -> ToolLayer:
    return ToolLayer(backend)


# ------------------------------------------------------------------ what the LLM sees
def test_the_llm_is_offered_exactly_the_five_tools(tools: ToolLayer) -> None:
    specs = tools.specs()
    assert (
        [s["function"]["name"] for s in specs]
        == list(TOOL_NAMES)
        == [
            "get_topology",
            "get_metrics",
            "get_alerts",
            "simulate_in_twin",
            "apply_action",
        ]
    )
    for spec in specs:
        assert spec["type"] == "function"
        assert spec["function"]["description"]
        assert spec["function"]["parameters"]["type"] == "object"


def test_unknown_tools_cannot_be_called(tools: ToolLayer) -> None:
    for name in ("approve_action", "set_channel", "__init__"):
        assert tools.call(name, {}) == {"error": f"unknown tool {name!r}"}


# ------------------------------------------------------------------ reads
def test_topology_lists_the_campus(tools: ToolLayer) -> None:
    topology = tools.call("get_topology", {})
    assert [ap["ap"] for ap in topology["aps"]] == ["ap1", "ap2", "ap3", "ap4"]
    assert len(topology["stations"]) == 20
    assert {"switches", "links"} <= set(topology)


def test_metrics_return_a_series_for_a_flow(tools: ToolLayer) -> None:
    result = tools.call(
        "get_metrics", {"entity": "sta1-video", "metric": "throughput_mbps", "window_s": 60}
    )
    assert result["entity"] == "sta1-video"
    assert result["points"]
    assert all({"ts", "value"} == set(p) for p in result["points"])


@pytest.mark.parametrize(
    "args",
    [
        {"entity": "sta1-video", "metric": "throughput_mbps", "window_s": 0},
        {"entity": "sta1-video", "metric": "rm -rf", "window_s": 60},
        {"entity": "sta1-video", "metric": "throughput_mbps", "window_s": 60, "extra": 1},
        {"metric": "throughput_mbps", "window_s": 60},
    ],
)
def test_bad_arguments_come_back_as_errors_not_exceptions(
    tools: ToolLayer, args: dict[str, Any]
) -> None:
    result = tools.call("get_metrics", args)
    assert set(result) == {"error"}


def test_alerts_are_empty_until_the_detector_exists(tools: ToolLayer) -> None:
    assert tools.call("get_alerts", {"since_s": 300}) == {"alerts": []}


# ------------------------------------------------------------------ simulate
def test_simulate_returns_a_schema_valid_verdict(tools: ToolLayer) -> None:
    result = tools.call("simulate_in_twin", {"action": STEER})
    verdict = Verdict.model_validate(result)
    assert (verdict.action_id, verdict.accepted, verdict.impact) == (
        "act_test_steer",
        True,
        "medium",
    )


def test_an_out_of_bounds_action_is_rejected_before_the_twin(tools: ToolLayer) -> None:
    bad = {**CHANNEL, "params": {"ap": "ap3", "channel": 7}}
    result = tools.call("simulate_in_twin", {"action": bad})
    assert set(result) == {"error"}
    assert tools.call("apply_action", {"action_id": "act_test_channel"})["error"]


# ------------------------------------------------------------------ apply (safety)
def test_an_action_never_simulated_is_refused(tools: ToolLayer, backend: SpyBackend) -> None:
    result = tools.call("apply_action", {"action_id": "act_test_steer"})
    assert "no accepted twin verdict" in result["error"]
    assert backend.applied == []


def test_a_verified_medium_impact_action_is_applied(tools: ToolLayer, backend: SpyBackend) -> None:
    tools.call("simulate_in_twin", {"action": STEER})
    result = tools.call("apply_action", {"action_id": "act_test_steer"})
    assert result["status"] == "applied"
    assert backend.applied == ["act_test_steer"]


def test_a_rejected_verdict_is_refused(tools: ToolLayer, backend: SpyBackend) -> None:
    backend.reject.add("act_test_steer")
    tools.call("simulate_in_twin", {"action": STEER})
    assert (
        "no accepted twin verdict"
        in tools.call("apply_action", {"action_id": "act_test_steer"})["error"]
    )
    assert backend.applied == []


def test_high_impact_needs_an_operator_and_the_llm_cannot_approve(
    tools: ToolLayer, backend: SpyBackend
) -> None:
    verdict = tools.call("simulate_in_twin", {"action": CHANNEL})
    assert verdict["needs_approval"] is True
    refused = tools.call("apply_action", {"action_id": "act_test_channel"})
    assert "operator approval" in refused["error"]
    assert tools.call("approve_action", {"action_id": "act_test_channel"})["error"]
    assert backend.applied == []
    tools.approve("act_test_channel")  # the operator, through the API/dashboard (not a tool)
    assert tools.call("apply_action", {"action_id": "act_test_channel"})["status"] == "applied"


def test_an_action_is_applied_only_once(tools: ToolLayer, backend: SpyBackend) -> None:
    tools.call("simulate_in_twin", {"action": STEER})
    tools.call("apply_action", {"action_id": "act_test_steer"})
    again = tools.call("apply_action", {"action_id": "act_test_steer"})
    assert "already applied" in again["error"]
    assert backend.applied == ["act_test_steer"]


def test_operator_cannot_approve_an_unverified_action(tools: ToolLayer) -> None:
    with pytest.raises(ValueError, match="no accepted twin verdict"):
        tools.approve("act_never_simulated")


def test_an_unknown_entity_has_no_points(tools: ToolLayer) -> None:
    result = tools.call("get_metrics", {"entity": "ap9", "metric": "n_clients", "window_s": 60})
    assert result["points"] == []


def test_the_backend_rechecks_the_verdict_itself() -> None:
    with pytest.raises(ValueError, match="no accepted twin verdict"):
        MockBackend().apply("act_never_simulated")


def test_a_backend_refusal_reaches_the_llm_and_nothing_is_marked_applied() -> None:
    class RefusingBackend(SpyBackend):
        def apply(self, action_id: str) -> dict[str, Any]:
            raise ValueError("executor refused: rate limit")

    tools = ToolLayer(RefusingBackend())
    tools.call("simulate_in_twin", {"action": STEER})
    assert tools.call("apply_action", {"action_id": "act_test_steer"}) == {
        "error": "executor refused: rate limit"
    }
    assert (
        "already applied"
        not in tools.call("apply_action", {"action_id": "act_test_steer"})["error"]
    )
