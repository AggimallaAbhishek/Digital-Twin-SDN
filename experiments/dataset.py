"""P2.3 dataset export logic: InfluxDB CSV -> labelled rows -> one Parquet table per measurement.

Pure (no I/O): experiments/export_dataset.py does the querying and writing. Labels (decision
P2.3-C): every row carries its run's scenario_id, run_id, seed and split, `t_s` (seconds since
the scenario started), `phase` (`normal` before the scenario's disruption, `stress` from it on)
and `event` (which disruption the run has: flash_crowd, ap_down, force_channel; None for normal).
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import datetime
from typing import Any, get_args

import pyarrow as pa

from common.schemas import Scenario, TelemetryRecord
from telemetry.collector.records import RUN_TAGS, TAGS

LABELS = ("seed", "split", "t_s", "phase", "event")
_DROP = {"", "result", "table", "_start", "_stop", "_measurement"}
_LABEL_TYPES = {
    "seed": pa.int64(),
    "split": pa.string(),
    "t_s": pa.float64(),
    "phase": pa.string(),
    "event": pa.string(),
}


@dataclass(frozen=True)
class Disruption:
    """When a scenario's stress starts (scenario time) and what causes it."""

    at_s: float
    name: str


@dataclass(frozen=True)
class RunInfo:
    """A batch run's identity (experiments/batch.py RunPlan, read back from batch.json)."""

    run_id: str
    scenario_id: str
    seed: int
    split: str


def parse_flux_csv(text: str, model: type[TelemetryRecord]) -> list[dict[str, Any]]:
    """Rows of a pivoted, ungrouped Flux result (`Accept: application/csv`), typed per `model`.

    `_time` becomes `ts`; tags stay strings; integer schema fields become int, the rest float.
    """
    reader = csv.reader(io.StringIO(text))
    header: list[str] | None = None
    rows = []
    tags = {*TAGS[model], *RUN_TAGS}
    for line in reader:
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
                row[name] = int(value) if _is_int_field(model, name) else float(value)
        rows.append(row)
    return rows


def disruption(scenario: Scenario) -> Disruption | None:
    """The scenario's first disruption: its first scripted event, else (for a crowd scenario)
    the first traffic that starts once the crowd moves; None for a normal scenario."""
    if scenario.events:
        first = min(scenario.events, key=lambda e: e.at_s)
        return Disruption(first.at_s, first.type)
    if scenario.mobility.groups:
        moves = min(g.start_s for g in scenario.mobility.groups)
        after = [t.start_s for t in scenario.traffic if t.start_s >= moves]
        return Disruption(min(after), "flash_crowd") if after else Disruption(moves, "crowd_move")
    return None


def label_rows(
    rows: list[dict[str, Any]], run: RunInfo, t0: datetime, onset: Disruption | None
) -> list[dict[str, Any]]:
    """Copies of `rows` with the run's labels; `t0` is the scenario start (events.jsonl `utc`)."""
    labelled = []
    for row in rows:
        t_s = round((row["ts"] - t0).total_seconds(), 3)
        stress = onset is not None and t_s >= onset.at_s
        labelled.append(
            {
                **row,
                "seed": run.seed,
                "split": run.split,
                "t_s": t_s,
                "phase": "stress" if stress else "normal",
                "event": onset.name if onset else None,
            }
        )
    return labelled


def to_table(rows: list[dict[str, Any]], model: type[TelemetryRecord]) -> pa.Table:
    """A Parquet-ready table: ts, run labels, then tags and fields (stable column order)."""
    tags = sorted(set(TAGS[model]) - set(RUN_TAGS))
    fields = sorted(set(model.model_fields) - {"ts", *TAGS[model], *RUN_TAGS})
    schema = pa.schema(
        [
            ("ts", pa.timestamp("ms", tz="UTC")),
            ("run_id", pa.string()),
            ("scenario_id", pa.string()),
            *((name, _LABEL_TYPES[name]) for name in LABELS),
            *((tag, pa.string()) for tag in tags),
            *((f, pa.int64() if _is_int_field(model, f) else pa.float64()) for f in fields),
        ]
    )
    return pa.Table.from_pylist(rows, schema=schema)


def _is_int_field(model: type[TelemetryRecord], name: str) -> bool:
    annotation = model.model_fields[name].annotation
    return annotation is int or (int in get_args(annotation) and float not in get_args(annotation))
