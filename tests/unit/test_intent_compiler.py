"""P5.3 deterministic policy compiler (genai/intent/compiler.py): Policy -> actions."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, TypeVar

import pytest

from common.schemas import Policy, RateLimitFlow, SetQosQueue
from genai.intent.compiler import Compiled, CompileError, FlowRef, compile_policy

NOW = datetime(2026, 10, 8, 10, 0, tzinfo=UTC)
FLOWS = [
    FlowRef("sta1-bulk", "bulk", "lab"),
    FlowRef("sta2-bulk", "bulk", "library"),
    FlowRef("sta3-video", "video", "lab"),
    FlowRef("sta4-bulk", "bulk", None),  # a station outside every zone
]


def _policy(
    objectives: list[dict[str, Any]],
    zone: str | None = "lab",
    apps: list[str] | None = None,
    constraints: list[dict[str, Any]] | None = None,
) -> Policy:
    return Policy.model_validate(
        {
            "policy_id": "pol_test",
            "intent_text": "test intent",
            "scope": {"zone": zone, "app_class": apps},
            "objectives": objectives,
            "constraints": constraints or [],
            "created_by": "llm.intent",
        }
    )


T = TypeVar("T", SetQosQueue, RateLimitFlow)


def _only(compiled: Compiled, kind: type[T]) -> list[T]:
    """The compiled actions, all of which must be of type `kind`."""
    assert all(isinstance(a, kind) for a in compiled.actions)
    return [a for a in compiled.actions if isinstance(a, kind)]


def _queues(compiled: Compiled) -> list[SetQosQueue]:
    return _only(compiled, SetQosQueue)


def _limits(compiled: Compiled) -> list[RateLimitFlow]:
    return _only(compiled, RateLimitFlow)


def _priority(value: str) -> dict[str, Any]:
    return {"kpi": "priority", "op": "=", "value": value}


def test_high_priority_puts_the_scope_in_the_priority_queue() -> None:
    compiled = compile_policy(_policy([_priority("high")], apps=["video"]), FLOWS, NOW)
    [action] = compiled.actions
    assert isinstance(action, SetQosQueue)
    assert action.params.queue_id == 1
    assert (action.params.match.zone, action.params.match.app_class) == ("lab", "video")
    assert action.source == "llm.intent"
    assert action.created_at == NOW
    assert "pol_test" in action.reason
    assert compiled.standing == []


def test_low_priority_for_two_app_classes_is_one_action_each() -> None:
    compiled = compile_policy(_policy([_priority("low")], apps=["bulk", "web"]), FLOWS, NOW)
    assert [(a.params.match.app_class, a.params.queue_id) for a in _queues(compiled)] == [
        ("bulk", 2),
        ("web", 2),
    ]
    assert len({a.action_id for a in compiled.actions}) == 2


def test_normal_priority_for_all_traffic_in_a_zone_matches_the_zone_only() -> None:
    [action] = _queues(compile_policy(_policy([_priority("normal")], zone="corridor"), FLOWS, NOW))
    assert (action.params.match.zone, action.params.match.app_class) == ("corridor", None)
    assert action.params.queue_id == 0


def test_a_priority_for_all_traffic_everywhere_changes_nothing() -> None:
    with pytest.raises(CompileError, match="all traffic everywhere"):
        compile_policy(_policy([_priority("high")], zone=None), FLOWS, NOW)


def test_two_different_priorities_conflict() -> None:
    with pytest.raises(CompileError, match="conflicting priorities"):
        compile_policy(_policy([_priority("high"), _priority("low")], apps=["video"]), FLOWS, NOW)


def test_a_throughput_cap_rate_limits_every_matching_flow() -> None:
    cap = {"kpi": "throughput_mbps", "op": "<=", "value": 2}
    compiled = compile_policy(_policy([cap], apps=["bulk"]), FLOWS, NOW)
    [action] = compiled.actions  # sta1-bulk: bulk in the lab; the others are elsewhere or video
    assert isinstance(action, RateLimitFlow)
    assert (action.params.flow_id, action.params.max_mbps) == ("sta1-bulk", 2.0)


def test_a_campus_wide_cap_reaches_flows_outside_every_zone() -> None:
    cap = {"kpi": "throughput_mbps", "op": "<=", "value": 1}
    compiled = compile_policy(_policy([cap], zone=None, apps=["bulk"]), FLOWS, NOW)
    assert sorted(a.params.flow_id for a in _limits(compiled)) == [
        "sta1-bulk",
        "sta2-bulk",
        "sta4-bulk",
    ]


def test_the_strictest_of_two_caps_wins() -> None:
    caps = [
        {"kpi": "throughput_mbps", "op": "<=", "value": 3},
        {"kpi": "throughput_mbps", "op": "<=", "value": 2},
    ]
    [action] = _limits(compile_policy(_policy(caps, apps=["bulk"]), FLOWS, NOW))
    assert action.params.max_mbps == 2.0


def test_a_cap_below_the_rate_limit_bound_is_refused() -> None:
    cap = {"kpi": "throughput_mbps", "op": "<=", "value": 0.5}
    with pytest.raises(CompileError, match=r"1\.0 Mbit/s"):
        compile_policy(_policy([cap], apps=["bulk"]), FLOWS, NOW)


def test_a_cap_with_no_matching_flow_compiles_to_nothing_but_stays_standing() -> None:
    cap = {"kpi": "throughput_mbps", "op": "<=", "value": 2}
    compiled = compile_policy(_policy([cap], zone="corridor", apps=["bulk"]), FLOWS, NOW)
    assert compiled.actions == []
    assert [o.kpi for o in compiled.standing] == ["throughput_mbps"]


def test_kpi_targets_and_constraints_become_no_actions() -> None:
    targets = [
        {"kpi": "latency_ms", "op": "<=", "value": 50},
        {"kpi": "throughput_mbps", "op": ">=", "value": 3},
    ]
    limit = [{"kpi": "loss_pct", "op": "<=", "value": 2, "scope": "all"}]
    compiled = compile_policy(_policy(targets, apps=["video"], constraints=limit), FLOWS, NOW)
    assert compiled.actions == []
    assert [(o.kpi, o.op) for o in compiled.standing] == [
        ("latency_ms", "<="),
        ("throughput_mbps", ">="),
    ]


def test_compiling_twice_gives_the_same_actions() -> None:
    policy = _policy([_priority("high")], apps=["video", "web"])
    assert compile_policy(policy, FLOWS, NOW) == compile_policy(policy, FLOWS, NOW)


def test_naming_every_app_class_everywhere_is_still_all_traffic_everywhere() -> None:
    every = ["video", "web", "bulk"]
    with pytest.raises(CompileError, match="all traffic everywhere"):
        compile_policy(_policy([_priority("high")], zone=None, apps=every), FLOWS, NOW)


def test_naming_every_app_class_in_a_zone_is_one_zone_wide_action() -> None:
    every = ["bulk", "video", "web"]
    [action] = _queues(compile_policy(_policy([_priority("high")], apps=every), FLOWS, NOW))
    assert (action.params.match.zone, action.params.match.app_class) == ("lab", None)
