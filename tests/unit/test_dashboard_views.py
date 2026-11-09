"""P6.1 dashboard view logic (dashboard/views.py): API JSON -> what each panel shows."""

from __future__ import annotations

from typing import Any

import pytest

from dashboard.views import (
    alert_groups,
    band,
    describe,
    kpi_series,
    map_layers,
    md_literal,
    plain_action,
    rca_view,
    rich_html,
    safe_html,
    shorten,
    verdict_word,
    waiting_steps,
    why_not,
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
    assert band(0.3) == "calm"
    assert band(0.6) == "busy"
    assert band(0.8) == "congested"
    assert band(1.0) == "congested"


def test_the_map_shows_aps_by_channel_and_load_and_stations_by_association() -> None:
    aps, stations = map_layers(TOPOLOGY)
    ap1 = next(a for a in aps if a["name"] == "ap1")
    assert (ap1["x"], ap1["y"], ap1["channel"], ap1["clients"]) == (20, 50, "ch 1", 2)
    assert (ap1["load"], ap1["band"]) == (0.93, "congested")
    ap2 = next(a for a in aps if a["name"] == "ap2")
    assert ap2["band"] == "down"
    # co-channel: ap1 and ap3 share channel 1 and are 30 m apart, inside each other's rings
    assert next(a for a in aps if a["name"] == "ap3")["shares_channel_with"] == ["ap1"]
    assert ap1["shares_channel_with"] == ["ap3"]
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
            "Move 3 clients from ap1 to ap3",
        ),
        (
            "steer_clients",
            {"stations": ["sta9"], "from_ap": "ap1", "to_ap": "ap2"},
            "Move 1 client from ap1 to ap2",
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


def _alert(ts: str, entity: str, score: float = 0.7) -> dict[str, Any]:
    return {"ts": f"2026-10-16T08:{ts}+00:00", "entity": entity, "score": score}


def _at(record: dict[str, Any], created: str, applied: str | None = None) -> dict[str, Any]:
    """The record proposed at 08:`created` and applied at 08:`applied`."""
    record["action"]["created_at"] = f"2026-10-16T08:{created}+00:00"
    record["applied_at"] = f"2026-10-16T08:{applied}+00:00" if applied else None
    return record


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
    assert view.suggestions == ["Move 3 clients from ap1 to ap3 · twin rejected"]
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


def test_a_reason_names_its_kpi_in_words() -> None:
    # live run 2026-10-17: "latency_ms 6.0% worse", the verifier's field name
    record = _at(_record(1, "rejected", kind="steer_clients"), "21:00")
    record["verdict"]["violations"] = [
        "act_1: latency_ms 6.0% worse and no KPI improves by more than 5%",
    ]
    assert why_not(record["verdict"]) == (
        "twin: latency 6.0% worse and no KPI improves by more than 5%"
    )


def test_a_prediction_for_no_traffic_is_not_shown() -> None:
    # live run 2026-10-17: a QoS intent before the video started read "latency 0 → 0 ms"
    record = _at(_record(1, "rejected", kind="steer_clients"), "21:00")
    zero = {"throughput_mbps": 0.0, "latency_ms": 0.0, "loss_pct": 0.0, "jain": 1.0}
    record["verdict"] |= {"baseline": zero, "predicted": zero, "violations": []}
    assert why_not(record["verdict"]) == ""  # rejected on its KPIs, but none to show


def test_a_rejected_change_shows_why_the_twin_rejected_it() -> None:
    # rejected on its bounds, the twin predicts nothing: its zeros would read as a prediction
    record = _at(_record(1, "rejected", kind="steer_clients"), "21:00")
    record["verdict"]["violations"] = [
        "act_1: moves 5 of 11 clients of ap1: more than 30% (ADR-004)",
        "act_1: sta1 would get -83 dBm at ap2: below -75 dBm (ADR-004)",
        "act_1: sta3 would get -80 dBm at ap2: below -75 dBm (ADR-004)",
    ]
    expected = "twin: moves 5 of 11 clients of ap1: more than 30%"
    assert why_not(record["verdict"]) == f"{expected} (+2 more reasons)"
    record["verdict"]["violations"] = record["verdict"]["violations"][:1]
    assert why_not(record["verdict"]) == expected


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


def test_text_for_streamlits_markdown_messages_shows_literally() -> None:
    # code review 2026-10-17: st.error / st.toast render Markdown, and an intent error can be
    # the model's text: an image from anywhere, or $…$ maths, must show as typed
    text = "Bad **intent** ![x](http://evil.example/p.png) costs $5 _now_"
    assert md_literal(text) == (
        r"Bad \*\*intent\*\* \!\[x\]\(http\:\/\/evil\.example\/p\.png\) costs \$5 \_now\_"
    )


def test_station_lists_are_shortened_wherever_the_model_writes_them() -> None:
    # the copilot's answers listed ten names; the root-cause report already counted them
    assert shorten("moving sta1, sta3, sta9 and sta10 to ap3") == "moving 4 clients to ap3"
    assert shorten("sta1 and sta2 joined") == "sta1 and sta2 joined"


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
