"""P3.5 twin validation on recorded runs: per-flow throughput MAPE (PHASE_PLAN P3.5).

    uv run python -m experiments.analysis.twin_validation                 # data/v1
    uv run python -m experiments.analysis.twin_validation --datasets data/v1 data/actions-v1

For every run: **steady** cases every STEP_S (no action; windows near the run's disruption are
left out), and **action** cases at each scripted event (force_channel -> set_ap_channel, ap_down
/ ap_up -> ap_admin_state; a validation batch adds steer, QoS, tx power and rate limits through
its own `actions.jsonl`). The one fitted parameter, bulk's offered rate, is calibrated on the
train split (median measured bulk throughput) and the MAPE is reported per split before and
after. Writes models/twin/v1/validation.json (RULEBOOK E-4).
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import statistics
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
import yaml

from common.schemas import ACTION_ADAPTER, Action, Scenario
from experiments.batch import load_scenario
from experiments.dataset import disruption
from experiments.shell import git_commit
from twin.radio import load_radio_params
from twin.sim.analytical import SimParams, load_sim_params
from twin.state.builder import load_campus_aps
from twin.validation.validate import (
    Applied,
    Case,
    RunTelemetry,
    TwinModel,
    action_cases,
    steady_cases,
    summary,
)

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "models" / "twin" / "v1"
STEP_S, HORIZON_S = 30.0, 30.0
SETTLE_S, MEASURE_S = 15.0, 30.0  # an AP-down's orphans rejoin after 5 s + ~4 s re-association
QUIET_BEFORE_S, QUIET_AFTER_S = 30.0, 60.0  # steady windows this close to a disruption are skipped
COLUMNS = {
    "ap_stats": ["run_id", "scenario_id", "split", "ts", "t_s", "ap", "channel", "channel_util"],
    "sta_stats": ["run_id", "ts", "t_s", "sta", "ap", "x", "y"],
    "kpi": [
        "run_id",
        "ts",
        "t_s",
        "flow_id",
        "app_class",
        "throughput_mbps",
        "latency_ms",
        "loss_pct",
    ],
}


def load_runs(dataset: Path) -> list[RunTelemetry]:
    """Every run of a dataset directory (P2.3 parquet layout)."""
    rows: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for name, columns in COLUMNS.items():
        for row in pq.read_table(dataset / f"{name}.parquet", columns=columns).to_pylist():
            rows[row["run_id"]][name].append(row)
    runs = []
    for run_id, tables in sorted(rows.items()):
        first = tables["ap_stats"][0]
        runs.append(
            RunTelemetry(
                run_id,
                first["scenario_id"],
                first["split"],
                tables["ap_stats"],
                tables["sta_stats"],
                tables["kpi"],
            )
        )
    return runs


def scripted_actions(scenario: Scenario, created_at: datetime) -> list[Applied]:
    """The scenario's scripted events as the actions they are."""
    applied = []
    for n, event in enumerate(scenario.events, start=1):
        if event.type == "force_channel":
            kind, params = "set_ap_channel", {"ap": event.ap, "channel": event.channel}
        else:
            kind, params = (
                "ap_admin_state",
                {"ap": event.ap, "state": event.type.removeprefix("ap_")},
            )
        action = ACTION_ADAPTER.validate_python(
            {
                "action_id": f"act_validation_{n:03d}",
                "type": kind,
                "source": "operator",
                "reason": f"scripted {event.type} at {event.at_s:g} s",
                "created_at": created_at,
                "params": params,
            }
        )
        applied.append(Applied(event.at_s, action))
    return applied


def batch_actions(dataset: Path, run_id: str) -> list[Applied]:
    """Actions a validation batch applied (actions.jsonl: run_id, t_s, action)."""
    path = dataset / "actions.jsonl"
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        entry = json.loads(line)
        if entry["run_id"] == run_id:
            out.append(Applied(entry["t_s"], _action(entry["action"])))
    return out


def _action(raw: dict[str, Any]) -> Action:  # Any: an action as JSON
    action: Action = ACTION_ADAPTER.validate_python(raw)
    return action


