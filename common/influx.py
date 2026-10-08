"""InfluxDB access shared by telemetry, the twin and the experiments (deviation #10).

Standard library only, plus the record models of common/schemas.py:

- `TAGS` / `RUN_TAGS`: which fields of each measurement are tags (PROJECT_PLAN §7.1).
- `rows_query()`: Flux for the rows of one measurement, optionally one run, one row per series
  and timestamp. Names are checked against `Identifier` before they go into the query.
- `query_csv()`: run Flux over HTTP (`/api/v2/query`, CSV out); http(s) URLs only.
- `parse_flux_csv()`: that CSV into typed rows.

The token is read from the environment by `InfluxConnection.from_env()` and never printed.
"""

from __future__ import annotations

import csv
import io
import os
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, get_args

from pydantic import TypeAdapter, ValidationError

from common.schemas import (
    APStats,
    FlowStats,
    Identifier,
    KPIRecord,
    PortStats,
    StationStats,
    TelemetryRecord,
)

RUN_TAGS = ("run_id", "scenario_id")
TAGS: dict[type[TelemetryRecord], tuple[str, ...]] = {  # PROJECT_PLAN §7.1
    PortStats: ("dpid", "port"),
    FlowStats: ("app_class", "dpid", "flow_id"),
    APStats: ("ap", "channel"),
    StationStats: ("ap", "sta"),
    KPIRecord: ("app_class", "flow_id"),
}
_DROP = {"", "result", "table", "_start", "_stop", "_measurement"}
_IDENTIFIER: TypeAdapter[str] = TypeAdapter(Identifier)


@dataclass(frozen=True)
class InfluxConnection:
    """Where InfluxDB is: URL, org, bucket and API token."""

    url: str
    org: str
    bucket: str
    token: str = field(repr=False)  # never printed

    @classmethod
    def from_env(cls) -> InfluxConnection:
        """INFLUXDB_URL/ORG/TOKEN (and INFLUXDB_BUCKET, default telemetry) from the environment."""
        missing = [
            k for k in ("INFLUXDB_URL", "INFLUXDB_ORG", "INFLUXDB_TOKEN") if not os.getenv(k)
        ]
        if missing:
            raise ValueError(f"set {', '.join(missing)} (from .env)")
        return cls(
            os.environ["INFLUXDB_URL"],
            os.environ["INFLUXDB_ORG"],
            os.getenv("INFLUXDB_BUCKET", "telemetry"),
            os.environ["INFLUXDB_TOKEN"],
        )


def is_http_url(url: str) -> bool:
    """Only http(s) URLs are ever opened (no file:// or custom schemes; bandit B310)."""
    return urllib.parse.urlsplit(url).scheme in ("http", "https")


def rows_query(
    bucket: str, measurement: str, start: datetime, stop: datetime, run_id: str | None = None
) -> str:
    """Flux: rows of `measurement` (of one run, if given), pivoted to one row per series and ts."""
    for value in (bucket, measurement, *([run_id] if run_id is not None else [])):
        try:  # interpolated into Flux: identifiers only
            _IDENTIFIER.validate_python(value)
        except ValidationError as exc:
            raise ValueError(f"not a safe identifier for a Flux query: {value!r}") from exc
    match = f'r._measurement == "{measurement}"'
    if run_id is not None:
        match += f' and r.run_id == "{run_id}"'
    return (
        f'from(bucket: "{bucket}")\n'
        f"  |> range(start: {start.isoformat()}, stop: {stop.isoformat()})\n"
        f"  |> filter(fn: (r) => {match})\n"
        '  |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")\n'
        "  |> group()\n"
    )


def query_csv(
    conn: InfluxConnection,
    flux: str,
    timeout_s: float,
    opener: Callable[..., Any] = urllib.request.urlopen,  # Any: urlopen's overloads; tests fake it
) -> str:
    """Run `flux` on InfluxDB; the result as CSV text."""
    if not is_http_url(conn.url):
        raise ValueError("InfluxDB URL must be an http(s) URL")
    url = conn.url.rstrip("/") + "/api/v2/query?" + urllib.parse.urlencode({"org": conn.org})
    request = urllib.request.Request(  # noqa: S310 - scheme checked above
        url,
        data=flux.encode(),
        method="POST",
        headers={
            "Authorization": f"Token {conn.token}",
            "Accept": "application/csv",
            "Content-Type": "application/vnd.flux",
        },
    )
    with opener(request, timeout=timeout_s) as response:
        return str(response.read().decode())


def parse_flux_csv(text: str, model: type[TelemetryRecord]) -> list[dict[str, Any]]:
    """Rows of a pivoted, ungrouped Flux result (`Accept: application/csv`), typed per `model`.

    `_time` becomes `ts`; tags stay strings; integer schema fields become int, the rest float.
    Rows are dicts (Any: the value type depends on the column).
    """
    header: list[str] | None = None
    is_int: dict[str, bool] = {}  # per column, worked out once (millions of cells in an export)
    rows = []
    tags = {*TAGS[model], *RUN_TAGS}
    for line in csv.reader(io.StringIO(text)):
        if not any(line):
            continue
        if line[1:3] == ["result", "table"]:
            header = line
            continue
        if header is None:
            raise ValueError("Flux CSV row before its header")
        row: dict[str, Any] = {}
        for name, value in zip(header, line, strict=True):
            if name in _DROP:
                continue
            if name == "_time":
                row["ts"] = datetime.fromisoformat(value.replace("Z", "+00:00"))
            elif name in tags or value == "":
                row[name] = value or None
            else:
                if name not in is_int:
                    is_int[name] = is_int_field(model, name)
                row[name] = int(value) if is_int[name] else float(value)
        rows.append(row)
    return rows


def is_int_field(model: type[TelemetryRecord], name: str) -> bool:
    """True for integer fields of a record model (Influx `i` suffix, int64 columns)."""
    annotation = model.model_fields[name].annotation
    return annotation is int or (int in get_args(annotation) and float not in get_args(annotation))
