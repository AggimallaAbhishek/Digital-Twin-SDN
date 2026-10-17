"""P6.1 dashboard view logic (dashboard/views.py): API JSON -> what each panel shows."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest

from dashboard.views import (
    COVERAGE_M,
    Status,
    Tile,
    alert_groups,
    band,
    describe,
    kpi_series,
    latest_steer,
    map_layers,
    plain_action,
    rca_view,
    rich_html,
    safe_html,
    status,
    tiles,
    timeline,
    twin_vs_live,
    verdict_word,
    waiting_steps,
)

WATCH = timedelta(seconds=30)  # config/executor.yaml watch_s, as app.watch() reads it

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
    assert band(0.3) == "calm"
    assert band(0.6) == "busy"
    assert band(0.8) == "congested"
    assert band(1.0) == "congested"


def test_the_map_shows_aps_by_channel_and_load_and_stations_by_association() -> None:
    aps, stations = map_layers(TOPOLOGY)
    ap1 = next(a for a in aps if a["name"] == "ap1")
    assert (ap1["x"], ap1["y"], ap1["channel"], ap1["clients"]) == (20, 50, "ch 1", 2)
    assert (ap1["load"], ap1["band"]) == (0.93, "congested")
    assert ap1["label"] == "ap1 · 93% · 2"  # the channel is drawn beside it, in grey
    ap2 = next(a for a in aps if a["name"] == "ap2")
    assert (ap2["band"], ap2["label"]) == ("down", "ap2 · down")
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
            "created_at": f"2026-10-16T08:20:{n:02d}+00:00",
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
    assert waiting_steps(actions) == {"act_1": "approve", "act_2": "apply"}


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
    assert {r["what"] for r in rows} == {"Move 2 clients ap1 → ap3"}


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


def test_a_waiting_change_says_where_it_came_from_and_what_the_twin_predicts() -> None:
    [item] = timeline([_record(1, "verified")], [], WATCH)
    assert item.detail == "llm.intent · high impact · twin: latency 9 → 5 ms · loss 14.0% → 0.2%"
    record = _record(1, "verified")
    record["verdict"] = record["verdict"] | {"baseline": None}  # a verdict without KPIs
    assert timeline([record], [], WATCH)[0].detail == "llm.intent · high impact"


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


@pytest.mark.parametrize(
    ("kind", "params", "words"),
    [
        (
            "steer_clients",
            {"stations": ["sta2", "sta12", "sta13"], "from_ap": "ap1", "to_ap": "ap3"},
            "Move 3 clients ap1 → ap3",
        ),
        (
            "steer_clients",
            {"stations": ["sta9"], "from_ap": "ap1", "to_ap": "ap2"},
            "Move 1 client ap1 → ap2",
        ),
        ("set_ap_channel", {"ap": "ap4", "channel": 11}, "Move ap4 to channel 11"),
        ("set_ap_tx_power", {"ap": "ap3", "dbm": 14.0}, "Set ap3 power to 14 dBm"),
        ("set_ap_tx_power", {"ap": "ap3", "dbm": 14.5}, "Set ap3 power to 14.5 dBm"),
        ("ap_admin_state", {"ap": "ap2", "state": "down"}, "Turn ap2 off"),
        ("ap_admin_state", {"ap": "ap2", "state": "up"}, "Turn ap2 on"),
        (
            "set_qos_queue",
            {"match": {"zone": "lecture_hall", "app_class": "video"}, "queue_id": 1},
            "Give video in the lecture hall priority",
        ),
        (
            "set_qos_queue",
            {"match": {"app_class": "bulk"}, "queue_id": 2},
            "Move bulk traffic to the background queue",
        ),
        (
            "set_qos_queue",
            {"match": {"flow_id": "sta1-video"}, "queue_id": 0},
            "Put flow sta1-video back to best effort",
        ),
        (
            "rate_limit_flow",
            {"flow_id": "sta1-video", "max_mbps": 1.5},
            "Cap flow sta1-video at 1.5 Mbit/s",
        ),
        (
            "reroute_flow",
            {"flow_id": "sta1-web", "path": ["s1", "s2", "ap1"]},
            "Reroute flow sta1-web via s1 → s2 → ap1",
        ),
    ],
)
def test_every_action_reads_in_plain_words(kind: str, params: dict[str, Any], words: str) -> None:
    assert plain_action({"type": kind, "params": params}) == words


ZONES = [  # config/campus_v1.yaml shape, as app.campus_zones() reads it
    {"zone": "lecture hall", "x": 0, "x2": 40, "y": 35, "y2": 70},
    {"zone": "lab", "x": 40, "x2": 80, "y": 35, "y2": 70},
    {"zone": "corridor", "x": 0, "x2": 40, "y": 0, "y2": 35},
]


def _topology(utils: dict[str, float], down: tuple[str, ...] = (), lost: int = 0) -> dict[str, Any]:
    """TOPOLOGY's three APs at the given loads; `lost` stations without an AP."""
    topo: dict[str, Any] = {
        "ts": TOPOLOGY["ts"],
        "aps": [
            a | {"util": utils.get(a["name"], 0.1), "up": a["name"] not in down}
            for a in TOPOLOGY["aps"]
        ],
        "stations": [s | {"ap": "ap1"} for s in TOPOLOGY["stations"]],
    }
    for s in topo["stations"][:lost]:
        s["ap"] = None
    return topo


