"""P3.4 verifier (twin/verify/verifier.py): accept, reject-regression, reject-policy, approval.

Worked example values are computed by hand from the P3.3 model (config/sim.yaml numbers).
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml

from common.schemas import ACTION_ADAPTER, Action, Policy
from twin.radio import RadioParams
from twin.sim.analytical import load_sim_params
from twin.state.builder import CampusAPs
from twin.state.model import APState, FlowState, StationState, TwinState
from twin.verify.verifier import VerifyContext, load_verify_config, verify

ROOT = Path(__file__).resolve().parents[2]
TS = datetime(2026, 10, 8, 10, 0, tzinfo=UTC)
RADIO = RadioParams(4.6, 30.0, 60.0, -16.0, 4.0)
CAMPUS = CampusAPs(
    positions={"ap1": (0.0, 0.0), "ap2": (20.0, 0.0), "ap3": (100.0, 0.0)},
    channels={"ap1": 1, "ap2": 6, "ap3": 11},
    zones={"lab": ((-5.0, 25.0), (-5.0, 5.0)), "library": ((90.0, 110.0), (-5.0, 5.0))},
)
CONTEXT = VerifyContext(
    campus=CAMPUS,
    radio=RADIO,
    sim=load_sim_params(yaml.safe_load((ROOT / "config" / "sim.yaml").read_text())),
    config=load_verify_config(yaml.safe_load((ROOT / "config" / "verify.yaml").read_text())),
)


def _state(
    clients: Mapping[str, str | None],
    channels: dict[str, int] | None = None,
    zones: dict[str, str] | None = None,
    up: dict[str, bool] | None = None,
    tx: float | None = 14.0,
) -> TwinState:
    channels = channels or CAMPUS.channels
    aps = {
        n: APState(n, p, channels[n], (up or {}).get(n, True), 0.0, tx)
        for n, p in CAMPUS.positions.items()
    }
    stations = {
        s: StationState(s, (5.0, 0.0), ap, (zones or {}).get(s, "lab")) for s, ap in clients.items()
    }
    flows = {f"{s}-video": FlowState(f"{s}-video", s, "video", 0, 0, 0) for s in clients}
    return TwinState(TS, aps, stations, flows)


def _action(kind: str, params: dict[str, Any], n: int = 1) -> Action:
    return ACTION_ADAPTER.validate_python(
        {
            "action_id": f"act_test_{n}",
            "type": kind,
            "source": "operator",
            "reason": "test",
            "created_at": TS,
            "params": params,
        }
    )


CROWDED = {f"sta{i}": "ap1" for i in range(1, 7)}  # 6 video flows on ap1: 6 > 4.6 Mbit/s
STEER_ONE = _action("steer_clients", {"from_ap": "ap1", "to_ap": "ap2", "stations": ["sta1"]})


def test_a_steer_that_relieves_a_crowded_ap_is_accepted_with_its_kpis() -> None:
    [verdict] = verify(_state(CROWDED), [STEER_ONE], CONTEXT)
    assert verdict.accepted
    assert verdict.violations == []
    # all 6 flows change. Before: 4.6/6 each, rho 6/4.6 -> 10.8126 ms, loss 23.533%
    assert verdict.baseline.throughput_mbps == pytest.approx(0.76667, abs=1e-4)
    assert verdict.baseline.latency_ms == pytest.approx(10.8126, abs=1e-4)
    assert verdict.baseline.loss_pct == pytest.approx(23.5333, abs=1e-4)
    assert verdict.baseline.jain == pytest.approx(1 / 3)  # clients 6, 0, 0: 36 / (3 * 36)
    # after: 5 x 0.92 + 1 x 1.0; p95 (nearest rank, 6 flows) = ap1's 9.1290 ms
    assert verdict.predicted.throughput_mbps == pytest.approx(0.93333, abs=1e-4)
    assert verdict.predicted.latency_ms == pytest.approx(9.1290, abs=1e-4)
    assert verdict.predicted.loss_pct == pytest.approx(6.8667, abs=1e-4)
    assert verdict.predicted.jain == pytest.approx(36 / 78)  # clients 5, 1, 0
    assert verdict.sim_mode == "analytical"
    assert verdict.impact == "medium"
    assert not verdict.needs_approval  # steering is validated (P3.5): config/verify.yaml


def test_moving_onto_a_neighbours_channel_is_rejected_as_a_regression() -> None:
    # ap2 (20 m away) joins ap1's channel: both get 4.6 / 2 = 2.3 Mbit/s; nothing improves
    clients = {"sta1": "ap1", "sta2": "ap1", "sta3": "ap2", "sta4": "ap2"}
    action = _action("set_ap_channel", {"ap": "ap2", "channel": 1})
    [verdict] = verify(_state(clients), [action], CONTEXT)
    assert not verdict.accepted
    assert any("latency_ms" in v and "worse" in v for v in verdict.violations)
    assert verdict.impact == "high"
    assert verdict.needs_approval


def test_an_action_that_changes_nothing_is_accepted() -> None:
    action = _action("set_ap_tx_power", {"ap": "ap1", "dbm": 15})
    [verdict] = verify(_state(CROWDED), [action], CONTEXT)
    assert verdict.accepted
    assert verdict.baseline == verdict.predicted


def _policy(raw: dict[str, Any]) -> Policy:
    base = {
        "policy_id": "pol_test",
        "intent_text": "test",
        "scope": {"zone": "library", "app_class": ["video"]},
        "objectives": [{"kpi": "priority", "op": "=", "value": "high"}],
        "created_by": "operator",
    }
    return Policy.model_validate(base | raw)


def test_breaking_a_hard_constraint_is_rejected_even_if_kpis_improve() -> None:
    # ap2's two library flows have 2.67 ms; a steered third flow pushes them to 4.56 ms
    clients = {**CROWDED, "sta7": "ap2", "sta8": "ap2"}
    zones = {"sta7": "library", "sta8": "library"}
    limit = {"constraints": [{"kpi": "latency_ms", "op": "<=", "value": 3, "scope": "policy"}]}
    context = CONTEXT.with_policies([_policy(limit)])
    [verdict] = verify(_state(clients, zones=zones), [STEER_ONE], context)
    assert not verdict.accepted
    assert any("pol_test" in v and "latency_ms <= 3" in v for v in verdict.violations)


def test_a_constraint_already_broken_does_not_block_an_action_that_does_not_worsen_it() -> None:
    limit = {"constraints": [{"kpi": "loss_pct", "op": "<=", "value": 1, "scope": "all"}]}
    [verdict] = verify(_state(CROWDED), [STEER_ONE], CONTEXT.with_policies([_policy(limit)]))
    assert verdict.accepted  # loss is 23.5% before and 6.9% after: broken, but better


def test_missing_a_met_objective_is_rejected() -> None:
    clients = {**CROWDED, "sta7": "ap2", "sta8": "ap2"}
    zones = {"sta7": "library", "sta8": "library"}
    target = {"objectives": [{"kpi": "throughput_mbps", "op": ">=", "value": 0.99}]}
    many = _action(
        "steer_clients", {"from_ap": "ap1", "to_ap": "ap2", "stations": ["sta1"]}
    )  # 3 flows on ap2 still fit: objective stays met
    [verdict] = verify(
        _state(clients, zones=zones), [many], CONTEXT.with_policies([_policy(target)])
    )
    assert verdict.accepted
    crowded_ap2 = {**{f"sta{i}": "ap2" for i in range(9, 12)}, "sta7": "ap2"}
    move = _action("steer_clients", {"from_ap": "ap1", "to_ap": "ap2", "stations": ["sta1"]})
    state = _state({**CROWDED, **crowded_ap2}, zones={"sta7": "library"})
    [verdict] = verify(state, [move], CONTEXT.with_policies([_policy(target)]))
    assert not verdict.accepted  # ap2: 4 -> 5 flows, 0.92 each: below the 0.99 target
    assert any("throughput_mbps >= 0.99" in v for v in verdict.violations)


@pytest.mark.parametrize(
    ("kind", "params", "message"),
    [
        (
            "steer_clients",
            {"from_ap": "ap1", "to_ap": "ap2", "stations": ["sta1", "sta2"]},
            "30%",
        ),
        ("steer_clients", {"from_ap": "ap1", "to_ap": "ap3", "stations": ["sta1"]}, "-75"),
        ("steer_clients", {"from_ap": "ap2", "to_ap": "ap1", "stations": ["sta1"]}, "not on"),
        ("set_ap_tx_power", {"ap": "ap1", "dbm": 18}, "3 dB"),
        ("ap_admin_state", {"ap": "ap3", "state": "down"}, "last AP"),
        ("reroute_flow", {"flow_id": "sta1-video", "path": ["s1", "ap1"]}, "one path"),
        ("set_ap_channel", {"ap": "ap9", "channel": 6}, "unknown AP"),
        ("steer_clients", {"from_ap": "ap1", "to_ap": "ap9", "stations": ["sta1"]}, "unknown AP"),
        ("steer_clients", {"from_ap": "ap1", "to_ap": "ap2", "stations": ["sta99"]}, "not on"),
        ("ap_admin_state", {"ap": "ap9", "state": "down"}, "unknown AP"),
    ],
)
def test_actions_outside_their_bounds_are_rejected_before_simulation(
    kind: str, params: dict[str, Any], message: str
) -> None:
    [verdict] = verify(_state(CROWDED), [_action(kind, params)], CONTEXT)
    assert not verdict.accepted
    assert any(message in v for v in verdict.violations)


def test_an_unknown_tx_power_has_no_step_to_check() -> None:
    action = _action("set_ap_tx_power", {"ap": "ap1", "dbm": 18})
    [verdict] = verify(_state(CROWDED, tx=None), [action], CONTEXT)
    assert verdict.accepted


def test_taking_down_an_ap_its_zone_still_has_another_for_is_allowed_by_the_bounds() -> None:
    # ap1 and ap2 both cover the lab: ap1 may go down (the KPI rule still judges it)
    action = _action("ap_admin_state", {"ap": "ap1", "state": "down"})
    [verdict] = verify(_state({"sta1": "ap1"}), [action], CONTEXT)
    assert not any("last AP" in v for v in verdict.violations)


def test_a_policys_actions_are_verified_together() -> None:
    # a tx power change (no KPI effect) and a steer: one simulation of both, one verdict each
    channel = _action("set_ap_tx_power", {"ap": "ap2", "dbm": 15}, n=1)
    both = [channel, _action("steer_clients", STEER_ONE.params.model_dump(by_alias=True), n=2)]
    verdicts = verify(_state(CROWDED), both, CONTEXT)
    assert [v.action_id for v in verdicts] == ["act_test_1", "act_test_2"]
    assert all(v.accepted for v in verdicts)
    assert verdicts[0].predicted == verdicts[1].predicted  # one joint prediction
    assert [v.impact for v in verdicts] == ["medium", "medium"]


def test_one_bad_action_rejects_the_whole_set() -> None:
    bad = _action("set_ap_tx_power", {"ap": "ap1", "dbm": 20}, n=2)  # 14 -> 20: 6 dB step
    verdicts = verify(_state(CROWDED), [STEER_ONE, bad], CONTEXT)
    assert not any(v.accepted for v in verdicts)
    assert all(any("3 dB" in x for x in v.violations) for v in verdicts)


def test_low_impact_actions_need_no_approval() -> None:
    action = _action("set_qos_queue", {"match": {"zone": "lab"}, "queue_id": 1})
    [verdict] = verify(_state(CROWDED), [action], CONTEXT)
    assert (verdict.impact, verdict.needs_approval) == ("low", False)


def test_a_medium_type_off_the_auto_apply_list_needs_approval() -> None:
    config = load_verify_config({"medium_auto_apply": ["set_ap_tx_power"]})
    context = VerifyContext(CAMPUS, RADIO, CONTEXT.sim, config)
    [verdict] = verify(_state(CROWDED), [STEER_ONE], context)
    assert (verdict.impact, verdict.needs_approval) == ("medium", True)


def test_the_shipped_config_auto_applies_the_types_validated_in_p35() -> None:
    assert CONTEXT.config.medium_auto_apply == {
        "steer_clients",
        "rate_limit_flow",
        "set_ap_tx_power",
    }


@pytest.mark.parametrize(
    "raw",
    [
        {},
        {"medium_auto_apply": "steer_clients"},
        {"medium_auto_apply": ["set_ap_channel"]},  # high impact: always needs approval
        {"medium_auto_apply": ["steer_clients"], "x": 1},
    ],
)
def test_a_bad_verify_config_is_refused(raw: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="verify config"):
        load_verify_config(raw)


def test_no_actions_is_an_error() -> None:
    with pytest.raises(ValueError, match="no actions"):
        verify(_state(CROWDED), [], CONTEXT)


def test_bringing_a_down_ap_back_up_revives_its_flows() -> None:
    # sta1 is on ap3 while ap3 is down: its flow is dead (0 Mbit/s) and comes back
    state = _state({"sta1": "ap3"}, up={"ap3": False})
    action = _action("ap_admin_state", {"ap": "ap3", "state": "up"})
    [verdict] = verify(state, [action], CONTEXT)
    assert verdict.baseline.throughput_mbps == 0.0
    assert verdict.predicted.throughput_mbps == pytest.approx(1.0)
    assert verdict.accepted


def test_a_policy_with_no_flows_in_scope_checks_nothing() -> None:
    corridor = _policy(
        {
            "scope": {"zone": "corridor", "app_class": None},
            "constraints": [{"kpi": "latency_ms", "op": "<=", "value": 0.1, "scope": "policy"}],
            "objectives": [{"kpi": "jitter_ms", "op": "<=", "value": 1}],
        }
    )
    [verdict] = verify(_state(CROWDED), [STEER_ONE], CONTEXT.with_policies([corridor]))
    assert verdict.accepted
