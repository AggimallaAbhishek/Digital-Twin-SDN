"""TwinState: the twin's view of the network at one moment (PROJECT_PLAN §7.2).

Defined early (decision P4.3-A) so the heuristics (P4.3), the simulator (P3.3) and the loop share
one type; P3.1 builds it from InfluxDB and extends it (links, flows) as those consumers need.
Treat instances as immutable: simulations work on modified copies (RULEBOOK C-7).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType


@dataclass(frozen=True)
class APState:
    """One access point: where it is, its channel, whether it is up, and its utilisation."""

    name: str
    position: tuple[float, float]
    channel: int
    up: bool
    util: float  # share of its current capacity in use, 0-1 (ap_stats.channel_util, deviation #8)
    tx_power_dbm: float | None = None


@dataclass(frozen=True)
class StationState:
    """One station: where it is and which AP it is on (None if not associated)."""

    name: str
    position: tuple[float, float]
    ap: str | None
    zone: str | None = None  # campus zone the station is in (config/campus_v1.yaml zones)


@dataclass(frozen=True)
class FlowState:
    """One traffic flow's latest measured KPIs (P1.5 probe), as the simulator's demand input."""

    flow_id: str
    sta: str
    app_class: str
    throughput_mbps: float
    latency_ms: float
    loss_pct: float
    queue_id: int = 0  # OVS QoS queue (common/schemas.py QOS_QUEUE_IDS; 0 = best effort)
    rate_limit_mbps: float | None = None
    path: tuple[str, ...] = ()  # explicit route after a reroute_flow; () = the default path


@dataclass(frozen=True)
class TwinState:
    """The network at `ts`. A station's AP is stored once, on the station."""

    ts: datetime
    aps: Mapping[str, APState]
    stations: Mapping[str, StationState]
    flows: Mapping[str, FlowState] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # read-only views of private copies: the state can't change under its users (C-7)
        object.__setattr__(self, "aps", MappingProxyType(dict(self.aps)))
        object.__setattr__(self, "stations", MappingProxyType(dict(self.stations)))
        object.__setattr__(self, "flows", MappingProxyType(dict(self.flows)))

    def clients(self, ap: str) -> tuple[str, ...]:
        """Stations associated with `ap`, in station order (sta2 before sta10)."""
        names = [s.name for s in self.stations.values() if s.ap == ap]
        return tuple(sorted(names, key=_station_number))

    def up_aps(self) -> list[APState]:
        """APs that are up, by name."""
        return [ap for name, ap in sorted(self.aps.items()) if ap.up]


def _station_number(name: str) -> int:
    return int(re.sub(r"\D", "", name) or 0)
