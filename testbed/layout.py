"""Campus layout: load and validate config/campus_v1.yaml, and place stations deterministically.

Pure Python (no Mininet import) so it is unit-tested on the Mac and reused on the VM.
Must stay Python 3.8-compatible (ADR-003).
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

VALID_CHANNELS_24GHZ = (1, 6, 11)


@dataclass(frozen=True)
class Zone:
    """Axis-aligned rectangular zone in metres."""

    name: str
    x_min: float
    x_max: float
    y_min: float
    y_max: float

    def contains(self, x: float, y: float) -> bool:
        """Return True if (x, y) lies inside the zone (edges included)."""
        return self.x_min <= x <= self.x_max and self.y_min <= y <= self.y_max


@dataclass(frozen=True)
class APSpec:
    """One access point from the layout."""

    name: str
    zone: str
    position: tuple[float, float]
    channel: int
    mode: str


@dataclass(frozen=True)
class ServerSpec:
    """One wired server (traffic endpoint)."""

    name: str
    ip: str
    switch: str
    bw_mbps: float


@dataclass(frozen=True)
class StationSpec:
    """One placed station: name, address, zone, position and the AP it starts on."""

    name: str
    ip: str
    zone: str
    position: tuple[float, float]
    ap: str


@dataclass(frozen=True)
class CampusLayout:
    """Validated campus layout."""

    name: str
    area_m: tuple[float, float]
    propagation_model: str
    propagation_exp: float
    wmediumd_mode: str
    zones: dict[str, Zone]
    aps: list[APSpec]
    switches: list[str]
    wired_links: list[tuple[str, str, float]]
    servers: list[ServerSpec]
    station_count: int
    ip_prefix: str
    seed: int
    margin_m: float
    initial: dict[str, int]

    def ap_for_zone(self, zone: str) -> APSpec:
        """Return the AP that serves `zone`."""
        for ap in self.aps:
            if ap.zone == zone:
                return ap
        raise ValueError(f"no AP serves zone {zone!r}")


def load_layout(path: Path | str) -> CampusLayout:
    """Load and validate a layout YAML file."""
    data = yaml.safe_load(Path(path).read_text())
    if not isinstance(data, dict):
        raise ValueError(f"{path}: layout must be a mapping")
    return layout_from_dict(data)


def layout_from_dict(data: Mapping[str, Any]) -> CampusLayout:
    """Build a CampusLayout from parsed YAML, raising ValueError on any inconsistency."""
    area_w, area_h = (float(v) for v in data["area_m"])
    zones = _parse_zones(data["zones"], area_w, area_h)
    aps = _parse_aps(data["aps"], zones)
    switches = [str(s) for s in data["switches"]]
    servers = [
        ServerSpec(str(s["name"]), str(s["ip"]), str(s["switch"]), float(s["bw_mbps"]))
        for s in data.get("servers", [])
    ]
    nodes = {ap.name for ap in aps} | set(switches) | {s.name for s in servers}
    links = _parse_links(data["wired_links"], nodes)
    for server in servers:
        if server.switch not in switches:
            raise ValueError(f"server {server.name}: unknown node {server.switch!r}")

    sta = data["stations"]
    count, margin = int(sta["count"]), float(sta["margin_m"])
    initial = {str(z): int(n) for z, n in sta["initial"].items()}
    for zone_name in initial:
        if zone_name not in zones:
            raise ValueError(f"stations.initial: unknown zone {zone_name!r}")
    if sum(initial.values()) != count:
        raise ValueError(f"stations.initial must sum to count={count}, got {sum(initial.values())}")
    for zone in zones.values():
        if 2 * margin >= min(zone.x_max - zone.x_min, zone.y_max - zone.y_min):
            raise ValueError(f"stations.margin_m={margin} too large for zone {zone.name!r}")

    prop = data["propagation"]
    return CampusLayout(
        name=str(data["name"]),
        area_m=(area_w, area_h),
        propagation_model=str(prop["model"]),
        propagation_exp=float(prop["exp"]),
        wmediumd_mode=str(data["wmediumd_mode"]),
        zones=zones,
        aps=aps,
        switches=switches,
        wired_links=links,
        servers=servers,
        station_count=count,
        ip_prefix=str(sta["ip_prefix"]),
        seed=int(sta["seed"]),
        margin_m=margin,
        initial=initial,
    )


def place_stations(layout: CampusLayout) -> list[StationSpec]:
    """Place stations at seeded random points inside their starting zone (deterministic)."""
    rng = random.Random(layout.seed)  # noqa: S311 - simulated station placement, not security
    stations: list[StationSpec] = []
    index = 1
    for zone_name, n in layout.initial.items():
        zone = layout.zones[zone_name]
        ap = layout.ap_for_zone(zone_name)
        m = layout.margin_m
        for _ in range(n):
            x = round(rng.uniform(zone.x_min + m, zone.x_max - m), 1)
            y = round(rng.uniform(zone.y_min + m, zone.y_max - m), 1)
            stations.append(
                StationSpec(
                    f"sta{index}", f"{layout.ip_prefix}{index}/8", zone_name, (x, y), ap.name
                )
            )
            index += 1
    return stations


def _parse_zones(raw: Mapping[str, Any], area_w: float, area_h: float) -> dict[str, Zone]:
    zones: dict[str, Zone] = {}
    for name, box in raw.items():
        (x0, x1), (y0, y1) = box["x"], box["y"]
        zone = Zone(str(name), float(x0), float(x1), float(y0), float(y1))
        if not (0 <= zone.x_min < zone.x_max <= area_w and 0 <= zone.y_min < zone.y_max <= area_h):
            raise ValueError(f"zone {name!r} is empty or outside the {area_w}x{area_h} m area")
        zones[str(name)] = zone
    return zones


def _parse_aps(raw: list[Mapping[str, Any]], zones: dict[str, Zone]) -> list[APSpec]:
    aps: list[APSpec] = []
    seen = set()
    for item in raw:
        name = str(item["name"])
        if name in seen:
            raise ValueError(f"duplicate AP name {name!r}")
        seen.add(name)
        zone = str(item["zone"])
        if zone not in zones:
            raise ValueError(f"AP {name}: unknown zone {zone!r}")
        x, y = (float(v) for v in item["position"])
        if not zones[zone].contains(x, y):
            raise ValueError(f"AP {name}: position ({x}, {y}) is outside zone {zone!r}")
        channel = int(item["channel"])
        if channel not in VALID_CHANNELS_24GHZ:
            raise ValueError(f"AP {name}: channel {channel} not in {VALID_CHANNELS_24GHZ}")
        aps.append(APSpec(name, zone, (x, y), channel, str(item["mode"])))
    return aps


def _parse_links(raw: list[list[Any]], nodes: set[str]) -> list[tuple[str, str, float]]:
    links: list[tuple[str, str, float]] = []
    for a, b, bw in raw:
        for node in (a, b):
            if node not in nodes:
                raise ValueError(f"wired link {a}-{b}: unknown node {node!r}")
        if float(bw) <= 0:
            raise ValueError(f"wired link {a}-{b}: bandwidth must be > 0, got {bw}")
        links.append((str(a), str(b), float(bw)))
    return links
