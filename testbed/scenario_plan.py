"""Scenario planning (P1.6): parse a scenario, resolve station selectors, order the timeline.

Pure Python (no Mininet import), unit-tested on the Mac and run on the VM (Python 3.8, ADR-003).
The full validation is common/schemas.py `Scenario` on the Mac (tests/contract/
test_scenario_files.py checks every experiments/scenarios/*.yaml); this module re-checks only
what testbed/run_scenario.py relies on, naming the bad field.
"""

from __future__ import annotations

import math
import re
import statistics
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from testbed.ap_logic import CHANNELS
from testbed.layout import CampusLayout, StationSpec
from testbed.mobility.crowd import CrowdGroupSpec, Walk, parse_groups, position_at

APP_CLASSES = ("video", "web", "bulk")  # = common/schemas.py AppClass
EVENT_TYPES = ("ap_down", "ap_up", "force_channel")  # = common/schemas.py ScenarioEvent.type
P95 = 0.95

_SCENARIO_KEYS = {
    "scenario_id",
    "duration_s",
    "seed",
    "topology",
    "mobility",
    "traffic",
    "events",
    "labels",
}
_TRAFFIC_KEYS = {"profile", "stations", "start_s", "rate_mbps"}
_EVENT_KEYS = {"at_s", "type", "ap", "channel"}
_IDENTIFIER = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
_SELECTOR = re.compile(r"^(\*|[a-z_]+:\*|sta[0-9]+)$")
_AP_NAME = re.compile(r"^ap[0-9]+$")


@dataclass(frozen=True)
class TrafficSpec:
    """Start `profile` traffic on the stations matching `stations` at `start_s`."""

    profile: str
    stations: str  # "*", "<zone>:*" or "staN"; resolved when the traffic starts
    start_s: float
    rate_mbps: float | None


@dataclass(frozen=True)
class EventSpec:
    """A scripted radio event: AP down/up, or an AP forced onto a channel (interference)."""

    at_s: float
    type: str
    ap: str
    channel: int | None = None


@dataclass(frozen=True)
class ScenarioSpec:
    """A parsed scenario file (experiments/scenarios/*.yaml)."""

    scenario_id: str
    duration_s: float
    seed: int
    topology: str
    groups: tuple[CrowdGroupSpec, ...]
    traffic: tuple[TrafficSpec, ...]
    events: tuple[EventSpec, ...]
    labels: tuple[str, ...]


@dataclass(frozen=True)
class Step:
    """Everything that happens at scenario time `t_s` (crowd walks run on their own clock)."""

    t_s: float
    traffic: tuple[TrafficSpec, ...]
    events: tuple[EventSpec, ...]


def parse_scenario(raw: Mapping[str, Any]) -> ScenarioSpec:
    """Parse a scenario mapping; raise ValueError naming the bad field."""
    _known_keys(raw, _SCENARIO_KEYS, "scenario")
    for key in ("scenario_id", "topology"):
        if not isinstance(raw.get(key), str) or not _IDENTIFIER.match(raw[key]):
            raise ValueError(f"{key} must be an identifier, got {raw.get(key)!r}")
    duration = _number(raw.get("duration_s"), "duration_s", positive=True)
    seed: Any = raw.get("seed")
    if not _is_int(seed):
        raise ValueError(f"seed must be an integer, got {seed!r}")
    mobility = raw.get("mobility", {"model": "static"})
    if mobility.get("model") not in ("static", "scheduled_crowd"):
        raise ValueError(f"mobility.model must be static or scheduled_crowd, got {mobility!r}")
    groups = tuple(parse_groups(mobility.get("groups", [])))
    traffic = tuple(_traffic(i, item) for i, item in enumerate(raw.get("traffic", [])))
    events = tuple(_event(i, item) for i, item in enumerate(raw.get("events", [])))
    times = [t.start_s for t in traffic] + [e.at_s for e in events]
    times += [g.start_s + g.spread_s for g in groups]
    if any(t > duration for t in times):
        raise ValueError("all traffic, events and crowd moves must happen within duration_s")
    return ScenarioSpec(
        raw["scenario_id"],
        duration,
        seed,
        raw["topology"],
        groups,
        traffic,
        events,
        tuple(raw.get("labels", [])),
    )


def resolve_selector(selector: str, zone_of: Mapping[str, str]) -> list[str]:
    """Stations matching `selector` given where every station is now, in station order."""
    if selector == "*":
        names = list(zone_of)
    elif selector.endswith(":*"):
        zone = selector[:-2]
        names = [name for name, z in zone_of.items() if z == zone]
    elif selector in zone_of:
        names = [selector]
    else:
        raise ValueError(f"unknown station {selector!r}")
    return sorted(names, key=_station_number)


