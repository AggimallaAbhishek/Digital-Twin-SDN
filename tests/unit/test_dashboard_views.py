"""P6.1 dashboard view logic (dashboard/views.py): API JSON -> what each panel shows."""

from __future__ import annotations

from typing import Any

import pytest

from dashboard.views import (
    COVERAGE_M,
    LoadBand,
    decision_queue,
    describe,
    kpi_series,
    load_band,
    map_layers,
    twin_vs_live,
    verdict_word,
)

TOPOLOGY: dict[str, Any] = {
    "ts": "2026-10-10T12:00:00+00:00",
    "aps": [
        {"name": "ap1", "position": [20, 50], "channel": 1, "up": True, "util": 0.93},
        {"name": "ap2", "position": [60, 50], "channel": 6, "up": False, "util": 0.0},
        {"name": "ap3", "position": [20, 20], "channel": 1, "up": True, "util": 0.4},
    ],
    "stations": [
        {"name": "sta1", "position": [21, 48], "ap": "ap1", "zone": "lecture_hall"},
        {"name": "sta2", "position": [22, 52], "ap": "ap1", "zone": "lecture_hall"},
        {"name": "sta4", "position": [58, 49], "ap": None, "zone": "lab"},
    ],
    "flows": [],
}


def test_load_bands_follow_the_congestion_threshold() -> None:
    # P4.5-A: utilisation of 0.8 or more is congested
    assert load_band(0.3) == LoadBand("calm", "under 60%")
    assert load_band(0.6).name == "busy"
    assert load_band(0.8).name == "congested"
    assert load_band(1.0).name == "congested"


def test_the_map_shows_aps_by_channel_and_load_and_stations_by_association() -> None:
    aps, stations = map_layers(TOPOLOGY)
    ap1 = next(a for a in aps if a["name"] == "ap1")
    assert (ap1["x"], ap1["y"], ap1["channel"], ap1["clients"]) == (20, 50, "ch 1", 2)
    assert (ap1["load"], ap1["band"]) == (0.93, "congested")
    assert ap1["label"] == "ap1 · ch 1 · 93% · 2 clients"
    ap2 = next(a for a in aps if a["name"] == "ap2")
    assert (ap2["band"], ap2["label"]) == ("down", "ap2 · ch 6 · down")
    # co-channel: ap1 and ap3 share channel 1 and are 30 m apart, inside each other's rings
    assert next(a for a in aps if a["name"] == "ap3")["shares_channel_with"] == ["ap1"]
    assert ap1["shares_channel_with"] == ["ap3"]
    assert ap1["coverage_m"] == COVERAGE_M
    assert {s["name"]: s["ap"] for s in stations} == {
        "sta1": "ap1",
        "sta2": "ap1",
        "sta4": "no AP",
    }


PARAMS = {
    "set_ap_channel": {"ap": "ap3", "channel": 11},
    "steer_clients": {"from_ap": "ap1", "to_ap": "ap3", "stations": ["sta1", "sta2"]},
}


def _record(n: int, status: str, kind: str = "set_ap_channel", **extra: Any) -> dict[str, Any]:
    return {
        "action_id": f"act_{n}",
        "group_id": f"act_{n}",
        "status": status,
        "action": {
            "type": kind,
            "params": PARAMS[kind],
            "reason": "r",
            "source": "llm.intent",
        },
        "verdict": {
            "accepted": status != "rejected",
            "needs_approval": kind == "set_ap_channel",
            "impact": "high" if kind == "set_ap_channel" else "medium",
            "predicted": {"throughput_mbps": 1.3, "latency_ms": 5.0, "loss_pct": 0.2, "jain": 0.9},
            "baseline": {"throughput_mbps": 1.1, "latency_ms": 9.0, "loss_pct": 14.0, "jain": 0.8},
        },
        "approved_by": None,
        "applied_at": None,
        "note": "",
        "measured": None,
    } | extra


