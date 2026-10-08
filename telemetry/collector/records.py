"""Collector records (P2.1): VM responses -> common.schemas records -> InfluxDB line protocol.

Validation happens here, on arrival (RULEBOOK C-2): a record that does not fit its schema is
dropped and its reason returned, never written. Mappings follow the contract tests in
tests/contract/ (Ryu: P1.2, AP agent: P1.3, KPI probe: P1.5). Measurements, tags and fields
follow PROJECT_PLAN §7.1; every line also carries scenario_id and run_id as tags.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from common.schemas import (
    MEASUREMENTS,
    APStats,
    FlowStats,
    KPIRecord,
    PortStats,
    StationStats,
    TelemetryRecord,
)

FLOW_FIELDS = ("ts", "dpid", "flow_id", "app_class", "bytes", "pkts", "duration_s", "bps")
RUN_TAGS = ("run_id", "scenario_id")
TAGS: dict[type[TelemetryRecord], tuple[str, ...]] = {  # PROJECT_PLAN §7.1
    PortStats: ("dpid", "port"),
    FlowStats: ("app_class", "dpid", "flow_id"),
    APStats: ("ap", "channel"),
    StationStats: ("ap", "sta"),
    KPIRecord: ("app_class", "flow_id"),
}
_ESCAPE = str.maketrans({",": r"\,", "=": r"\=", " ": r"\ "})


@dataclass(frozen=True)
class Meta:
    """Run labels added to every record (the VM does not know them)."""

    scenario_id: str
    run_id: str


@dataclass
class Batch:
    """Valid records from one response, plus one reason per dropped record."""

    records: list[TelemetryRecord] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def from_ryu_ports(body: Any, meta: Meta) -> Batch:
    """Ryu GET /stats/ports -> PortStats."""
    return _map(body, "ports", PortStats, meta)


def from_ryu_flows(body: Any, meta: Meta) -> Batch:
    """Ryu GET /stats/flows -> FlowStats (controller extras such as `match` dropped)."""
    return _map(
        body, "flows", FlowStats, meta, pick=lambda r: {k: r[k] for k in r if k in FLOW_FIELDS}
    )


def from_ap_stats(body: Any, meta: Meta) -> Batch:
    """AP agent GET /aps/{ap}/stats (one record with its own ts) -> APStats."""
    return _map({"records": [body]}, "records", APStats, meta)


def from_stations(body: Any, meta: Meta) -> Batch:
    """AP agent GET /stations -> StationStats (records take the response's ts)."""
    ts = body.get("ts") if isinstance(body, Mapping) else None
    return _map(body, "stations", StationStats, meta, pick=lambda r: {**r, "ts": ts})


def from_kpis(body: Any, meta: Meta) -> Batch:
    """AP agent GET /kpi -> KPIRecord (one per traffic flow, each with its own ts)."""
    return _map(body, "kpis", KPIRecord, meta)


def line_protocol(record: TelemetryRecord) -> str:
    """One InfluxDB line: `measurement,tags fields ts_ns` (sorted; None values left out)."""
    values = record.model_dump(exclude={"ts"})
    tag_names = (*TAGS[type(record)], *RUN_TAGS)
    tags = sorted((k, values[k]) for k in tag_names if values.get(k) is not None)
    fields = sorted((k, v) for k, v in values.items() if k not in tag_names and v is not None)
    tag_part = "".join(f",{k}={str(v).translate(_ESCAPE)}" for k, v in tags)
    field_part = ",".join(f"{k}={_field(v)}" for k, v in fields)
    ts_ns = int(record.ts.timestamp()) * 1_000_000_000 + record.ts.microsecond * 1000
    return f"{MEASUREMENTS[type(record)]}{tag_part} {field_part} {ts_ns}"


def _map(
    body: Any,
    key: str,
    model: type[TelemetryRecord],
    meta: Meta,
    pick: Callable[[Mapping[str, Any]], Mapping[str, Any]] = dict,
) -> Batch:
    batch = Batch()
    items = body.get(key) if isinstance(body, Mapping) else None
    if not isinstance(items, list):
        batch.errors.append(f"{model.__name__}: response has no {key!r} list")
        return batch
    for item in items:
        try:
            raw = {**pick(item), "scenario_id": meta.scenario_id, "run_id": meta.run_id}
            batch.records.append(model.model_validate(raw))
        except (ValidationError, TypeError, KeyError) as exc:
            batch.errors.append(f"{model.__name__}: {_reason(exc)}")
    return batch


def _reason(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
    return f"{type(exc).__name__}: {exc}"


def _field(value: float) -> str:
    """Telemetry fields are all numeric (common/schemas.py): ints get Influx's `i` suffix."""
    return f"{value}i" if isinstance(value, int) else repr(float(value))