def test_before_the_first_telemetry_the_banner_waits() -> None:
    assert status(None, ZONES, []) == Status("waiting", "Waiting for data from the network…", "")


@pytest.mark.parametrize(
    ("topology", "level", "headline"),
    [
        # first match wins: an AP down outranks everything else on the network
        (_topology({"ap1": 0.95}, down=("ap2",), lost=1), "critical", "ap2 is down (lab)."),
        (
            # a steered client is unassociated for a moment: congestion stays the headline
            # (live run 2026-10-16: the banner flipped on every steer), the client is added
            _topology({"ap1": 0.95}, lost=1),
            "critical",
            "ap1 is congested in the lecture hall (95%, 2 clients) · 1 client has no access point.",
        ),
        (_topology({}, lost=1), "critical", "1 client has no access point."),
        (_topology({}, lost=2), "critical", "2 clients have no access point."),
        (
            _topology({"ap1": 0.93, "ap3": 0.85}),  # the worst congested AP is named
            "critical",
            "ap1 is congested in the lecture hall (93%, 3 clients) and 1 more AP.",
        ),
        (_topology({"ap3": 0.68}), "attention", "ap3 is busy in the corridor (68%, 0 clients)."),
        (_topology({}), "calm", "All access points are calm · 3 clients connected."),
    ],
)
def test_the_banner_names_the_worst_problem_first(
    topology: dict[str, Any], level: str, headline: str
) -> None:
    got = status(topology, ZONES, [])
    assert (got.level, got.headline) == (level, headline)


def test_the_banner_says_what_the_system_is_doing() -> None:
    topo = _topology({"ap1": 0.95})
    steering = _record(1, "applied", kind="steer_clients", applied_at="2026-10-16T08:21:50+00:00")
    waiting = _record(2, "verified")  # a channel change: needs approval
    assert status(topo, ZONES, [steering]).doing == "The system is moving 2 clients to ap3."
    assert status(topo, ZONES, [waiting]).doing == "A change is waiting for you."
    assert status(topo, ZONES, [_record(3, "kept")]).doing == ""
    channel = _record(4, "applied", applied_at="2026-10-16T08:21:50+00:00")
    assert status(topo, ZONES, [channel]).doing == "The system is checking: Move ap3 to channel 11."


def test_the_tiles_count_problems_waiting_changes_and_the_last_outcome() -> None:
    topo = _topology({"ap1": 0.95, "ap3": 0.82}, lost=1)
    actions = [
        _record(1, "rolled_back", applied_at="2026-10-16T08:20:00+00:00"),
        _record(2, "kept", applied_at="2026-10-16T08:21:00+00:00"),  # the newest finished
        _record(3, "verified"),  # waiting for the operator
        _record(4, "approved"),  # approved, waiting to be applied
    ]
    assert tiles(topo, actions) == [
        Tile("2", "APs congested", "critical"),
        Tile("1", "client without an AP", "critical"),
        Tile("2", "waiting for you", "action"),
        Tile("✓", "last change kept", "good"),
    ]
    assert tiles(None, []) == [
        Tile("—", "APs congested", "calm"),
        Tile("—", "clients without an AP", "calm"),
        Tile("0", "waiting for you", "calm"),
        Tile("—", "no change yet", "calm"),
    ]


def test_a_rolled_back_or_failed_rollback_is_the_last_outcome_too() -> None:
    back = [_record(1, "rolled_back", applied_at="2026-10-16T08:20:00+00:00")]
    failed = [_record(1, "rollback_failed", applied_at="2026-10-16T08:20:00+00:00")]
    assert tiles(None, back)[3] == Tile("↺", "last change rolled back", "warn")
    assert tiles(None, failed)[3] == Tile("✕", "last rollback failed", "critical")