def zones_at(
    layout: CampusLayout, stations: Sequence[StationSpec], walks: Sequence[Walk], t: float
) -> dict[str, str]:
    """The zone every station is in at scenario time `t` (planned walks, deterministic)."""
    position = {s.name: s.position for s in stations}
    for walk in sorted(walks, key=lambda w: w.start_s):  # later walks of a station win
        if t >= walk.start_s:
            position[walk.sta] = position_at(walk, t)
    return {name: _zone_of(layout, xy) for name, xy in position.items()}


def nearest_up_ap(layout: CampusLayout, position: tuple[float, float], down: set[str]) -> str:
    """The AP an orphaned station joins: the nearest one that is up (as decision P1.4-A)."""
    up = [ap for ap in layout.aps if ap.name not in down]
    if not up:
        raise ValueError("no AP is up")
    return min(up, key=lambda ap: math.dist(ap.position, position)).name


def timeline(spec: ScenarioSpec) -> list[Step]:
    """Traffic starts and events grouped by time, in time order (file order within a time)."""
    times = sorted({t.start_s for t in spec.traffic} | {e.at_s for e in spec.events})
    return [
        Step(
            t,
            tuple(item for item in spec.traffic if item.start_s == t),
            tuple(event for event in spec.events if event.at_s == t),
        )
        for t in times
    ]


def summarize_kpis(records: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """Per app class: record count, mean throughput, p50/p95 latency (nearest rank), mean loss."""
    summary: dict[str, dict[str, Any]] = {}
    for app_class in sorted({r["app_class"] for r in records}):
        rows = [r for r in records if r["app_class"] == app_class]
        latencies = sorted(r["latency_ms"] for r in rows)
        summary[app_class] = {
            "records": len(rows),
            "throughput_mbps": round(statistics.mean(r["throughput_mbps"] for r in rows), 3),
            "latency_ms_p50": round(statistics.median(latencies), 3),
            "latency_ms_p95": latencies[math.ceil(P95 * len(latencies)) - 1],
            "loss_pct": round(statistics.mean(r["loss_pct"] for r in rows), 3),
        }
    return summary


def max_deviation_pct(values: Sequence[float]) -> float:
    """Largest deviation of any value from their mean, in % of the mean (P1.6 ±5% criterion)."""
    if not values:
        raise ValueError("no values to compare")
    mean = statistics.mean(values)
    return max(abs(v - mean) for v in values) / mean * 100


def _traffic(index: int, item: Mapping[str, Any]) -> TrafficSpec:
    where = f"traffic {index}"
    _known_keys(item, _TRAFFIC_KEYS, where)
    profile, stations = item.get("profile"), item.get("stations")
    if profile not in APP_CLASSES:
        raise ValueError(f"{where}: profile must be one of {APP_CLASSES}, got {profile!r}")
    if not isinstance(stations, str) or not _SELECTOR.match(stations):
        raise ValueError(f"{where}: stations must be '*', '<zone>:*' or 'staN', got {stations!r}")
    start = _number(item.get("start_s", 0.0), f"{where}: start_s")
    rate = item.get("rate_mbps")
    if rate is not None:
        if profile == "web":
            raise ValueError(f"{where}: rate_mbps applies to video and bulk only")
        rate = _number(rate, f"{where}: rate_mbps", positive=True)
    return TrafficSpec(profile, stations, start, rate)


def _event(index: int, item: Mapping[str, Any]) -> EventSpec:
    where = f"event {index}"
    _known_keys(item, _EVENT_KEYS, where)
    kind, ap, channel = item.get("type"), item.get("ap"), item.get("channel")
    if kind not in EVENT_TYPES:
        raise ValueError(f"{where}: type must be one of {EVENT_TYPES}, got {kind!r}")
    if not isinstance(ap, str) or not _AP_NAME.match(ap):
        raise ValueError(f"{where}: ap must be an AP name, got {ap!r}")
    if kind == "force_channel" and channel not in CHANNELS:
        raise ValueError(f"{where}: force_channel needs a channel in {CHANNELS}, got {channel!r}")
    if kind != "force_channel" and channel is not None:
        raise ValueError(f"{where}: {kind} takes no channel")
    return EventSpec(_number(item.get("at_s"), f"{where}: at_s"), kind, ap, channel)


def _zone_of(layout: CampusLayout, xy: tuple[float, float]) -> str:
    for zone in layout.zones.values():
        if zone.contains(*xy):
            return zone.name
    raise ValueError(f"position {xy} is outside every zone")


def _known_keys(raw: Mapping[str, Any], allowed: set[str], where: str) -> None:
    unknown = set(raw) - allowed
    if unknown:
        raise ValueError(f"{where}: unknown keys {sorted(unknown)}")


def _number(value: Any, where: str, positive: bool = False) -> float:
    if not _is_number(value) or value < 0 or (positive and value == 0):
        raise ValueError(f"{where} must be a number {'> 0' if positive else '>= 0'}, got {value!r}")
    return float(value)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _station_number(name: str) -> int:
    return int(re.sub(r"\D", "", name) or 0)
