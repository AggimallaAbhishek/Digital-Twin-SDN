"""Blueprint + Sorbet dashboard SVGs (dashboard/svg.py): the floor plan and the twin bars, as
markup the page shows inline. Checked through their structure, not their pixels."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

from dashboard.svg import Move, floor_plan_svg, twin_bars_svg

ZONES = [
    {"zone": "lecture hall", "x": 0, "x2": 40, "y": 35, "y2": 65},
    {"zone": "lab", "x": 40, "x2": 80, "y": 35, "y2": 65},
    {"zone": "corridor", "x": 0, "x2": 40, "y": 5, "y2": 35},
    {"zone": "library", "x": 40, "x2": 80, "y": 5, "y2": 35},
]
SVG = "{http://www.w3.org/2000/svg}"


def _ap(name: str, x: float, y: float, band: str = "calm", channel: str = "ch 1") -> dict[str, Any]:
    return {"name": name, "x": x, "y": y, "band": band, "channel": channel}


def _sta(name: str, x: float, y: float, ap: str | None = "ap1") -> dict[str, Any]:
    return {"name": name, "x": x, "y": y, "ap": ap}


APS = [
    _ap("ap1", 20, 50, "congested"),
    _ap("ap2", 60, 50, channel="ch 6"),
    _ap("ap3", 20, 20, channel="ch 11"),
    _ap("ap4", 60, 20, "down"),
]


def _parse(svg: str) -> ET.Element:
    return ET.fromstring(svg)  # noqa: S314 - our own markup, built by the code under test


def _by_data(root: ET.Element, key: str, value: str) -> list[ET.Element]:
    return [e for e in root.iter() if e.get(f"data-{key}") == value]


def _texts(root: ET.Element) -> list[str]:
    return [t.text or "" for t in root.iter(f"{SVG}text")]


def test_the_plan_is_valid_svg_with_its_zones_and_dimensions() -> None:
    root = _parse(floor_plan_svg(APS, [], ZONES))
    assert root.tag == f"{SVG}svg"
    assert root.get("role") == "img"
    zones = {e.get("data-zone", "") for e in root.iter()} - {""}
    assert sorted(zones) == ["corridor", "lab", "lecture hall", "library"]
    texts = _texts(root)
    assert "80 m" in texts
    assert "60 m" in texts  # the zones span y 5 to 65: the plan shows what it draws
    assert {"Lecture hall", "Lab", "Corridor", "Library"} <= set(texts)


def test_no_unformatted_placeholder_reaches_the_markup() -> None:
    # a plain string among f-strings would ship "{LINE}" as a colour (found in review)
    stations = [_sta("sta1", 15, 55), _sta("sta2", 30, 10, None)]
    plan = floor_plan_svg(APS, stations, ZONES, Move("ap1", "ap3", ("sta1",), "moving"))
    kpis = {"latency_ms": 5.0, "loss_pct": 1.0}
    bars = twin_bars_svg(kpis, kpis, kpis)
    for svg in (plan, bars):
        assert "{" not in svg
        assert "}" not in svg


def test_a_congested_aps_zone_is_hatched_and_its_disc_is_red() -> None:
    root = _parse(floor_plan_svg(APS, [], ZONES))
    [hall] = [e for e in _by_data(root, "zone", "lecture hall") if e.get("data-state")]
    assert hall.get("data-state") == "congested"
    assert hall.get("fill") == "url(#hatch)"
    [disc] = _by_data(root, "ap", "ap1")
    assert disc.get("class") == "ap congested"


def test_a_down_ap_is_drawn_hollow_and_its_channel_reads_off() -> None:
    root = _parse(floor_plan_svg(APS, [], ZONES))
    [disc] = _by_data(root, "ap", "ap4")
    assert disc.get("class") == "ap down"
    assert "off" in _texts(root)


def test_clients_show_who_is_on_a_congested_ap_moving_or_without_an_ap() -> None:
    stations = [
        _sta("sta1", 15, 55, "ap1"),  # on the congested ap1
        _sta("sta2", 65, 45, "ap2"),  # an ordinary client
        _sta("sta3", 25, 45, "ap1"),  # in the move below
        _sta("sta4", 30, 10, None),  # no AP
    ]
    move = Move("ap1", "ap3", ("sta3",), "proposed")
    root = _parse(floor_plan_svg(APS, stations, ZONES, move))
    kinds = {e.get("data-client"): e.get("class") for e in root.iter() if e.get("data-client")}
    assert kinds == {
        "sta1": "client hot",
        "sta2": "client",
        "sta3": "client moving",
        "sta4": "client lost",
    }


def test_a_move_is_a_dashed_line_with_its_label() -> None:
    move = Move("ap1", "ap3", ("sta1", "sta2", "sta3"), "proposed")
    root = _parse(floor_plan_svg(APS, [], ZONES, move))
    [line] = [e for e in root.iter(f"{SVG}line") if e.get("class") == "move"]
    assert line.get("stroke-dasharray")
    assert "Move 3 clients to ap3" in _texts(root)
    watched = _parse(floor_plan_svg(APS, [], ZONES, Move("ap1", "ap3", ("sta1",), "moving")))
    assert "Moving 1 client to ap3" in _texts(watched)


def test_a_move_to_an_unknown_ap_draws_no_line() -> None:
    root = _parse(floor_plan_svg(APS, [], ZONES, Move("ap1", "ap9", ("sta1",), "proposed")))
    assert not [e for e in root.iter(f"{SVG}line") if e.get("class") == "move"]


def test_names_from_the_api_are_escaped() -> None:
    aps = [_ap('<b onmouseover="x">', 20, 50)]
    svg = floor_plan_svg(aps, [_sta("sta<1>", 10, 50, "ap1")], ZONES)
    _parse(svg)  # still well-formed
    assert "<b onmouseover" not in svg
    assert "&lt;b onmouseover=&quot;x&quot;&gt;" in svg


# ------------------------------------------------------------------ twin bars


def test_twin_bars_show_before_predicted_and_measured_for_latency_and_loss() -> None:
    before = {"latency_ms": 180.0, "loss_pct": 49.0}
    predicted = {"latency_ms": 40.0, "loss_pct": 3.0}
    measured = {"latency_ms": 44.0, "loss_pct": 3.0}
    root = _parse(twin_bars_svg(before, predicted, measured))
    bars = [(e.get("data-kpi"), e.get("data-source")) for e in root.iter() if e.get("data-source")]
    assert bars == [
        ("latency_ms", "before"),
        ("latency_ms", "predicted"),
        ("latency_ms", "measured"),
        ("loss_pct", "before"),
        ("loss_pct", "predicted"),
        ("loss_pct", "measured"),
    ]
    texts = _texts(root)
    assert [t for t in texts if t[0].isdigit()] == ["180", "40", "44", "49.0", "3.0", "3.0"]
    assert "Latency (ms)" in texts
    assert "Packet loss (%)" in texts


def test_the_tallest_bar_of_each_group_fills_its_height() -> None:
    root = _parse(
        twin_bars_svg(
            {"latency_ms": 10.0, "loss_pct": 0.0},
            {"latency_ms": 5.0, "loss_pct": 0.0},
            {"latency_ms": 20.0, "loss_pct": 0.0},
        )
    )
    heights = {
        (e.get("data-kpi"), e.get("data-source")): float(e.get("height", "0"))
        for e in root.iter()
        if e.get("data-source")
    }
    assert heights[("latency_ms", "measured")] > heights[("latency_ms", "before")]
    assert heights[("latency_ms", "before")] == 2 * heights[("latency_ms", "predicted")]
    assert all(heights[("loss_pct", s)] == 0 for s in ("before", "predicted", "measured"))
