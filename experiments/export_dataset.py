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
import re
import sys
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
import yaml

from common.schemas import (
    MEASUREMENTS,
    APStats,
    FlowStats,
    KPIRecord,
    PortStats,
    Scenario,
    StationStats,
    TelemetryRecord,
)
from experiments.batch import SPLITS
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
_IDENTIFIER = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")  # = common/schemas.py Identifier
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
        if not _IDENTIFIER.match(value):
            raise ValueError(f"not a safe identifier for a Flux query: {value!r}")
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
    """Export every passed run of data/raw/<version>/ to data/<version>/; return the manifest."""
    raw = ROOT / "data" / "raw" / version
    batch = json.loads((raw / "batch.json").read_text())
    runs = [r for r in batch["runs"] if r.get("passed") and r.get("scenario_ok")]
    tables: dict[str, list[dict[str, Any]]] = {MEASUREMENTS[m]: [] for m in EXPORTED}
    seconds = 0.0
    for r in runs:
        path = ROOT / "experiments" / "scenarios" / f"{r['scenario']}.yaml"
        scenario = Scenario.model_validate(yaml.safe_load(path.read_text()))
        info = RunInfo(r["run_id"], r["scenario"], r["seed"], r["split"])
        t0 = scenario_start(raw / r["run_id"])
        start, stop = t0 - MARGIN, t0 + timedelta(seconds=scenario.duration_s) + MARGIN
        onset = disruption(scenario)
        for model in EXPORTED:
            name = MEASUREMENTS[model]
            rows = parse_flux_csv(influx_csv(run_query(name, info.run_id, start, stop)), model)
            tables[name] += label_rows(rows, info, t0, onset)
        seconds += scenario.duration_s
    out = ROOT / "data" / version
    out.mkdir(parents=True, exist_ok=True)
    counts: dict[str, dict[str, int]] = {}
    for model in EXPORTED:
        name = MEASUREMENTS[model]
        pq.write_table(to_table(tables[name], model), out / f"{name}.parquet")
        counts[name] = {
            split: sum(1 for row in tables[name] if row["split"] == split) for split in SPLITS
        }
    manifest = {
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
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1))
    return manifest


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
