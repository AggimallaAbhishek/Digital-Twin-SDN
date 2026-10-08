"""P4.4a testbed QoS (testbed/qos.py): which tc commands enforce queues and rate limits."""

from __future__ import annotations

import pytest

from testbed.interference import tc_commands
from testbed.qos import FlowQos, FlowRule, flow_rules, tc_tree

ENDPOINTS = {  # flow_id -> (station IP, srv1 source port)
    "sta1-video": ("10.0.0.1", 5201),
    "sta1-bulk": ("10.0.0.1", 5202),
    "sta2-web": ("10.0.0.2", 8000),
}


def test_without_rules_the_tree_is_the_interference_cap_alone() -> None:
    assert tc_tree("ap1-wlan1", 3.45, 4.6, []) == tc_commands("ap1-wlan1", 3.45)
    assert tc_tree("ap1-wlan1", None, 4.6, []) == tc_commands("ap1-wlan1", None)


def test_flow_rules_carry_queue_limit_and_a_ping_rule_per_station() -> None:
    qos = {"sta1-video": FlowQos(queue_id=1), "sta1-bulk": FlowQos(queue_id=2, limit_mbps=1.5)}
    assert flow_rules(qos, ENDPOINTS) == [
        FlowRule("sta1-bulk", "10.0.0.1", 5202, queue_id=2, limit_mbps=1.5),
        FlowRule("sta1-video", "10.0.0.1", 5201, queue_id=1, limit_mbps=None),
        # the station's ping replies share its highest-priority flow's queue (decision P4.4a-A)
        FlowRule("ping-10.0.0.1", "10.0.0.1", None, queue_id=1, limit_mbps=None),
    ]


def test_best_effort_without_a_limit_needs_no_rule() -> None:
    assert flow_rules({"sta2-web": FlowQos(queue_id=0)}, ENDPOINTS) == []


def test_a_flow_without_a_known_endpoint_is_skipped() -> None:
    # not started yet: the agent re-renders when traffic starts
    assert flow_rules({"sta9-video": FlowQos(queue_id=1)}, ENDPOINTS) == []


def test_the_tree_has_three_priority_classes_under_the_cap() -> None:
    rules = [FlowRule("sta1-video", "10.0.0.1", 5201, queue_id=1, limit_mbps=None)]
    commands = tc_tree("ap1-wlan1", None, 4.6, rules)
    dev = "dev ap1-wlan1"
    assert commands[:3] == [
        f"tc qdisc del {dev} root",
        f"tc qdisc add {dev} root handle 1: htb default 21",
        f"tc class add {dev} parent 1: classid 1:1 htb rate 4.6mbit ceil 4.6mbit",
    ]
    # queue 1 -> 1:10 (htb prio 0), queue 0 -> 1:20 (prio 1), queue 2 -> 1:30 (prio 2); each
    # holds its unlimited traffic in a leaf 1:x1 (an HTB class with children can't hold packets)
    for minor, prio in ((10, 0), (20, 1), (30, 2)):
        assert (
            f"tc class add {dev} parent 1:1 classid 1:{minor} htb rate 8kbit ceil 4.6mbit "
            f"prio {prio}" in commands
        )
        assert (
            f"tc class add {dev} parent 1:{minor} classid 1:{minor + 1} htb rate 8kbit "
            f"ceil 4.6mbit prio {prio}" in commands
        )
        assert f"tc qdisc add {dev} parent 1:{minor + 1} handle {minor + 1}: fq_codel" in commands
    assert commands[-1] == (
        f"tc filter add {dev} parent 1: protocol ip prio 1 u32 "
        "match ip dst 10.0.0.1/32 match ip sport 5201 0xffff flowid 1:11"
    )


def test_a_rate_limit_gets_its_own_class_under_its_queue() -> None:
    rules = [FlowRule("sta1-bulk", "10.0.0.1", 5202, queue_id=2, limit_mbps=1.5)]
    commands = tc_tree("ap2-wlan1", 2.3, 4.6, rules)
    dev = "dev ap2-wlan1"
    assert f"tc class add {dev} parent 1: classid 1:1 htb rate 2.3mbit ceil 2.3mbit" in commands
    assert f"tc class add {dev} parent 1:30 classid 1:101 htb rate 8kbit ceil 1.5mbit prio 2" in (
        commands
    )
    assert commands[-1].endswith("match ip sport 5202 0xffff flowid 1:101")


def test_a_ping_rule_matches_icmp_to_the_station() -> None:
    rules = [FlowRule("ping-10.0.0.1", "10.0.0.1", None, queue_id=1, limit_mbps=None)]
    assert tc_tree("ap1-wlan1", None, 4.6, rules)[-1] == (
        "tc filter add dev ap1-wlan1 parent 1: protocol ip prio 1 u32 "
        "match ip dst 10.0.0.1/32 match ip protocol 1 0xff flowid 1:11"
    )


@pytest.mark.parametrize("queue", [-1, 3])
def test_an_unknown_queue_is_refused(queue: int) -> None:
    with pytest.raises(ValueError, match="queue_id"):
        FlowQos(queue_id=queue)


def test_a_limit_below_the_minimum_is_refused() -> None:
    with pytest.raises(ValueError, match="limit_mbps"):
        FlowQos(queue_id=0, limit_mbps=0.5)
