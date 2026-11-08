"""Blueprint + Sorbet panels (dashboard/panels.py): what the new dashboard's panels show, from the
API's JSON and the demo's run file. Pure functions, tested without Streamlit."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml

from dashboard.panels import (
    RANGE,
    ApRow,
    DemoClock,
    Event,
    Focus,
    Hero,
    IntentView,
    Live,
    Proposal,
    Step,
    ap_rows,
    clock_label,
    demo_clock,
    event_rows,
    focus_ap,
    hero,
    intent_view,
    load_stories,
    map_move,
    proposal_view,
    route,
    story_steps,
)
from dashboard.svg import Move
from tests.unit.test_dashboard_views import _record

WATCH = timedelta(seconds=30)
STORY = [  # config/dashboard.yaml's lecture_flash_crowd story
    {"label": "Normal day", "trigger": "clock", "from_s": 0, "to_s": 120},
    {"label": "Crowd builds", "trigger": "clock", "from_s": 120, "to_s": 195},
    {"label": "Congestion", "trigger": "congested", "from_s": 210},
    {"label": "Optimiser proposes", "trigger": "proposed", "from_s": 215},
    {"label": "Apply and watch", "trigger": "applied", "from_s": 220, "to_s": 250},
    {"label": "Keep or roll back", "trigger": "outcome", "from_s": 250},
]


def _iso(s: float) -> str:
    """`s` seconds into the demo run, as the API writes a time."""
    return (START + timedelta(seconds=s)).isoformat()


def _topology(util: float = 0.3) -> dict[str, Any]:
    return {
        "ts": _iso(0),
        "aps": [{"name": "ap1", "position": [20, 50], "channel": 1, "up": True, "util": util}],
        "stations": [],
        "flows": [],
    }


def _steps(
    now_s: float,
    topology: dict[str, Any] | None = None,
    actions: list[dict[str, Any]] | None = None,
    alerts: list[dict[str, Any]] | None = None,
    congested_s: float | None = None,
) -> list[tuple[str, str]]:
    """(state, subtitle) of each story step `now_s` seconds into the demo; `congested_s`: when
    the dashboard first saw an AP congested in this run."""
    clock = demo_clock(RUN, START + timedelta(seconds=now_s))
    assert clock is not None
    topo = topology if topology is not None else _topology()
    live = Live(topo, actions or [], alerts or [])
    return [(s.state, s.sub) for s in story_steps(STORY, clock, live, WATCH, congested_s)]


def _applied(created_s: float, applied_s: float | None, status: str) -> dict[str, Any]:
    """A steer recorded `created_s` into the demo, applied at `applied_s`, now `status`."""
    record = _record(1, status, kind="steer_clients")
    record["action"]["created_at"] = _iso(created_s)
    record["applied_at"] = _iso(applied_s) if applied_s is not None else None
    return record


# ------------------------------------------------------------------ the story strip


def test_early_in_the_demo_only_the_first_step_is_happening() -> None:
    assert _steps(30) == [
        ("now", f"0:00{RANGE}2:00, happening now"),
        ("next", f"2:00{RANGE}3:15"),
        ("next", "about 3:30"),
        ("next", "about 3:35"),
        ("next", f"3:40{RANGE}4:10"),
        ("next", "about 4:10"),
    ]


def test_the_crowd_step_follows_the_clock() -> None:
    assert _steps(150)[:3] == [
        ("done", f"0:00{RANGE}2:00, done"),
        ("now", f"2:00{RANGE}3:15, happening now"),
        ("next", "about 3:30"),
    ]


def test_congestion_lights_up_when_it_is_detected_not_when_it_was_planned() -> None:
    hot = _topology(util=0.95)
    assert _steps(205, topology=hot)[2] == ("now", "3:25, happening now")  # seen live, early
    # congested at 3:32 but calm again now: the remembered onset still counts
    assert _steps(230, congested_s=212)[1:3] == [
        ("done", f"2:00{RANGE}3:15, done"),
        ("now", "3:32, happening now"),
    ]


def test_a_step_first_seen_after_a_later_step_was_missed() -> None:
    # live demo 2026-11-09: nobody watched the dashboard at the onset, so it first saw the
    # congestion at 5:49, after the proposal at 3:34: the strip read 5:49 before 3:34
    proposed = [_applied(214, None, "verified")]
    assert _steps(350, actions=proposed, congested_s=349)[2:4] == [
        ("done", "about 3:30, done"),  # passed over: when it began is unknown
        ("now", "3:34, happening now"),
    ]


def test_an_anomaly_alert_alone_is_not_congestion() -> None:
    # live demo 2026-11-09: the detector flagged ap3 at 0:04, during start-up, with every AP
    # calm; the strip jumped to "Congestion, happening now" while the crowd had not moved yet
    startup = [{"ts": _iso(4), "entity": "ap3", "score": 0.7}]
    assert [s for s, _ in _steps(12, alerts=startup)] == ["now"] + ["next"] * 5


def test_the_systems_steps_follow_the_ledger() -> None:
    proposed = [_applied(214, None, "verified")]
    assert _steps(216, actions=proposed, congested_s=210)[2:4] == [
        ("done", "3:30, done"),
        ("now", "3:34, happening now"),
    ]
    watching = [_applied(214, 219, "applied")]
    assert _steps(225, actions=watching, congested_s=210)[3:5] == [
        ("done", "3:34, done"),
        ("now", "3:39, happening now"),
    ]
    kept = [_applied(214, 219, "kept")]
    assert _steps(260, actions=kept, congested_s=210)[4:] == [
        ("done", "3:39, done"),
        ("now", "4:09, happening now"),  # applied + the 30 s watch
    ]


def test_events_from_before_the_demo_started_do_not_count() -> None:
    old = [_applied(-60, -50, "kept")]
    stale = [{"ts": _iso(-90), "entity": "ap1", "score": 0.7}]
    assert [s for s, _ in _steps(30, actions=old, alerts=stale)] == ["now"] + ["next"] * 5


def test_when_the_demo_ends_the_last_step_reached_is_done() -> None:
    kept = [_applied(214, 219, "kept")]
    assert _steps(700, actions=kept, congested_s=210)[-1] == ("done", "4:09, done")


def test_a_step_passed_over_reads_done_with_its_plan() -> None:
    # a change proposed without an alert first: the congestion step is behind it
    proposed = [_applied(214, None, "verified")]
    assert _steps(216, actions=proposed)[2:4] == [
        ("done", "about 3:30, done"),
        ("now", "3:34, happening now"),
    ]


def test_the_repos_story_config_loads() -> None:
    raw = yaml.safe_load(
        (Path(__file__).resolve().parents[2] / "config" / "dashboard.yaml").read_text()
    )
    stories = load_stories(raw)
    assert stories["lecture_flash_crowd"] == STORY


@pytest.mark.parametrize(
    ("bad", "message"),
    [
        ({"stories": {"s": [{"label": "x", "trigger": "rain", "from_s": 0}]}}, "trigger"),
        ({"stories": {"s": [{"label": "x", "trigger": "clock"}]}}, "from_s"),
        ({"stories": {"s": [{"label": "x", "trigger": "clock", "from_s": 9, "to_s": 3}]}}, "to_s"),
        (
            {"stories": {"s": [{"label": "x", "trigger": "clock", "from_s": 0, "colour": 1}]}},
            "unknown",
        ),
        ({"stories": {"s": [{"trigger": "clock", "from_s": 0}]}}, "label"),
        ({"stories": []}, "stories"),
        ({"story": {}}, "stories"),
    ],
)
def test_a_bad_story_config_is_refused_naming_the_field(bad: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        load_stories(bad)


def test_every_step_keeps_its_label() -> None:
    clock = demo_clock(RUN, START)
    assert clock is not None
    steps = story_steps(STORY, clock, Live(None, [], []), WATCH)
    assert [s.label for s in steps] == [s["label"] for s in STORY]
    assert steps[0] == Step("Normal day", f"0:00{RANGE}2:00, happening now", "now")


START = datetime(2026, 11, 9, 8, 0, tzinfo=UTC)
RUN = {
    "scenario": "lecture_flash_crowd",
    "title": "Lecture flash crowd",
    "started_at": START.isoformat(),
    "duration_s": 600,
}


# ------------------------------------------------------------------ the one input box


@pytest.mark.parametrize(
    "text",
    [
        "Why is video slow in the lecture hall?",
        "what is ap1 doing",
        "How many clients are on ap3",
        "Is the lab busy",
        "explain the last rollback",
        "show me the loss on ap2",
        "  WHICH ap is congested  ",
    ],
)
def test_a_question_goes_to_the_copilot(text: str) -> None:
    assert route(text) == "ask"


@pytest.mark.parametrize(
    "text",
    [
        "Give video calls in the lecture hall priority.",
        "Keep latency for video under 50 ms in the lab",
        "Limit bulk downloads in the library",
        "prioritise web traffic",
    ],
)
def test_anything_else_is_an_intent(text: str) -> None:
    assert route(text) == "intent"


# ------------------------------------------------------------------ the demo clock


def test_the_demo_clock_counts_from_the_runs_start() -> None:
    clock = demo_clock(RUN, START + timedelta(seconds=220))
    assert clock == DemoClock("Lecture flash crowd", START, 220, 600, ended=False)
    assert clock.text() == ("03:40", "10:00")


def test_the_demo_clock_stops_at_the_runs_end() -> None:
    clock = demo_clock(RUN, START + timedelta(seconds=900))
    assert clock is not None
    assert (clock.elapsed_s, clock.ended) == (600, True)
    assert clock.text() == ("10:00", "10:00")


def test_without_a_run_there_is_no_demo_clock() -> None:
    assert demo_clock(None, START) is None
    assert demo_clock({"scenario": "x"}, START) is None  # an unreadable file is no run


def test_a_run_finished_early_ends_the_clock_where_it_stopped() -> None:
    finished = RUN | {"finished_at": (START + timedelta(seconds=300)).isoformat()}
    clock = demo_clock(finished, START + timedelta(seconds=500))
    assert clock is not None
    assert (clock.elapsed_s, clock.ended) == (300, True)


def test_event_times_read_on_the_demo_clock_when_there_is_one() -> None:
    at = (START + timedelta(seconds=210)).isoformat()
    assert clock_label(at, START) == "03:30"
    assert clock_label((START - timedelta(seconds=5)).isoformat(), START) == "00:00"
    # no run: the local wall-clock time, as the old dashboard showed it
    assert clock_label(at, None) == datetime.fromisoformat(at).astimezone().strftime("%H:%M:%S")


# ------------------------------------------------------------------ status card, tiles, AP rows
ZONES = [  # config/campus_v1.yaml, as app.campus_zones() reads it
    {"zone": "lecture hall", "x": 0, "x2": 40, "y": 35, "y2": 65},
    {"zone": "lab", "x": 40, "x2": 80, "y": 35, "y2": 65},
    {"zone": "corridor", "x": 0, "x2": 40, "y": 5, "y2": 35},
    {"zone": "library", "x": 40, "x2": 80, "y": 5, "y2": 35},
]


def _campus(utils: dict[str, float], down: tuple[str, ...] = ()) -> dict[str, Any]:
    """Four APs (one per zone) at `utils`; ap1 has 3 clients with two video flows, ap3 has one."""
    where = {"ap1": (20, 50, 1), "ap2": (60, 50, 6), "ap3": (20, 20, 11), "ap4": (60, 20, 1)}
    return {
        "ts": _iso(200),
        "aps": [
            {
                "name": n,
                "position": [x, y],
                "channel": ch,
                "up": n not in down,
                "util": utils.get(n, 0.2),
            }
            for n, (x, y, ch) in where.items()
        ],
        "stations": [
            {"name": "sta1", "position": [15, 50], "ap": "ap1"},
            {"name": "sta2", "position": [25, 52], "ap": "ap1"},
            {"name": "sta3", "position": [22, 45], "ap": "ap1"},
            {"name": "sta4", "position": [20, 25], "ap": "ap3"},
            {"name": "sta5", "position": [65, 45], "ap": None},
        ],
        "flows": [
            {"flow_id": "sta1-video", "sta": "sta1", "app_class": "video", "loss_pct": 40.0},
            {"flow_id": "sta2-video", "sta": "sta2", "app_class": "video", "loss_pct": 58.0},
            {"flow_id": "sta4-web", "sta": "sta4", "app_class": "web", "loss_pct": 1.0},
        ],
    }


def test_the_status_card_names_the_worst_problem_in_plain_words() -> None:
    alerts = [{"ts": _iso(210), "entity": "ap1", "score": 0.7}]
    card = hero(Live(_campus({"ap1": 0.95}), [], alerts), ZONES, START)
    assert card == Hero(
        "coral", "⚠", "Anomaly detected at 03:30", "ap1 is congested in the lecture hall"
    )


def test_a_problem_without_an_alert_yet_says_when_the_twin_saw_it() -> None:
    card = hero(Live(_campus({"ap1": 0.95}), [], []), ZONES, START)
    assert (card.eyebrow, card.headline) == (
        "Seen at 03:20",
        "ap1 is congested in the lecture hall",
    )


@pytest.mark.parametrize(
    ("utils", "down", "tone", "headline"),
    [
        ({}, ("ap3",), "coral", "ap3 is down in the corridor"),
        ({"ap2": 0.65}, (), "yellow", "ap2 is busy in the lab"),
        ({}, (), "mint", "All access points are calm"),
    ],
)
def test_the_status_card_follows_the_status_levels(
    utils: dict[str, float], down: tuple[str, ...], tone: str, headline: str
) -> None:
    topo = _campus(utils, down)
    topo["stations"][4]["ap"] = "ap2"  # every client associated: only the APs' state counts
    card = hero(Live(topo, [], []), ZONES, None)
    assert (card.tone, card.headline) == (tone, headline)


def test_clients_without_an_ap_are_the_problem_when_no_ap_is() -> None:
    topo = _campus({})
    topo["stations"][0]["ap"] = None  # sta5 and sta1 without an AP
    card = hero(Live(topo, [], []), ZONES, None)
    assert (card.tone, card.headline) == ("coral", "2 clients have no access point")


def test_before_the_first_telemetry_the_card_waits() -> None:
    card = hero(Live(None, [], []), ZONES, None)
    assert (card.tone, card.headline) == ("white", "Waiting for data from the network")


def test_the_tiles_describe_the_busiest_ap() -> None:
    focus = focus_ap(_campus({"ap1": 0.95, "ap4": 0.97}, down=("ap4",)))
    assert focus == Focus("ap1", 3, 0.95, 49.0)  # loss: the mean of its two video flows
    assert focus_ap(_campus({"ap3": 0.7})) == Focus("ap3", 1, 0.7, 1.0)
    assert focus_ap(None) is None


def test_an_ap_without_flows_has_no_loss_to_show() -> None:
    topo = _campus({"ap2": 0.9})
    assert focus_ap(topo) == Focus("ap2", 0, 0.9, None)


def test_every_ap_has_a_row_with_its_zone_channel_clients_and_load() -> None:
    rows = ap_rows(_campus({"ap1": 0.95, "ap2": 0.52}, down=("ap4",)), ZONES)
    assert rows == [
        ApRow("ap1", "coral", "Lecture hall, channel 1, 3 clients", "95%", 95, True),
        ApRow("ap2", "mint", "Lab, channel 6, 0 clients", "52%", 52, False),
        ApRow("ap3", "sky", "Corridor, channel 11, 1 client", "20%", 20, False),
        ApRow("ap4", "grey", "Library, channel 1, off", "off", 0, False),
    ]


# ------------------------------------------------------------------ event timeline
MEASURED = {"throughput_mbps": 1.2, "latency_ms": 6.0, "loss_pct": 0.5, "jain": 0.9}


def _steer(n: int, status: str, created_s: float, applied_s: float | None = None) -> dict[str, Any]:
    record = _record(n, status, kind="steer_clients")
    record["action"] |= {"created_at": _iso(created_s), "source": "optimizer.heuristic"}
    record["applied_at"] = _iso(applied_s) if applied_s is not None else None
    if status in {"kept", "rolled_back"}:
        record["measured"] = MEASURED
    return record


def test_the_timeline_reads_in_order_with_a_coloured_time_chip() -> None:
    alerts = [{"ts": _iso(210), "entity": "ap1", "score": 0.7}] * 3
    live = Live(_campus({"ap1": 0.95}), [_steer(1, "kept", 215, 220)], alerts)
    assert event_rows(live, WATCH, START) == [
        Event("03:30", "coral", "ap1 looks unusual", "3 anomaly alerts"),
        Event(
            "03:35",
            "lavender",
            "Optimiser proposes a change",
            "Move 2 clients from ap1 to ap3; twin predicts 5 ms and 0.2% loss",
        ),
        Event(
            "03:40",
            "yellow",
            "Applying the change",
            "Move 2 clients from ap1 to ap3, watching for 30 s",
        ),
        Event("04:10", "mint", "Change kept", "Latency: twin 5 ms, measured 6 ms"),
    ]


def test_the_timeline_says_what_the_twin_and_the_operator_refused() -> None:
    rejected = _steer(1, "rejected", 215)
    rejected["verdict"]["violations"] = ["act_1: loss_pct regression on 3 flows (ADR-004)"]
    denied = _record(2, "denied")
    denied["action"]["created_at"] = _iso(230)
    rolled = _steer(3, "rolled_back", 240, 245)
    rows = event_rows(Live(None, [rejected, denied, rolled], []), WATCH, START)
    assert [(e.tone, e.title) for e in rows] == [
        ("coral", "Twin rejects a change"),
        ("lavender", "AI copilot proposes a change"),
        ("white", "Operator denied it"),
        ("lavender", "Optimiser proposes a change"),
        ("yellow", "Applying the change"),
        ("coral", "Change rolled back"),
    ]
    assert rows[0].detail == "Move 2 clients from ap1 to ap3; twin: loss regression on 3 flows"


def test_the_timeline_keeps_the_newest_rows() -> None:
    actions = [_steer(n, "verified", 200 + n) for n in range(1, 9)]
    rows = event_rows(Live(None, actions, []), WATCH, START, limit=3)
    assert [r.time for r in rows] == ["03:26", "03:27", "03:28"]


# ------------------------------------------------------------------ proposal card


def test_a_change_waiting_for_the_operator_comes_first() -> None:
    waiting = _record(1, "verified")  # a channel change: needs approval
    waiting["action"]["source"] = "optimizer.heuristic"
    view = proposal_view(
        Live(None, [_steer(2, "applied", 200, 205), waiting], []),
        START + timedelta(seconds=210),
        WATCH,
        START,
    )
    assert view == Proposal(
        kind="waiting",
        eyebrow="Optimiser proposal",
        title="Move ap3 to channel 11",
        latency=(5.0, 9.0),
        loss=(0.2, 14.0),
        accepted=True,
        note="",
        action_id="act_1",
        next_step="approve",
        progress=0.0,
    )


def test_a_change_being_watched_shows_how_far_its_watch_has_run() -> None:
    view = proposal_view(
        Live(None, [_steer(1, "applied", 200, 210)], []),
        START + timedelta(seconds=220),
        WATCH,
        START,
    )
    assert view is not None
    assert (view.kind, view.eyebrow) == ("watching", "Applied at 03:30 · watching for 30 s")
    assert view.progress == pytest.approx(1 / 3)  # 10 s into its 30 s watch


def test_the_latest_result_shows_until_it_is_ten_minutes_old() -> None:
    kept = _steer(1, "kept", 200, 210)
    soon = proposal_view(Live(None, [kept], []), START + timedelta(seconds=300), WATCH, START)
    assert soon is not None
    assert (soon.kind, soon.note) == ("result", "✓ Kept · measured latency 6 ms, loss 0.5%")
    assert (
        proposal_view(Live(None, [kept], []), START + timedelta(seconds=900), WATCH, START) is None
    )


def test_a_rejected_change_shows_the_twins_reason() -> None:
    rejected = _steer(1, "rejected", 200)
    rejected["verdict"]["violations"] = [
        "act_1: tx power step 6 dB on ap2: more than 3 dB (ADR-004)"
    ]
    view = proposal_view(Live(None, [rejected], []), START + timedelta(seconds=230), WATCH, START)
    assert view is not None
    assert (view.kind, view.accepted, view.note) == (
        "result",
        False,
        "✕ Twin rejected: tx power step 6 dB on ap2: more than 3 dB",
    )


# ------------------------------------------------------------------ the map's move arrow


def test_the_map_draws_the_steer_being_watched_else_the_one_waiting() -> None:
    assert map_move([_steer(1, "applied", 200, 205)]) == Move(
        "ap1", "ap3", ("sta1", "sta2"), "moving"
    )
    waiting = _steer(2, "approved", 210)
    assert map_move([waiting]) == Move("ap1", "ap3", ("sta1", "sta2"), "proposed")
    assert map_move([_steer(3, "kept", 200, 205), _record(4, "verified")]) is None


# ------------------------------------------------------------------ an intent's reply


def test_an_intent_reply_lists_its_changes_and_the_twins_check() -> None:
    result = {
        "actions": [
            {
                "action_id": "act_9",
                "type": "set_qos_queue",
                "params": {"queue_id": 1, "match": {"app_class": "video", "zone": "lecture_hall"}},
            }
        ],
        "verdicts": {"act_9": {"accepted": True, "violations": []}},
        "error": None,
    }
    view = intent_view(result)
    assert view == IntentView(
        "I can make 1 change: Give video in the lecture hall priority.",
        True,
        "Twin check passed for 1 change",
        ("act_9",),
    )


def test_an_intent_the_twin_refuses_cannot_be_applied() -> None:
    result = {
        "actions": [
            {
                "action_id": "act_9",
                "type": "rate_limit_flow",
                "params": {"flow_id": "sta1-bulk", "max_mbps": 0.2},
            }
        ],
        "verdicts": {
            "act_9": {"accepted": False, "violations": ["act_9: max_mbps below 0.5 (ADR-004)"]}
        },
        "error": None,
    }
    view = intent_view(result)
    assert (view.ok, view.check, view.applicable) == (False, "Twin refused: max_mbps below 0.5", ())


def test_an_intent_error_or_nothing_to_do_is_said_plainly() -> None:
    assert (
        intent_view({"actions": [], "verdicts": {}, "error": "no model answered"}).text
        == "no model answered"
    )
    nothing = intent_view({"actions": [], "verdicts": {}, "error": None})
    assert (nothing.text, nothing.applicable) == (
        "Nothing to change: the network already does that.",
        (),
    )
