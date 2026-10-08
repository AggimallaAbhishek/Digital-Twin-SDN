"""P4.4 actuator (controller/executor/actuator.py): AP agent calls, and how to undo them."""

from __future__ import annotations

import urllib.request
from datetime import UTC, datetime
from typing import Any

import pytest

from common.schemas import ACTION_ADAPTER, Action
from controller.executor.actuator import AgentActuator
from twin.state.model import APState, FlowState, StationState, TwinState

TS = datetime(2026, 10, 8, 10, 0, tzinfo=UTC)
STATE = TwinState(
    TS,
    {"ap1": APState("ap1", (0, 0), 1, True, 0.0, 14.0)},
    {
        "sta1": StationState("sta1", (0, 0), "ap1", "lab"),
        "sta2": StationState("sta2", (0, 0), "ap1", "library"),
    },
    {
        "sta1-video": FlowState("sta1-video", "sta1", "video", 0, 0, 0),
        "sta1-bulk": FlowState("sta1-bulk", "sta1", "bulk", 0, 0, 0),
        "sta2-video": FlowState("sta2-video", "sta2", "video", 0, 0, 0),
    },
)


class FakeAgent:
    """Answers GETs from fixed data and records every call."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, Any]] = []
        self.aps = [{"ap": "ap1", "channel": 1, "tx_power_dbm": 14.0}]
        self.qos: dict[str, Any] = {"sta1-video": {"queue_id": 2, "max_mbps": 3.0}}

    def __call__(self, method: str, path: str, body: Any, timeout_s: float) -> Any:
        self.calls.append((method, path, body))
        if path == "/aps":
            return {"aps": self.aps}
        if path == "/qos":
            return {"flows": self.qos}
        return {"ok": True}

    def posts(self) -> list[tuple[str, Any]]:
        return [(path, body) for method, path, body in self.calls if method == "POST"]


def _action(kind: str, params: dict[str, Any]) -> Action:
    return ACTION_ADAPTER.validate_python(
        {
            "action_id": "act_t_1",
            "type": kind,
            "source": "operator",
            "reason": "test",
            "created_at": TS,
            "params": params,
        }
    )


def _round_trip(kind: str, params: dict[str, Any]) -> tuple[FakeAgent, list[tuple[str, Any]]]:
    agent = FakeAgent()
    actuator = AgentActuator("http://vm:8081", transport=agent)
    action = _action(kind, params)
    previous = actuator.apply(action, STATE)
    applied = agent.posts()
    agent.calls.clear()
    actuator.revert(action, previous)
    return agent, applied


def test_steering_reassociates_and_reverts_to_the_old_ap() -> None:
    agent, applied = _round_trip(
        "steer_clients", {"from_ap": "ap1", "to_ap": "ap2", "stations": ["sta1", "sta2"]}
    )
    assert applied == [
        ("/stations/sta1/associate", {"ap": "ap2"}),
        ("/stations/sta2/associate", {"ap": "ap2"}),
    ]
    assert agent.posts() == [
        ("/stations/sta1/associate", {"ap": "ap1"}),
        ("/stations/sta2/associate", {"ap": "ap1"}),
    ]


@pytest.mark.parametrize(
    ("kind", "params", "path", "forward", "back"),
    [
        (
            "set_ap_channel",
            {"ap": "ap1", "channel": 6},
            "/aps/ap1/channel",
            {"channel": 6},
            {"channel": 1},
        ),
        (
            "set_ap_tx_power",
            {"ap": "ap1", "dbm": 12},
            "/aps/ap1/txpower",
            {"dbm": 12.0},
            {"dbm": 14.0},
        ),
        (
            "ap_admin_state",
            {"ap": "ap1", "state": "down"},
            "/aps/ap1/admin",
            {"state": "down"},
            {"state": "up"},
        ),
        (
            "ap_admin_state",
            {"ap": "ap1", "state": "up"},
            "/aps/ap1/admin",
            {"state": "up"},
            {"state": "down"},
        ),
    ],
)
def test_radio_changes_revert_to_the_value_read_before(
    kind: str, params: dict[str, Any], path: str, forward: Any, back: Any
) -> None:
    agent, applied = _round_trip(kind, params)
    assert applied == [(path, forward)]
    assert agent.posts() == [(path, back)]


def test_a_qos_queue_applies_to_the_matching_flows_and_restores_each_old_queue() -> None:
    agent, applied = _round_trip(
        "set_qos_queue", {"match": {"zone": "lab", "app_class": "video"}, "queue_id": 1}
    )
    assert applied == [("/flows/sta1-video/queue", {"queue_id": 1})]  # sta2 is in the library
    assert agent.posts() == [("/flows/sta1-video/queue", {"queue_id": 2})]


def test_a_flow_with_no_qos_yet_goes_back_to_best_effort() -> None:
    agent, applied = _round_trip(
        "set_qos_queue", {"match": {"flow_id": "sta2-video"}, "queue_id": 1}
    )
    assert applied == [("/flows/sta2-video/queue", {"queue_id": 1})]
    assert agent.posts() == [("/flows/sta2-video/queue", {"queue_id": 0})]


@pytest.mark.parametrize(("flow", "before"), [("sta1-video", 3.0), ("sta1-bulk", None)])
def test_a_rate_limit_restores_the_old_limit(flow: str, before: float | None) -> None:
    agent, applied = _round_trip("rate_limit_flow", {"flow_id": flow, "max_mbps": 2})
    assert applied == [(f"/flows/{flow}/limit", {"max_mbps": 2.0})]
    assert agent.posts() == [(f"/flows/{flow}/limit", {"max_mbps": before})]


def test_a_reroute_is_refused() -> None:
    actuator = AgentActuator("http://vm:8081", transport=FakeAgent())
    action = _action("reroute_flow", {"flow_id": "sta1-video", "path": ["s1", "ap1"]})
    with pytest.raises(ValueError, match="deviation #9"):
        actuator.apply(action, STATE)


def test_an_unknown_ap_is_an_error() -> None:
    actuator = AgentActuator("http://vm:8081", transport=FakeAgent())
    with pytest.raises(ValueError, match="ap7"):
        actuator.apply(_action("set_ap_channel", {"ap": "ap7", "channel": 6}), STATE)


def test_only_http_urls_are_used() -> None:
    with pytest.raises(ValueError, match="http"):
        AgentActuator("file:///etc/passwd")


def test_reverting_a_reroute_does_nothing() -> None:  # it can never have been applied
    agent = FakeAgent()
    action = _action("reroute_flow", {"flow_id": "sta1-video", "path": ["s1", "ap1"]})
    AgentActuator("http://vm:8081", transport=agent).revert(action, {})
    assert agent.calls == []


class _Response:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def test_the_http_transport_sends_json_and_parses_the_reply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[urllib.request.Request] = []

    def fake_urlopen(request: urllib.request.Request, timeout: float) -> _Response:
        sent.append(request)
        reply = b'{"aps": [{"ap": "ap1", "channel": 1, "tx_power_dbm": 14.0}]}'
        return _Response(reply if request.get_method() == "GET" else b"")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    actuator = AgentActuator("http://vm:8081/")
    previous = actuator.apply(_action("set_ap_channel", {"ap": "ap1", "channel": 6}), STATE)
    assert previous == {"channel": 1}
    assert [(r.get_method(), r.full_url) for r in sent] == [
        ("GET", "http://vm:8081/aps"),
        ("POST", "http://vm:8081/aps/ap1/channel"),
    ]
    assert sent[1].data == b'{"channel": 6}'