def cases_for(
    run: RunTelemetry,
    applied: list[Applied],
    model: TwinModel,
    duration_s: float,
    quiet: list[float],
) -> list[Case]:
    """Steady cases away from disruptions and actions, plus one case set per action."""
    busy = quiet + [a.t_s for a in applied]
    times = [
        t
        for t in _steps(STEP_S * 2, duration_s - HORIZON_S, STEP_S)
        if all(not (b - QUIET_BEFORE_S - HORIZON_S < t < b + QUIET_AFTER_S) for b in busy)
    ]
    cases = steady_cases(run, model, times, HORIZON_S)
    for a in applied:
        cases += action_cases(run, a, model, SETTLE_S, MEASURE_S)
    return cases


def _steps(start: float, stop: float, step: float) -> list[float]:
    count = int((stop - start) // step) + 1
    return [start + i * step for i in range(max(0, count))]


def calibrate_bulk(cases: list[Case], params: SimParams) -> SimParams:
    """Bulk's offered rate = its median measured throughput in the train split's steady cases."""
    measured = [c.measured_mbps for c in cases if c.app_class == "bulk" and c.kind == "steady"]
    if not measured:
        return params
    bulk = dataclasses.replace(
        params.apps["bulk"], offered_mbps=round(statistics.median(measured), 3)
    )
    return dataclasses.replace(params, apps={**params.apps, "bulk": bulk})


def main(argv: list[str] | None = None) -> int:
    """Validate, calibrate on train, report per split; 0 always (the report is the deliverable)."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--datasets", nargs="+", type=Path, default=[ROOT / "data" / "v1"])
    args = parser.parse_args(argv)

    campus_raw = yaml.safe_load((ROOT / "config" / "campus_v1.yaml").read_text())
    base = load_sim_params(yaml.safe_load((ROOT / "config" / "sim.yaml").read_text()))
    campus, radio = load_campus_aps(campus_raw), load_radio_params(campus_raw)
    now = datetime.now(UTC)
    work: list[tuple[RunTelemetry, list[Applied], float, list[float]]] = []
    for dataset in args.datasets:
        for run in load_runs(dataset):
            scenario = load_scenario(run.scenario_id)
            onset = disruption(scenario)
            applied = scripted_actions(scenario, now) + batch_actions(dataset, run.run_id)
            work.append((run, applied, scenario.duration_s, [onset.at_s] if onset else []))

    def all_cases(params: SimParams) -> list[Case]:
        model = TwinModel(campus, radio, params)
        return [
            c
            for run, applied, duration, quiet in work
            for c in cases_for(run, applied, model, duration, quiet)
        ]

    before = all_cases(base)
    calibrated = calibrate_bulk([c for c in before if c.split == "train"], base)
    after = all_cases(calibrated)
    report: dict[str, Any] = {
        "created": now.isoformat(timespec="seconds"),
        "git_commit": git_commit(),
        "datasets": [str(d.relative_to(ROOT)) for d in args.datasets],
        "bulk_offered_mbps": {
            "config": base.apps["bulk"].offered_mbps,
            "calibrated": calibrated.apps["bulk"].offered_mbps,
        },
        "before_calibration": {
            s: summary([c for c in before if c.split == s]) for s in ("train", "val", "test")
        },
        "after_calibration": {
            s: summary([c for c in after if c.split == s]) for s in ("train", "val", "test")
        },
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "validation.json").write_text(json.dumps(report, indent=1))
    bulk = report["bulk_offered_mbps"]
    print(
        f"TWIN_VALIDATION bulk offered: config {bulk['config']} -> calibrated {bulk['calibrated']}"
    )
    for stage in ("before_calibration", "after_calibration"):
        for split, table in report[stage].items():
            for key, row in table.items():
                if row["mape"] is not None:
                    score = f"MAPE {row['mape']:.1%} (n={row['n']})"
                    print(f"TWIN_VALIDATION {stage} {split} {key}: {score}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
