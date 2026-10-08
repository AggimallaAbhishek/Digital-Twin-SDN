"""Scheduled-crowd mobility (P1.4): who walks where, when, and where they are at time t.

Pure Python (no Mininet import), unit-tested on the Mac and run on the VM (Python 3.8, ADR-003).
Input is a scenario's `mobility.groups` (same fields as common/schemas.py CrowdGroup). The full
scenario is validated on the Mac (P1.6); this module re-checks only what it relies on.
"""

from __future__ import annotations

import math
import random
import re
from dataclasses import dataclass
from typing import AbstractSet, Any, Mapping, Sequence

from testbed.layout import CampusLayout, StationSpec

WALK_SPEED_MPS = 1.2  # normal walking pace
TICK_S = 1.0  # how often the runner moves walking stations

_GROUP_KEYS = {"stations", "from", "to", "start_s", "spread_s"}


@dataclass(frozen=True)
class CrowdGroupSpec:
    """A group of `stations` walking from one zone to another."""

    stations: int
    from_zone: str
    to_zone: str
    start_s: float
    spread_s: float = 0.0


@dataclass(frozen=True)
class Walk:
    """One station walking in a straight line from `src` to `dst`, leaving at `start_s`."""

    sta: str
    start_s: float
    src: tuple[float, float]
    dst: tuple[float, float]
    speed_mps: float = WALK_SPEED_MPS

    @property
    def duration_s(self) -> float:
        return math.dist(self.src, self.dst) / self.speed_mps

    @property
    def end_s(self) -> float:
        return self.start_s + self.duration_s


def parse_groups(raw: Sequence[Mapping[str, Any]]) -> list[CrowdGroupSpec]:
    """Parse `mobility.groups`; raise ValueError naming the bad group."""
    return [_parse_group(i, item) for i, item in enumerate(raw)]


def _parse_group(index: int, item: Mapping[str, Any]) -> CrowdGroupSpec:
    where = f"crowd group {index}"
    unknown = set(item) - _GROUP_KEYS
    if unknown:
        raise ValueError(f"{where}: unknown keys {sorted(unknown)}")
    for key in ("stations", "from", "to", "start_s"):
        if key not in item:
            raise ValueError(f"{where}: missing {key!r}")
    stations, start, spread = item["stations"], item["start_s"], item.get("spread_s", 0.0)
    if not _is_int(stations) or stations <= 0:
        raise ValueError(f"{where}: stations must be a positive integer, got {stations!r}")
    if not isinstance(item["from"], str) or not isinstance(item["to"], str):
        raise ValueError(f"{where}: from/to must be zone names")
    if item["from"] == item["to"]:
        raise ValueError(f"{where}: must move between different zones")
    for name, value in (("start_s", start), ("spread_s", spread)):
        if not _is_number(value) or value < 0:
            raise ValueError(f"{where}: {name} must be a number >= 0, got {value!r}")
    return CrowdGroupSpec(stations, item["from"], item["to"], float(start), float(spread))


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def plan_crowd(
    groups: Sequence[CrowdGroupSpec],
    layout: CampusLayout,
    stations: Sequence[StationSpec],
    seed: int,
    speed_mps: float = WALK_SPEED_MPS,
) -> list[Walk]:
    """Plan every station's walk (deterministic for a seed), groups in start order.

    Walkers are a seeded sample of the stations in the source zone that are not still walking.
    Departures are spaced evenly over [start_s, start_s + spread_s]; each walker heads to a
    seeded point inside the target zone. Later groups see where earlier walkers ended up.
    """
    rng = random.Random(seed)  # noqa: S311 - simulated crowd, not security
    zone_of = {s.name: s.zone for s in stations}
    position = {s.name: s.position for s in stations}
    busy_until: dict[str, float] = {}
    walks: list[Walk] = []
    for index, group in sorted(enumerate(groups), key=lambda ig: (ig[1].start_s, ig[0])):
        for zone in (group.from_zone, group.to_zone):
            if zone not in layout.zones:
                raise ValueError(f"crowd group {index}: unknown zone {zone!r}")
        free = sorted(
            (
                name
                for name, zone in zone_of.items()
                if zone == group.from_zone and busy_until.get(name, -math.inf) <= group.start_s
            ),
            key=station_number,
        )
        if len(free) < group.stations:
            raise ValueError(
                f"crowd group {index}: {group.from_zone} has {len(free)} free stations "
                f"at t={group.start_s:g} s, needs {group.stations}"
            )
        walkers = rng.sample(free, group.stations)
        step = group.spread_s / (group.stations - 1) if group.stations > 1 else 0.0
        for k, name in enumerate(walkers):
            walk = Walk(
                name,
                group.start_s + k * step,
                position[name],
                _random_point(rng, layout, group.to_zone),
                speed_mps,
            )
            walks.append(walk)
            zone_of[name], position[name], busy_until[name] = group.to_zone, walk.dst, walk.end_s
    return walks


def position_at(walk: Walk, t: float) -> tuple[float, float]:
    """Where the walker is at scenario time `t` (at src before leaving, at dst after arriving)."""
    if t <= walk.start_s:
        return walk.src
    if t >= walk.end_s:
        return walk.dst
    f = (t - walk.start_s) / walk.duration_s
    (x0, y0), (x1, y1) = walk.src, walk.dst
    return (x0 + f * (x1 - x0), y0 + f * (y1 - y0))


def nearest_ap(
    layout: CampusLayout, position: tuple[float, float], down: AbstractSet[str] = frozenset()
) -> str:
    """The AP a station joins: the nearest one that is up (decision P1.4-A: nearest, not
    RSSI-threshold roaming). Used for crowd arrivals and for stations of a failed AP (P1.6)."""
    up = [ap for ap in layout.aps if ap.name not in down]
    if not up:
        raise ValueError("no AP is up")
    return min(up, key=lambda ap: math.dist(ap.position, position)).name


def _random_point(rng: random.Random, layout: CampusLayout, zone_name: str) -> tuple[float, float]:
    zone, m = layout.zones[zone_name], layout.margin_m
    return (
        round(rng.uniform(zone.x_min + m, zone.x_max - m), 1),
        round(rng.uniform(zone.y_min + m, zone.y_max - m), 1),
    )


def station_number(name: str) -> int:
    """sta2 sorts before sta10."""
    return int(re.sub(r"\D", "", name) or 0)