def _alert(ts: str, entity: str, score: float = 0.7) -> dict[str, Any]:
    return {"ts": f"2026-10-16T08:{ts}+00:00", "entity": entity, "score": score}


def test_only_the_newest_alert_episodes_get_their_own_item() -> None:
    # live run 2026-10-17: four episodes at the peak pushed the twin's story off the card
    alerts = [_alert(f"2{n}:00", entity) for n, entity in enumerate(("ap4", "ap3", "net", "ap1"))]
    items = timeline([], alerts, WATCH)
    assert [(i.title, i.badge, i.group is not None) for i in items] == [
        ("ap1 looks unusual", "1 alert", True),
        ("net looks unusual", "1 alert", True),
        ("2 earlier alert episodes", "ap3, ap4", False),  # no Explain: a summary
    ]
    assert items[2].at == "2026-10-16T08:21:00+00:00"  # the newer of the two


def _at(record: dict[str, Any], created: str, applied: str | None = None) -> dict[str, Any]:
    """The record proposed at 08:`created` and applied at 08:`applied`."""
    record["action"]["created_at"] = f"2026-10-16T08:{created}+00:00"
    record["applied_at"] = f"2026-10-16T08:{applied}+00:00" if applied else None
    return record


MEASURED = {"throughput_mbps": 1.2, "latency_ms": 15.0, "loss_pct": 1.0, "jain": 0.9}


def test_the_timeline_tells_the_story_newest_first_with_waiting_changes_on_top() -> None:
    kept = _at(_record(1, "kept", kind="steer_clients", measured=MEASURED), "21:48", "21:50")
    rejected = _at(_record(2, "rejected", kind="steer_clients"), "22:00")
    waiting = _at(_record(3, "verified"), "22:25")  # a channel change: needs approval
    watching = _at(_record(4, "applied", kind="steer_clients"), "22:28", "22:30")
    alerts = [_alert(f"21:{s}", "ap1") for s in ("40", "45", "50", "55")]
    items = timeline([kept, rejected, waiting, watching], alerts, WATCH)
    assert [(i.kind, i.title, i.badge, i.tone) for i in items] == [
        ("waiting", "Move ap3 to channel 11", "waiting for you", "action"),
        ("applied", "Move 2 clients ap1 → ap3", "watching 30 s", "action"),
        ("checked", "Move 2 clients ap1 → ap3", "accepted", "calm"),
        ("outcome", "Move 2 clients ap1 → ap3", "✓ kept", "good"),  # applied + the 30 s watch
        ("checked", "Move 2 clients ap1 → ap3", "✕ rejected", "warn"),
        ("detected", "ap1 looks unusual", "4 alerts", "critical"),
        ("checked", "Move 2 clients ap1 → ap3", "accepted", "calm"),
    ]
    assert items[0].next_step == "approve"
    assert items[0].action_id == "act_3"
    assert items[3].at == "2026-10-16T08:22:20+00:00"
    assert items[3].detail == "latency: twin 5 ms · measured 15 ms"
    assert items[2].detail == "twin: latency 9 → 5 ms · loss 14.0% → 0.2%"
    assert items[5].group is not None
    assert items[5].group.count == 4


@pytest.mark.parametrize(
    ("final", "badge", "tone"),
    [
        ("rolled_back", "↺ rolled back", "warn"),
        ("rollback_failed", "✕ rollback failed", "critical"),
        ("failed", "✕ could not apply", "critical"),
    ],
)
def test_every_final_status_has_its_outcome(final: str, badge: str, tone: str) -> None:
    items = timeline([_at(_record(1, final, kind="steer_clients"), "21:00", "21:02")], [], WATCH)
    assert (items[0].kind, items[0].badge, items[0].tone) == ("outcome", badge, tone)
    assert items[0].detail == ""  # nothing measured


REPORT = {  # POST /alerts/explain, as in the live run of 2026-10-16
    "summary": "ap1 experienced a sudden jump in client count (3.36 → 10.88).",
    "likely_causes": [
        {
            "category": "bad_action",
            "entity": "ap1",
            "confidence": 0.86,
            "evidence": "steer_clients moved sta2, sta12, sta13 from ap1 to ap3; ap1 util 0.1→0.6.",
        },
        {"category": "congestion", "entity": "ap1", "confidence": 0.4, "evidence": "sta9 joined"},
    ],
    "suggested_actions": [
        {
            "action": {
                "type": "steer_clients",
                "params": {"from_ap": "ap1", "to_ap": "ap3", "stations": ["sta1", "sta3", "sta9"]},
            },
            "verdict": {"accepted": False},
        }
    ],
    "model": "gpt-oss:120b-cloud",
}