def test_the_queue_holds_what_waits_for_an_operator_and_what_can_be_applied() -> None:
    actions = [
        _record(1, "verified"),  # needs approval
        _record(2, "approved", approved_by="abhishek"),  # approved, not yet applied
        _record(3, "verified", kind="steer_clients"),  # needs no approval: the loop applies it
        _record(4, "rejected"),
        _record(5, "kept", applied_at="2026-10-10T12:00:00+00:00"),
        _record(6, "denied", note="by abhishek"),
    ]
    queue = decision_queue(actions)
    assert [(q["action_id"], q["next_step"]) for q in queue] == [
        ("act_1", "approve"),
        ("act_2", "apply"),
    ]
    assert queue[0]["what"] == "set_ap_channel ap3 → channel 11"
    assert queue[0]["twin"] == "accepted · loss 14.0% → 0.2% · latency 9.0 → 5.0 ms"


def test_twin_vs_live_pairs_each_watched_action_with_its_prediction() -> None:
    measured = {"throughput_mbps": 1.2, "latency_ms": 6.0, "loss_pct": 0.5, "jain": 0.88}
    actions = [
        _record(5, "kept", kind="steer_clients", measured=measured),
        _record(6, "verified"),  # no measurement yet
    ]
    rows = twin_vs_live(actions)
    assert [
        (r["action"], r["kpi"], r["source"], r["value"]) for r in rows if r["kpi"] == "loss %"
    ] == [
        ("act_5", "loss %", "before", 14.0),
        ("act_5", "loss %", "twin predicted", 0.2),
        ("act_5", "loss %", "measured", 0.5),
    ]
    assert {r["kpi"] for r in rows} == {"throughput Mbit/s", "latency ms", "loss %"}
    assert all(r["outcome"] == "kept" for r in rows)


@pytest.mark.parametrize(
    ("kind", "params", "line"),
    [
        ("set_ap_tx_power", {"ap": "ap1", "dbm": 11}, "set_ap_tx_power ap1 → 11 dBm"),
        ("ap_admin_state", {"ap": "ap2", "state": "up"}, "ap_admin_state ap2 → up"),
        (
            "rate_limit_flow",
            {"flow_id": "sta1-video", "max_mbps": 2},
            "rate_limit_flow flow_id=sta1-video, max_mbps=2",
        ),
    ],
)
def test_every_action_reads_as_one_line(kind: str, params: dict[str, Any], line: str) -> None:
    assert describe({"type": kind, "params": params}) == line


def test_a_verdict_without_kpis_reads_as_accepted_or_rejected() -> None:
    record = _record(1, "verified") | {}
    record["verdict"] = record["verdict"] | {"baseline": None}
    assert decision_queue([record])[0]["twin"] == "accepted"


def test_a_verdict_reads_as_one_word_or_the_error() -> None:
    assert verdict_word({"accepted": True}) == "accepted"
    assert verdict_word({"accepted": False}) == "rejected"
    assert verdict_word({"error": "channel 3 is not allowed"}) == "error: channel 3 is not allowed"


def test_kpi_series_averages_each_class_over_10_s_steps() -> None:
    points = {
        ("video", "latency_ms"): [
            {"ts": "2026-10-10T12:00:01+00:00", "value": 10.0},
            {"ts": "2026-10-10T12:00:04+00:00", "value": 30.0},  # another video flow
            {"ts": "2026-10-10T12:00:12+00:00", "value": 5.0},
        ],
        ("web", "loss_pct"): [{"ts": "2026-10-10T12:00:09+00:00", "value": 1.5}],
    }
    assert kpi_series(points) == [
        {"class": "video", "kpi": "latency ms", "t": "2026-10-10T12:00:00+00:00", "value": 20.0},
        {"class": "video", "kpi": "latency ms", "t": "2026-10-10T12:00:10+00:00", "value": 5.0},
        {"class": "web", "kpi": "loss %", "t": "2026-10-10T12:00:00+00:00", "value": 1.5},
    ]
