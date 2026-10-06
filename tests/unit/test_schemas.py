"""P0.6 contracts (common/schemas.py): valid + invalid examples for every schema, and bounds."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, get_args

import pytest
import yaml
from hypothesis import given
from hypothesis import strategies as st
from pydantic import BaseModel, ValidationError

from common import schemas as s

REPO_ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 10, 6, 9, 58, 12, tzinfo=UTC)
META: dict[str, Any] = {"ts": NOW, "scenario_id": "lecture_flash_crowd", "run_id": "run_001"}


def _action(type_: str, params: dict[str, Any], **over: Any) -> dict[str, Any]:
    return {
        "action_id": "act_20261006_095812_001",
        "type": type_,
        "params": params,
        "source": "optimizer.heuristic",
        "reason": "ap1 forecast 92% util",
        "created_at": NOW,
        **over,
    }


KPI: dict[str, Any] = {"throughput_mbps": 412.3, "latency_ms": 31.0, "loss_pct": 0.4, "jain": 0.91}


# ----------------------------------------------------------------------------- telemetry

VALID_TELEMETRY: list[tuple[type[s.TelemetryRecord], dict[str, Any]]] = [
    (
        s.PortStats,
        {
            "dpid": "0000000000000001",
            "port": 2,
            "rx_bytes": 10,
            "tx_bytes": 20,
            "rx_pkts": 1,
            "tx_pkts": 2,
            "rx_dropped": 0,
            "tx_dropped": 0,
            "rx_bps": 800.0,
            "tx_bps": 1600.0,
        },
    ),
    (
        s.FlowStats,
        {
            "dpid": "1",
            "flow_id": "f1",
            "app_class": "video",
            "bytes": 5,
            "pkts": 1,
            "duration_s": 3.5,
            "bps": 10.0,
        },
    ),
    (
        s.APStats,
        {
            "ap": "ap1",
            "channel": 6,
            "n_clients": 7,
            "channel_util": 0.92,
            "tx_power_dbm": 14,
            "retries": 3,
            "noise_dbm": -91,
        },
    ),
    (s.StationStats, {"sta": "sta3", "ap": None, "x": 1.0, "y": 2.0}),
    (
        s.KPIRecord,
        {
            "flow_id": "f1",
            "app_class": "web",
            "throughput_mbps": 3.0,
            "latency_ms": 20.0,
            "jitter_ms": 1.0,
            "loss_pct": 0.5,
        },
    ),
    (s.AlertRecord, {"detector": "iforest", "entity": "ap2", "score": 0.83}),
]


@pytest.mark.parametrize(("model", "fields"), VALID_TELEMETRY)
def test_valid_telemetry(model: type[s.TelemetryRecord], fields: dict[str, Any]) -> None:
    record = model(**META, **fields)
    assert s.MEASUREMENTS[type(record)]  # every record type maps to an InfluxDB measurement


@pytest.mark.parametrize(
    ("model", "fields", "bad"),
    [
        (s.PortStats, VALID_TELEMETRY[0][1], {"rx_bytes": -1}),
        (s.FlowStats, VALID_TELEMETRY[1][1], {"app_class": "voip"}),
        (s.APStats, VALID_TELEMETRY[2][1], {"channel": 3}),
        (s.APStats, VALID_TELEMETRY[2][1], {"channel_util": 1.5}),
        (s.StationStats, VALID_TELEMETRY[3][1], {"sta": "laptop7"}),
        (s.KPIRecord, VALID_TELEMETRY[4][1], {"loss_pct": 101}),
        (s.AlertRecord, VALID_TELEMETRY[5][1], {"surprise": 1}),
    ],
)
def test_invalid_telemetry(
    model: type[BaseModel], fields: dict[str, Any], bad: dict[str, Any]
) -> None:
    with pytest.raises(ValidationError):
        model(**{**META, **fields, **bad})


def test_naive_timestamps_are_rejected() -> None:
    with pytest.raises(ValidationError):
        s.AlertRecord(
            **{**META, "ts": NOW.replace(tzinfo=None)}, detector="d", entity="ap1", score=1
        )


def test_contracts_are_immutable() -> None:
    rec = s.AlertRecord(**META, detector="d", entity="ap1", score=1)
    with pytest.raises(ValidationError):
        rec.score = 2  # mutation is exactly what this test checks


# ----------------------------------------------------------------------------- actions

VALID_ACTIONS: list[tuple[str, dict[str, Any]]] = [
    ("reroute_flow", {"flow_id": "f1", "path": ["ap1", "s1", "s2", "ap2"]}),
    ("set_qos_queue", {"match": {"zone": "lab", "app_class": "video"}, "queue_id": 1}),
    ("rate_limit_flow", {"flow_id": "f9", "max_mbps": 1.0}),
    ("steer_clients", {"from_ap": "ap1", "to_ap": "ap2", "stations": ["sta1", "sta2"]}),
    ("set_ap_tx_power", {"ap": "ap3", "dbm": 20}),
    ("set_ap_channel", {"ap": "ap3", "channel": 11}),
    ("ap_admin_state", {"ap": "ap2", "state": "down"}),
]


@pytest.mark.parametrize(("type_", "params"), VALID_ACTIONS)
def test_valid_actions_parse_to_the_right_class(type_: str, params: dict[str, Any]) -> None:
    action = s.ACTION_ADAPTER.validate_python(_action(type_, params))
    assert action.type == type_
    assert s.impact_of(action) == s.IMPACT[type_]


def test_every_allow_listed_type_has_an_impact_class_and_a_model() -> None:
    assert {t for t, _ in VALID_ACTIONS} == set(s.IMPACT)


@pytest.mark.parametrize(
    ("type_", "params"),
    [
        ("delete_everything", {}),  # not on the allow-list
        ("reroute_flow", {"flow_id": "f1", "path": ["ap1"]}),  # too short
        ("reroute_flow", {"flow_id": "f1", "path": ["ap1", "s1", "ap1"]}),  # loop
        ("set_qos_queue", {"match": {}, "queue_id": 1}),  # empty match
        ("set_qos_queue", {"match": {"zone": "lab"}, "queue_id": 7}),  # unknown queue
        ("set_qos_queue", {"match": {"zone": "gym"}, "queue_id": 1}),  # unknown zone
        ("rate_limit_flow", {"flow_id": "f1", "max_mbps": 0.5}),  # below 1 Mbps
        ("steer_clients", {"from_ap": "ap1", "to_ap": "ap1", "stations": ["sta1"]}),  # same AP
        ("steer_clients", {"from_ap": "ap1", "to_ap": "ap2", "stations": []}),  # nobody
        ("steer_clients", {"from_ap": "ap1", "to_ap": "ap2", "stations": ["sta1", "sta1"]}),
        ("set_ap_tx_power", {"ap": "ap1", "dbm": 4.9}),  # below 5 dBm
        ("set_ap_tx_power", {"ap": "ap1", "dbm": 20.1}),  # above 20 dBm
        ("set_ap_channel", {"ap": "ap1", "channel": 3}),  # overlapping channel
        ("ap_admin_state", {"ap": "ap1", "state": "reboot"}),
        ("set_ap_channel", {"ap": "router1", "channel": 6}),  # not an AP name
    ],
)
def test_invalid_actions_are_rejected(type_: str, params: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        s.ACTION_ADAPTER.validate_python(_action(type_, params))


@pytest.mark.parametrize(
    "over",
    [
        {"action_id": "a1"},  # missing act_ prefix
        {"source": "optimizer.rl"},  # RL is out of scope in v2.1
        {"reason": ""},
        {"created_at": NOW.replace(tzinfo=None)},
        {"target": "ap1"},  # unknown field
    ],
)
def test_invalid_action_envelope_is_rejected(over: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        s.ACTION_ADAPTER.validate_python(_action(*VALID_ACTIONS[5], **over))


@given(st.floats(min_value=5.0, max_value=20.0))
def test_tx_power_inside_bounds_is_accepted(dbm: float) -> None:
    assert s.SetApTxPowerParams(ap="ap1", dbm=dbm).dbm == dbm


@given(
    st.one_of(
        st.floats(max_value=4.999, allow_nan=False),
        st.floats(min_value=20.001, allow_nan=False),
    )
)
def test_tx_power_outside_bounds_is_rejected(dbm: float) -> None:
    with pytest.raises(ValidationError):
        s.SetApTxPowerParams(ap="ap1", dbm=dbm)


@given(st.integers())
def test_only_non_overlapping_channels_are_accepted(channel: int) -> None:
    if channel in (1, 6, 11):
        assert s.SetApChannelParams(ap="ap1", channel=channel).channel == channel
    else:
        with pytest.raises(ValidationError):
            s.SetApChannelParams(ap="ap1", channel=channel)


# ----------------------------------------------------------------------------- policy

POLICY: dict[str, Any] = {
    "policy_id": "pol_lab_video",
    "intent_text": "Give video calls in the lab priority and keep latency under 50 ms.",
    "scope": {"zone": "lab", "app_class": ["video"]},
    "objectives": [
        {"kpi": "latency_ms", "op": "<=", "value": 50},
        {"kpi": "priority", "op": "=", "value": "high"},
    ],
    "constraints": [{"kpi": "loss_pct", "op": "<=", "value": 1, "scope": "all"}],
    "valid": {"from": None, "until": None},
    "created_by": "llm.intent",
}


def test_valid_policy_round_trips_through_json() -> None:
    policy = s.Policy.model_validate(POLICY)
    again = s.Policy.model_validate_json(policy.model_dump_json(by_alias=True))
    assert again == policy


def test_policy_json_schema_is_available_for_structured_llm_output() -> None:
    schema = s.Policy.model_json_schema()
    assert schema["additionalProperties"] is False
    assert {"policy_id", "scope", "objectives", "created_by"} <= set(schema["required"])


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p.update(policy_id="Policy 1"),
        lambda p: p.update(objectives=[]),
        lambda p: p["scope"].update(zone="lab2"),
        lambda p: p["scope"].update(app_class=[]),
        lambda p: p["objectives"].append({"kpi": "priority", "op": "<=", "value": "high"}),
        lambda p: p["objectives"].append({"kpi": "priority", "op": "=", "value": 3}),
        lambda p: p["objectives"].append({"kpi": "latency_ms", "op": "=", "value": 50}),
        lambda p: p["objectives"].append({"kpi": "latency_ms", "op": "<=", "value": "low"}),
        lambda p: p["objectives"].append({"kpi": "latency_ms", "op": "<=", "value": -5}),
        lambda p: p["constraints"].append({"kpi": "loss_pct", "op": "=", "value": 1}),
        lambda p: p.update(valid={"from": NOW, "until": NOW - timedelta(hours=1)}),
        lambda p: p.update(created_by="optimizer.heuristic"),
        lambda p: p.update(extra_field=True),
    ],
)
def test_invalid_policies_are_rejected(mutate: Any) -> None:
    bad = {**POLICY, "scope": dict(POLICY["scope"]), "objectives": list(POLICY["objectives"])}
    bad["constraints"] = list(POLICY["constraints"])
    mutate(bad)
    with pytest.raises(ValidationError):
        s.Policy.model_validate(bad)


def test_policy_validity_window_accepts_ordered_times() -> None:
    p = s.Policy.model_validate({**POLICY, "valid": {"from": NOW, "until": NOW + timedelta(1)}})
    assert p.valid.valid_from == NOW


# ----------------------------------------------------------------------------- verdict

VERDICT: dict[str, Any] = {
    "action_id": "act_1",
    "accepted": True,
    "predicted": KPI,
    "baseline": {**KPI, "latency_ms": 47.5},
    "violations": [],
    "impact": "high",
    "needs_approval": True,
    "sim_mode": "analytical",
    "sim_time_ms": 120,
}


def test_valid_verdict() -> None:
    assert s.Verdict.model_validate(VERDICT).accepted


@pytest.mark.parametrize(
    "over",
    [
        {"violations": ["loss_pct > 1"]},  # accepted with violations
        {"needs_approval": False},  # high impact without approval
        {"predicted": {**KPI, "jain": 1.2}},
        {"sim_mode": "magic"},
    ],
)
def test_invalid_verdicts_are_rejected(over: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        s.Verdict.model_validate({**VERDICT, **over})


def test_rejected_verdict_may_list_violations() -> None:
    v = s.Verdict.model_validate({**VERDICT, "accepted": False, "violations": ["loss_pct > 1"]})
    assert v.violations == ["loss_pct > 1"]


# ----------------------------------------------------------------------------- scenario

SCENARIO: dict[str, Any] = {
    "scenario_id": "lecture_flash_crowd",
    "duration_s": 600,
    "seed": 42,
    "topology": "campus_v1",
    "mobility": {
        "model": "scheduled_crowd",
        "groups": [
            {
                "stations": 10,
                "from": "corridor",
                "to": "lecture_hall",
                "start_s": 120,
                "spread_s": 60,
            }
        ],
    },
    "traffic": [
        {"profile": "video", "stations": "lecture_hall:*", "start_s": 180, "rate_mbps": 3},
        {"profile": "web", "stations": "*"},
    ],
    "events": [{"at_s": 300, "type": "force_channel", "ap": "ap3", "channel": 1}],
    "labels": ["congestion"],
}


def test_valid_scenario() -> None:
    sc = s.Scenario.model_validate(SCENARIO)
    assert sc.mobility.groups[0].to_zone == "lecture_hall"


def test_minimal_static_scenario() -> None:
    sc = s.Scenario.model_validate(
        {"scenario_id": "normal", "duration_s": 60, "seed": 1, "topology": "campus_v1"}
    )
    assert sc.mobility.model == "static"


@pytest.mark.parametrize(
    "over",
    [
        {"duration_s": 0},
        {"mobility": {"model": "static", "groups": SCENARIO["mobility"]["groups"]}},
        {"mobility": {"model": "scheduled_crowd", "groups": []}},
        {
            "mobility": {
                "model": "scheduled_crowd",
                "groups": [{"stations": 1, "from": "lab", "to": "lab", "start_s": 0}],
            }
        },
        {"events": [{"at_s": 10, "type": "force_channel", "ap": "ap3"}]},
        {"events": [{"at_s": 10, "type": "force_channel", "ap": "ap3", "channel": 2}]},
        {"events": [{"at_s": 10, "type": "ap_down", "ap": "ap2", "channel": 6}]},
        {"events": [{"at_s": 900, "type": "ap_down", "ap": "ap2"}]},  # after the end
        {"traffic": [{"profile": "video", "stations": "everyone"}]},
        {"labels": ["chaos"]},
    ],
)
def test_invalid_scenarios_are_rejected(over: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        s.Scenario.model_validate({**SCENARIO, **over})


# ----------------------------------------------------------------------------- contract with config


def test_zone_vocabulary_matches_campus_config() -> None:
    campus = yaml.safe_load((REPO_ROOT / "config" / "campus_v1.yaml").read_text())
    assert set(get_args(s.Zone)) == set(campus["zones"])


def test_campus_ap_channels_are_valid_contract_channels() -> None:
    campus = yaml.safe_load((REPO_ROOT / "config" / "campus_v1.yaml").read_text())
    for ap in campus["aps"]:
        s.SetApChannelParams(ap=ap["name"], channel=ap["channel"])
