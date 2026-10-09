"""P4.5 / H1: time to recover after the flash crowd, V1 (no loop) against V3 (full loop).

    uv run python -m experiments.analysis.recovery_report --v1 data/v1 --v3 data/loopv3-v1

For every lecture_flash_crowd run: the affected AP (busiest after onset) and the seconds until
it is back under 80% with video p95 latency <= 50 ms for 15 s (experiments/analysis/
time_to_recover.py, decision P4.5-A). A run that never recovers counts as "> run end" (the
seconds from onset to the end of the run). Writes models/loop/v1/recovery.json.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from experiments.analysis.time_to_recover import RecoveryRule, affected_ap, time_to_recover
from experiments.batch import load_scenario
from experiments.dataset import disruption
from experiments.shell import git_commit

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "models" / "loop" / "v1"
SCENARIO = "lecture_flash_crowd"


def recoveries(dataset: Path, rule: RecoveryRule) -> dict[str, dict[str, Any]]:
    """{run_id: {ap, seed, ttr_s or None}} for the flash-crowd runs of a dataset."""
    rows: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    columns = {
        "ap_stats": ["run_id", "scenario_id", "seed", "t_s", "ap", "channel_util"],
        "kpi": ["run_id", "scenario_id", "t_s", "app_class", "latency_ms"],
    }
    for name, cols in columns.items():
        only = [("scenario_id", "==", SCENARIO)]
        for row in pq.read_table(
            dataset / f"{name}.parquet", columns=cols, filters=only
        ).to_pylist():
            rows[row["run_id"]][name].append(row)
    scenario = load_scenario(SCENARIO)
    onset = disruption(scenario)
    assert onset is not None  # noqa: S101 - the flash crowd always has one
    out = {}
    for run_id, tables in sorted(rows.items()):
        ap = affected_ap(tables["ap_stats"], onset.at_s)
        ttr = time_to_recover(tables["ap_stats"], tables["kpi"], ap, onset.at_s, rule)
        out[run_id] = {"seed": tables["ap_stats"][0]["seed"], "ap": ap, "ttr_s": ttr}
    return out


def main(argv: list[str] | None = None) -> int:
    """Report V1 and V3 recovery; 0 always (the report is the deliverable)."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--v1", type=Path, default=ROOT / "data" / "v1")
    parser.add_argument("--v3", type=Path, default=ROOT / "data" / "loopv3-v1")
    args = parser.parse_args(argv)
    rule = RecoveryRule()
    scenario = load_scenario(SCENARIO)
    onset = disruption(scenario)
    assert onset is not None  # noqa: S101 - the flash crowd always has one
    censored = scenario.duration_s - onset.at_s
    report: dict[str, Any] = {
        "created": datetime.now(UTC).isoformat(timespec="seconds"),
        "git_commit": git_commit(),
        "rule": vars(rule) | {"decision": "P4.5-A"},
        "run_end_after_onset_s": censored,
        "V1": recoveries(args.v1, rule),
        "V3": recoveries(args.v3, rule),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "recovery.json").write_text(json.dumps(report, indent=1))
    for mode in ("V1", "V3"):
        for run_id, r in report[mode].items():
            ttr = f"{r['ttr_s']:.0f} s" if r["ttr_s"] is not None else f"> {censored:.0f} s (never)"
            print(f"RECOVERY {mode} {run_id} seed={r['seed']} ap={r['ap']}: {ttr}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
