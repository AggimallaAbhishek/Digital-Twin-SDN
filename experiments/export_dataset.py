"""P2.3 dataset export: a finished batch (data/raw/<version>/) -> data/<version>/*.parquet.

    make dataset                       # version from experiments/batch_v1.yaml
    uv run python -m experiments.export_dataset --version v1

Reads data/raw/<version>/batch.json (experiments/run_batch.py), and for every run that passed
queries its telemetry from InfluxDB, labels the rows (experiments/dataset.py: run, seed, split,
t_s, phase, event) and writes one Parquet file per measurement plus manifest.json (scenarios,
seeds, splits, commit, row counts, hours of telemetry; RULEBOOK E-3). A released version is
never edited: export a new version instead. Format and columns: docs/dataset.md.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
from pydantic import TypeAdapter, ValidationError

from common.schemas import (
    MEASUREMENTS,
    APStats,
    FlowStats,
    Identifier,
    KPIRecord,
    PortStats,
    StationStats,
    TelemetryRecord,
)
from experiments.batch import SPLITS, load_scenario, run_ok
from experiments.dataset import RunInfo, disruption, label_rows, parse_flux_csv, to_table
from experiments.shell import git_commit
from telemetry.collector.collector import is_http_url

ROOT = Path(__file__).resolve().parents[1]
EXPORTED: tuple[type[TelemetryRecord], ...] = (
    PortStats,
    FlowStats,
    APStats,
    StationStats,
    KPIRecord,
)
_IDENTIFIER: TypeAdapter[str] = TypeAdapter(Identifier)
MARGIN = timedelta(seconds=5)  # query window around the scenario clock
QUERY_TIMEOUT_S = 120


def influx_csv(flux: str) -> str:
    """Run a Flux query against InfluxDB (INFLUXDB_URL/ORG/TOKEN from .env); CSV text."""
    if not is_http_url(os.environ["INFLUXDB_URL"]):
        raise SystemExit("export_dataset: INFLUXDB_URL must be an http(s) URL")
    url = os.environ["INFLUXDB_URL"].rstrip("/") + "/api/v2/query?"
    url += urllib.parse.urlencode({"org": os.environ["INFLUXDB_ORG"]})
    request = urllib.request.Request(  # noqa: S310 - URL from INFLUXDB_URL
        url,
        data=flux.encode(),
        method="POST",
        headers={
            "Authorization": f"Token {os.environ['INFLUXDB_TOKEN']}",
            "Accept": "application/csv",
            "Content-Type": "application/vnd.flux",
        },
    )
    with urllib.request.urlopen(request, timeout=QUERY_TIMEOUT_S) as response:  # noqa: S310  # nosec B310 - scheme checked above
        return str(response.read().decode())


def run_query(measurement: str, run_id: str, start: datetime, stop: datetime) -> str:
    """Flux for one run's rows of one measurement, one row per series and timestamp."""
    bucket = os.getenv("INFLUXDB_BUCKET", "telemetry")
    for value in (measurement, run_id, bucket):  # interpolated into Flux: identifiers only
        try:
            _IDENTIFIER.validate_python(value)
        except ValidationError as exc:
            raise ValueError(f"not a safe identifier for a Flux query: {value!r}") from exc
    return (
        f'from(bucket: "{bucket}")\n'
        f"  |> range(start: {start.isoformat()}, stop: {stop.isoformat()})\n"
        f'  |> filter(fn: (r) => r._measurement == "{measurement}" and r.run_id == "{run_id}")\n'
        '  |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")\n'
        "  |> group()\n"
    )


def scenario_start(run_dir: Path) -> datetime:
    """UTC time the scenario clock started (events.jsonl `started` event, P2.3)."""
    for line in (run_dir / "events.jsonl").read_text().splitlines():
        event = json.loads(line)
        if event["kind"] == "started":
            return datetime.fromisoformat(event["utc"])
    raise ValueError(f"{run_dir}/events.jsonl has no started event")


def export(version: str) -> dict[str, Any]:
    """Export every passed run of data/raw/<version>/ to data/<version>/; return the manifest.

    Each run is written as soon as it is queried (one ParquetWriter per measurement), so memory
    holds one run of one measurement at a time, not the whole dataset.
    """
    raw = ROOT / "data" / "raw" / version
    batch = json.loads((raw / "batch.json").read_text())
    runs = [r for r in batch["runs"] if run_ok(r)]
    out = ROOT / "data" / version
    out.mkdir(parents=True, exist_ok=True)
    counts = {MEASUREMENTS[m]: dict.fromkeys(SPLITS, 0) for m in EXPORTED}
    writers = {
        MEASUREMENTS[m]: pq.ParquetWriter(
            out / f"{MEASUREMENTS[m]}.parquet", to_table([], m).schema
        )
        for m in EXPORTED
    }
    try:
        for r in runs:
            info = RunInfo(r["run_id"], r["scenario"], r["seed"], r["split"])
            for model, rows in _run_rows(raw, info):
                writers[MEASUREMENTS[model]].write_table(to_table(rows, model))
                counts[MEASUREMENTS[model]][info.split] += len(rows)
    finally:
        for writer in writers.values():
            writer.close()
    seconds = sum(load_scenario(r["scenario"]).duration_s for r in runs)
    manifest = _manifest(version, batch, runs, seconds, counts)
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1))
    return manifest


def _run_rows(
    raw: Path, info: RunInfo
) -> Iterator[tuple[type[TelemetryRecord], list[dict[str, Any]]]]:
    """One run's labelled rows, measurement by measurement."""
    scenario = load_scenario(info.scenario_id)
    t0 = scenario_start(raw / info.run_id)
    start, stop = t0 - MARGIN, t0 + timedelta(seconds=scenario.duration_s) + MARGIN
    onset = disruption(scenario)
    for model in EXPORTED:
        query = run_query(MEASUREMENTS[model], info.run_id, start, stop)
        yield model, label_rows(parse_flux_csv(influx_csv(query), model), info, t0, onset)


def _manifest(
    version: str,
    batch: dict[str, Any],
    runs: list[dict[str, Any]],
    seconds: float,
    counts: dict[str, dict[str, int]],
) -> dict[str, Any]:
    """What the dataset is and how it was made (RULEBOOK E-3)."""
    return {
        "dataset_version": version,
        "created": datetime.now(UTC).isoformat(timespec="seconds"),
        "git_commit": git_commit(),
        "batch_commit": batch.get("git_commit"),
        "config_hash": batch.get("config_hash"),
        "scenarios": sorted({r["scenario"] for r in runs}),
        "seeds": {str(r["seed"]): r["split"] for r in runs},
        "telemetry_hours": round(seconds / 3600, 2),
        "runs": [{k: r[k] for k in ("run_id", "scenario", "seed", "split")} for r in runs],
        "skipped_runs": [r["run_id"] for r in batch["runs"] if r not in runs],
        "rows": counts,
    }


def main(argv: list[str] | None = None) -> int:
    """CLI entry point; 0 when at least one run was exported."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--version", required=True, help="dataset version, e.g. v1")
    args = parser.parse_args(argv)
    manifest = export(args.version)
    total = sum(sum(c.values()) for c in manifest["rows"].values())
    print(
        f"EXPORT_RESULT version={args.version} runs={len(manifest['runs'])} "
        f"hours={manifest['telemetry_hours']} rows={total} skipped={manifest['skipped_runs']}"
    )
    return 0 if manifest["runs"] else 1


if __name__ == "__main__":
    sys.exit(main())