def test_a_root_cause_report_reads_in_plain_words() -> None:
    view = rca_view(REPORT)
    assert view.summary == REPORT["summary"]
    assert view.causes == [
        (
            "a recent change",
            "ap1",
            "86%",
            "steer_clients moved 3 clients from ap1 to ap3; ap1 util 0.1→0.6.",
        ),
        ("congestion", "ap1", "40%", "sta9 joined"),  # one or two names stay
    ]
    assert view.suggestions == ["Move 3 clients ap1 → ap3 · twin rejected"]
    assert view.model == "gpt-oss:120b-cloud"
    assert view.error == ""


@pytest.mark.parametrize(
    ("category", "word"),
    [
        ("ap_down", "an access point down"),
        ("cochannel_interference", "co-channel interference"),
        ("congestion", "congestion"),
        ("bad_action", "a recent change"),
        ("other", "something else"),
        ("new_category", "new category"),  # one the explainer adds later still reads
    ],
)
def test_every_root_cause_category_has_a_word(category: str, word: str) -> None:
    cause = {"category": category, "entity": "ap1", "confidence": 0.5, "evidence": ""}
    view = rca_view({"summary": "", "likely_causes": [cause], "suggested_actions": []})
    assert view.causes[0][0] == word


def test_a_failed_explanation_shows_its_error() -> None:
    view = rca_view({"error": "the explainer timed out"})
    assert (view.error, view.causes, view.suggestions) == ("the explainer timed out", [], [])


def test_the_steer_being_watched_is_drawn_as_an_arrow_between_its_aps() -> None:
    aps, _ = map_layers(TOPOLOGY)
    older = _at(_record(1, "applied", kind="steer_clients"), "21:00", "21:00")
    newer = _at(_record(2, "applied", kind="steer_clients"), "21:30", "21:30")
    newer["action"]["params"] = {"from_ap": "ap3", "to_ap": "ap1", "stations": ["sta5"]}
    assert latest_steer([older, newer], aps) == {
        "x": 20,
        "y": 20,
        "x2": 20,
        "y2": 50,
        "label": "1 client",
    }


def test_no_arrow_without_a_steer_being_watched() -> None:
    aps, _ = map_layers(TOPOLOGY)
    kept = _at(_record(1, "kept", kind="steer_clients"), "21:00", "21:00")  # watch is over
    channel = _at(_record(2, "applied"), "21:00", "21:00")  # being watched, not a steer
    assert latest_steer([kept, channel], aps) is None
    unknown = _at(_record(3, "applied", kind="steer_clients"), "21:00", "21:00")
    unknown["action"]["params"] = {"from_ap": "ap1", "to_ap": "ap9", "stations": ["sta1"]}
    assert latest_steer([unknown], aps) is None  # an AP the twin does not know


def test_a_reason_names_its_kpi_in_words() -> None:
    # live run 2026-10-17: "latency_ms 6.0% worse", the verifier's field name
    record = _at(_record(1, "rejected", kind="steer_clients"), "21:00")
    record["verdict"]["violations"] = [
        "act_1: latency_ms 6.0% worse and no KPI improves by more than 5%",
    ]
    [item] = timeline([record], [], WATCH)
    assert item.detail == "twin: latency 6.0% worse and no KPI improves by more than 5%"


def test_a_prediction_for_no_traffic_is_not_shown() -> None:
    # live run 2026-10-17: a QoS intent before the video started read "latency 0 → 0 ms"
    record = _at(_record(1, "kept", kind="steer_clients"), "21:00")
    zero = {"throughput_mbps": 0.0, "latency_ms": 0.0, "loss_pct": 0.0, "jain": 1.0}
    record["verdict"] |= {"baseline": zero, "predicted": zero}
    checked = [i for i in timeline([record], [], WATCH) if i.kind == "checked"]
    assert checked[0].detail == ""


