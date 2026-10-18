"""P3.1 TwinState builder: the latest telemetry of each series -> one TwinState (pure).

twin/state/sync.py feeds it the last few seconds of a run from InfluxDB. Rules:

- Each AP, station and flow takes its **latest** record in the snapshot.
- An AP is **up** if it reported within `stale_s` of `now`: a disabled AP stops sending stats
  (its channel would be null, which the schema rejects). Otherwise it is down, on its last
  known channel (or the configured one) with zero utilisation.
- An AP, station or KPI row with an empty cell the twin needs is ignored: the series keeps its
  latest complete record, and a station or flow with none is left out.
- AP positions come from config/campus_v1.yaml; station positions from their own telemetry.
- `ts` is the time up to which every measurement is known: the oldest of the newest ap_stats,
  sta_stats and kpi records (measurements without rows in the snapshot don't count). So
  lag = now - ts grows when any measurement stops arriving, even if the others keep flowing.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from twin.state.model import APState, FlowState, StationState, TwinState


@dataclass(frozen=True)
class CampusAPs:
    """What the campus config says: each AP's position and planned channel, and the zones."""

    positions: dict[str, tuple[float, float]]
    channels: dict[str, int]
    zones: dict[str, tuple[tuple[float, float], tuple[float, float]]]  # name -> (x range, y range)

    def zone_of(self, position: tuple[float, float]) -> str | None:
        """The zone containing `position` (edges included), or None."""
        x, y = position
        for name, ((x0, x1), (y0, y1)) in self.zones.items():
            if x0 <= x <= x1 and y0 <= y <= y1:
                return name
        return None


class NoTelemetryError(ValueError):
    """No telemetry yet in the window (the run has not started): not yet, rather than wrong."""


@dataclass(frozen=True)
class Snapshot:
    """Recent telemetry rows (common.influx.parse_flux_csv) of one run, any order.

    Rows are column -> value dicts (Any: str tags, int/float fields, datetime ts, None)."""

    ap_rows: list[dict[str, Any]]
    sta_rows: list[dict[str, Any]]
    kpi_rows: list[dict[str, Any]]


def load_campus_aps(campus: Mapping[str, Any]) -> CampusAPs:
    """AP positions, planned channels and zones from a parsed config/campus_v1.yaml."""
    aps = campus["aps"]
    return CampusAPs(
        positions={a["name"]: (float(a["position"][0]), float(a["position"][1])) for a in aps},
        channels={a["name"]: int(a["channel"]) for a in aps},
        zones={
            name: ((float(z["x"][0]), float(z["x"][1])), (float(z["y"][0]), float(z["y"][1])))
            for name, z in campus.get("zones", {}).items()
        },
    )


_AP_FIELDS = ("ts", "ap", "channel", "channel_util")
_STA_FIELDS = ("ts", "sta", "x", "y")
_KPI_FIELDS = ("ts", "flow_id", "app_class", "throughput_mbps", "latency_ms", "loss_pct")


def _complete(rows: Iterable[dict[str, Any]], fields: tuple[str, ...]) -> list[dict[str, Any]]:
    """The rows with a value in every field the twin needs: the pivoted Flux result can leave a
    cell empty (None), and such a row is ignored in favour of the series' last complete one."""
    return [r for r in rows if all(r.get(k) is not None for k in fields)]


def build_state(snapshot: Snapshot, campus: CampusAPs, now: datetime, stale_s: float) -> TwinState:
    """The network as the latest telemetry describes it; ValueError if there is none."""
    # empty cells found live: ap_stats (V3 loop), kpi (demo); sta_stats filtered the same way.
    # Filtered first, so a dropped row cannot make the state look fresher than it is.
    ap_ok = _complete(snapshot.ap_rows, _AP_FIELDS)
    sta_ok = _complete(snapshot.sta_rows, _STA_FIELDS)
    kpi_ok = _complete(snapshot.kpi_rows, _KPI_FIELDS)
    newest = [max(r["ts"] for r in rows) for rows in (ap_ok, sta_ok, kpi_ok) if rows]
    if not newest:
        raise NoTelemetryError("no telemetry in the snapshot")
    ap_rows = _latest(ap_ok, "ap")
    aps = {}
    for name, position in campus.positions.items():
        row = ap_rows.get(name)
        up = row is not None and (now - row["ts"]).total_seconds() <= stale_s
        channel = int(row["channel"]) if row is not None else campus.channels[name]
        util = float(row["channel_util"]) if row is not None and up else 0.0
        power = row.get("tx_power_dbm") if row is not None else None  # None: empty Flux cell
        power = float(power) if power is not None else None
        aps[name] = APState(name, position, channel, up, util, power)
    stations = {}
    for name, r in _latest(sta_ok, "sta").items():
        position = (float(r["x"]), float(r["y"]))
        stations[name] = StationState(name, position, r.get("ap"), campus.zone_of(position))
    flows = {
        fid: FlowState(
            flow_id=fid,
            sta=fid.split("-", 1)[0],
            app_class=r["app_class"],
            throughput_mbps=float(r["throughput_mbps"]),
            latency_ms=float(r["latency_ms"]),
            loss_pct=float(r["loss_pct"]),
        )
        for fid, r in _latest(kpi_ok, "flow_id").items()
    }
    return TwinState(min(newest), aps, stations, flows)


def lag_s(state: TwinState, now: datetime) -> float:
    """How old the state is at `now` (seconds): the stalest measurement's newest record."""
    return (now - state.ts).total_seconds()


def _latest(rows: Iterable[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        name = row[key]
        if name not in latest or row["ts"] > latest[name]["ts"]:
            latest[name] = row
    return latest
