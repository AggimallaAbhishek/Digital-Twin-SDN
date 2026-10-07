"""P1.2 controller logic (controller/apps/ryu_logic.py): request validation, cookies, rates."""

from typing import Any

import pytest

from controller.apps.ryu_logic import (
    FlowSpec,
    dpid_str,
    flow_cookie,
    is_ours,
    parse_flow_request,
    parse_qos_request,
    rate_bps,
)

FLOW: dict[str, Any] = {
    "flow_id": "block_sta1_srv1",
    "dpid": "1000000000000001",
    "priority": 200,
    "match": {"ipv4_src": "10.0.0.1", "ipv4_dst": "10.0.1.1"},
    "actions": [{"drop": True}],
}


def test_dpid_str_is_16_hex_digits() -> None:
    assert dpid_str(1) == "0000000000000001"
    assert dpid_str(0x1000000000000001) == "1000000000000001"


def test_flow_cookie_is_stable_tagged_and_distinct() -> None:
    a, b = flow_cookie("f1"), flow_cookie("f2")
    assert a == flow_cookie("f1")
    assert a != b
    assert is_ours(a)
    assert is_ours(b)
    assert not is_ours(0)  # cookie 0 = learned L2 flows
    assert 0 < a < 2**64


def test_parse_flow_request_valid_drop_adds_ipv4_prerequisite() -> None:
    spec = parse_flow_request(FLOW)
    assert isinstance(spec, FlowSpec)
    assert spec.dpid == 0x1000000000000001
    assert spec.priority == 200
    assert spec.match == {"ipv4_src": "10.0.0.1", "ipv4_dst": "10.0.1.1", "eth_type": 0x0800}
    assert spec.actions == [("drop", 0)]
    assert spec.cookie == flow_cookie("block_sta1_srv1")


@pytest.mark.parametrize(
    ("actions", "expected"),
    [
        ([{"output": 3}], [("output", 3)]),
        ([{"output": "normal"}], [("output", "normal")]),
        ([{"queue": 1}, {"output": 2}], [("queue", 1), ("output", 2)]),
    ],
)
def test_parse_flow_request_actions(actions: list[Any], expected: list[Any]) -> None:
    spec = parse_flow_request({**FLOW, "actions": actions})
    assert spec.actions == expected


def test_parse_flow_request_defaults() -> None:
    spec = parse_flow_request(
        {"flow_id": "f", "dpid": 1, "match": {"in_port": 1}, "actions": [{"output": 2}]}
    )
    assert spec.priority == 100
    assert spec.idle_timeout == 0
    assert spec.hard_timeout == 0


def test_ip_proto_adds_ipv4_eth_type() -> None:
    spec = parse_flow_request({**FLOW, "match": {"ip_proto": 6}})
    assert spec.match == {"ip_proto": 6, "eth_type": 0x0800}


@pytest.mark.parametrize(
    ("over", "message"),
    [
        ({"flow_id": "bad id!"}, "flow_id"),
        ({"flow_id": ""}, "flow_id"),
        ({"dpid": "xyz"}, "dpid"),
        ({"dpid": -1}, "dpid"),
        ({"priority": 0}, "priority"),
        ({"priority": 70000}, "priority"),
        ({"match": {}}, "match"),
        ({"match": {"vlan": 3}}, "unknown match field"),
        ({"match": {"in_port": "one"}}, "in_port"),
        ({"match": {"ipv4_dst": "10.0.0"}}, "ipv4_dst"),
        ({"match": {"eth_dst": "zz:zz"}}, "eth_dst"),
        ({"match": {"ip_proto": 300}}, "ip_proto"),
        ({"actions": []}, "actions"),
        ({"actions": [{"teleport": 1}]}, "unknown action"),
        ({"actions": [{"output": 0}]}, "output"),
        ({"actions": [{"output": "flood"}]}, "output"),
        ({"actions": [{"queue": 7}, {"output": 1}]}, "queue"),
        ({"actions": [{"queue": 1}]}, "queue"),
        ({"actions": [{"drop": True}, {"output": 1}]}, "drop"),
        ({"actions": [{"output": 1, "queue": 1}]}, "exactly one"),
        ({"idle_timeout": -5}, "idle_timeout"),
        ({"surprise": 1}, "unknown field"),
    ],
)
def test_parse_flow_request_rejects(over: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        parse_flow_request({**FLOW, **over})


def test_parse_flow_request_requires_fields() -> None:
    with pytest.raises(ValueError, match="missing"):
        parse_flow_request({"flow_id": "f"})


def test_parse_qos_request() -> None:
    spec = parse_qos_request(
        {
            "flow_id": "lab_video_q1",
            "dpid": "1",
            "match": {"ipv4_src": "10.0.0.5"},
            "queue_id": 1,
            "out_port": 3,
        }
    )
    assert spec.actions == [("queue", 1), ("output", 3)]
    assert spec.priority == 150


def test_parse_qos_request_rejects_unknown_queue() -> None:
    with pytest.raises(ValueError, match="queue"):
        parse_qos_request(
            {"flow_id": "q", "dpid": 1, "match": {"in_port": 1}, "queue_id": 9, "out_port": 2}
        )


@pytest.mark.parametrize(
    ("prev", "now", "expected"),
    [
        ((1000, 10.0), (2000, 11.0), 8000.0),  # 1000 bytes in 1 s = 8 kbit/s
        ((1000, 10.0), (1000, 12.0), 0.0),
        ((5000, 10.0), (100, 11.0), 0.0),  # counter reset (switch restart) -> 0, not negative
        ((1000, 10.0), (2000, 10.0), 0.0),  # zero interval -> 0, no division by zero
        (None, (2000, 11.0), 0.0),  # first sample
    ],
)
def test_rate_bps(prev: tuple[int, float] | None, now: tuple[int, float], expected: float) -> None:
    assert rate_bps(prev, now) == expected


def test_body_must_be_an_object() -> None:
    with pytest.raises(ValueError, match="JSON object"):
        parse_flow_request(["not", "an", "object"])  # type: ignore[arg-type]  # bad input on purpose


def test_mac_match_is_normalised_to_lowercase() -> None:
    spec = parse_flow_request({**FLOW, "match": {"eth_dst": "02:00:00:00:0A:FF"}})
    assert spec.match == {"eth_dst": "02:00:00:00:0a:ff"}


def test_explicit_eth_type_is_kept() -> None:
    spec = parse_flow_request({**FLOW, "match": {"eth_type": 0x0806}})
    assert spec.match == {"eth_type": 0x0806}


def test_drop_must_be_true() -> None:
    with pytest.raises(ValueError, match="drop must be true"):
        parse_flow_request({**FLOW, "actions": [{"drop": False}]})