def test_a_rejected_change_shows_why_the_twin_rejected_it() -> None:
    # rejected on its bounds, the twin predicts nothing: its zeros would read as a prediction
    record = _at(_record(1, "rejected", kind="steer_clients"), "21:00")
    record["verdict"]["violations"] = [
        "act_1: moves 5 of 11 clients of ap1: more than 30% (ADR-004)",
        "act_1: sta1 would get -83 dBm at ap2: below -75 dBm (ADR-004)",
        "act_1: sta3 would get -80 dBm at ap2: below -75 dBm (ADR-004)",
    ]
    [item] = timeline([record], [], WATCH)
    assert item.detail == "twin: moves 5 of 11 clients of ap1: more than 30% (+2 more reasons)"
    record["verdict"]["violations"] = record["verdict"]["violations"][:1]
    assert (
        timeline([record], [], WATCH)[0].detail
        == "twin: moves 5 of 11 clients of ap1: more than 30%"
    )


def test_a_denied_change_shows_on_its_twin_check() -> None:
    [item] = timeline([_at(_record(1, "denied"), "21:00")], [], WATCH)
    assert (item.kind, item.badge) == ("checked", "denied by the operator")


def test_the_timeline_keeps_the_newest_items_and_every_waiting_change() -> None:
    actions = [
        _at(_record(n, "rejected", kind="steer_clients"), f"2{n % 10}:{n:02d}") for n in range(12)
    ]
    actions.append(_at(_record(99, "verified"), "00:00"))  # old but still waiting
    items = timeline(actions, [], WATCH, limit=4)
    assert len(items) == 4
    assert items[0].kind == "waiting"
    assert [i.at[11:19] for i in items[1:]] == ["08:29:09", "08:28:08", "08:27:07"]


def test_repeated_alerts_on_one_entity_become_one_group_newest_first() -> None:
    # the monitor alerts every 5 s while a fault lasts; the screen shows one item per episode
    alerts = [
        _alert("21:35", "network", 0.71),
        _alert("21:40", "ap1", 0.70),
        _alert("21:45", "network", 0.73),  # interleaved: still the same network episode
        _alert("21:50", "ap1", 0.72),
        _alert("21:55", "network", 0.69),
    ]
    groups = alert_groups(alerts)
    assert [(g.entity, g.count, g.score) for g in groups] == [
        ("network", 3, 0.73),
        ("ap1", 2, 0.72),
    ]
    assert groups[0].first == "2026-10-16T08:21:35+00:00"
    assert groups[0].last == groups[0].latest["ts"] == "2026-10-16T08:21:55+00:00"


def test_alerts_more_than_a_minute_apart_are_separate_episodes() -> None:
    alerts = [_alert("10:00", "ap3"), _alert("10:05", "ap3"), _alert("12:00", "ap3")]
    assert [(g.count, g.first[11:19]) for g in alert_groups(alerts)] == [
        (1, "08:12:00"),
        (2, "08:10:00"),
    ]


def test_no_alerts_no_groups() -> None:
    assert alert_groups([]) == []


def test_the_copilots_bold_shows_as_bold_and_nothing_else_gets_through() -> None:
    # live run 2026-10-17: the answer read "returned **rejected**" with the asterisks
    answer = "It returned **rejected**: <b>x</b> **unclosed\n\n**So it would not help.**"
    assert rich_html(answer) == (
        "It returned <b>rejected</b>: &lt;b&gt;x&lt;/b&gt; **unclosed<br><br>"
        "<b>So it would not help.</b>"
    )


def test_text_from_the_api_cannot_add_html_or_markdown_to_the_page() -> None:
    # rule L-6: answers and reports can be written by the LLM. A blank line would end
    # st.markdown's HTML block and let Markdown after it render (an image from anywhere)
    answer = 'Load is high <script>x</script>.\n\n![](http://evil.example/p.png) "ok"'
    assert safe_html(answer) == (
        "Load is high &lt;script&gt;x&lt;/script&gt;.<br><br>"
        "![](http://evil.example/p.png) &quot;ok&quot;"
    )
    assert "\n" not in safe_html("a\r\nb\rc")


def test_a_queue_without_its_own_words_is_named_by_number() -> None:
    # a queue added to common/schemas.py later must not break the timeline
    action = {"type": "set_qos_queue", "params": {"match": {"app_class": "video"}, "queue_id": 7}}
    assert plain_action(action) == "Put video traffic in queue 7"


def test_an_unknown_action_type_falls_back_to_its_one_line_description() -> None:
    # a type added to the allow-list later still shows, if less nicely
    action = {"type": "new_kind", "params": {"ap": "ap1"}}
    assert plain_action(action) == describe(action)
