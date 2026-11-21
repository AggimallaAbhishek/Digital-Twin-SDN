"""What the IEEE paper (final_submission/paper/) is built from: the recorded evaluation, read once,
and the definitions its numbers (experiments/paper_build.py) and its figures
(experiments/paper_figures.py) share.

- `experiments/results/results.json` (`make results`): the KPI table, H1, fairness, H2 counts;
- the executor ledgers of the 27 campaign runs (`data/raw/eval<mode>-v1/<run>/actions.db`,
  opened read-only): what became of every action, and the twin's prediction time;
- the campaign's telemetry (`data/eval<mode>-v1/*.parquet`): per run, the APs' load and clients,
  the affected flows' KPIs and where the stations were;
- `models/{twin,anomaly,forecast,genai}/v1/*.json` and `experiments/results/intents*.json`;
- the configuration files and constants the method section quotes (config/*.yaml, the verifier).
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import combinations
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
import yaml

from common.schemas import KPIValues
from controller.executor.ledger import ActionRecord, read_records
from controller.executor.live_kpis import window_kpis
from experiments.analysis.campaign import affected_flows
from experiments.analysis.results import run_tables, stress_window
from experiments.batch import LOOP_MODES, load_scenario, run_ok
from twin.radio import RadioParams, capped_capacity_mbps, cochannel_load
from twin.sim.analytical import SimParams
from twin.verify.verifier import _better_pct

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = {  # scenario -> (macro word, title)
    "lecture_flash_crowd": ("Flash", "Lecture flash crowd"),
    "ap_failure": ("ApFail", "AP failure"),
    "cochannel_interference": ("Cochan", "Co-channel interference"),
}
MODE_WORDS = {"V1": "Vone", "V2": "Vtwo", "V3": "Vthree"}  # LaTeX names have no digits
MODE_LABELS = {"V1": "V1 plain SDN", "V2": "V2 no twin", "V3": "V3 full"}
KPIS = {  # kpi -> (macro word, decimals, heading)
    "ttr_s": ("Ttr", 0, "Recovery (s)"),
    "throughput_mbps": ("Thr", 2, "Thr. (Mbit/s)"),
    "latency_p95_ms": ("Lat", 0, "p95 lat. (ms)"),
    "loss_pct": ("Loss", 1, "Loss (\\%)"),
    "jain": ("Jain", 2, "Jain"),
}
KPI_FIELDS = ("throughput_mbps", "latency_ms", "loss_pct", "jain")  # common/schemas.py KPIValues
JUDGED_MODES = ("V2", "V3")  # the variants whose proposals the twin judges (V1 proposes none)
RESOLVED = ("kept", "rolled_back", "rollback_failed")  # applied, and the watch has decided
HARMFUL = ("rolled_back", "rollback_failed")  # the watch measured a regression
STATUS_WORDS = {  # ledger status -> macro word and table heading (also the figures' legend)
    "kept": ("Kept", "Kept"),
    "rolled_back": ("RolledBack", "Rolled back"),
    "rollback_failed": ("RollbackFailed", "Rollback failed"),
    "applied": ("Watched", "Still watched"),
    "rejected": ("Rejected", "Rejected, not applied"),
    "verified": ("Waiting", "Awaiting an operator"),
}
SERIES_COLUMNS = {  # the telemetry the figures draw, per table
    "ap_stats": ("run_id", "scenario_id", "seed", "t_s", "ap", "channel_util", "n_clients"),
    "sta_stats": ("run_id", "t_s", "sta", "ap", "x", "y"),
    "kpi": ("run_id", "t_s", "flow_id", "app_class", "throughput_mbps", "latency_ms", "loss_pct"),
}
Json = dict[str, Any]  # Any: JSON
Row = dict[str, Any]  # Any: a telemetry row, column -> value
Point = tuple[float, float]
Window = tuple[KPIValues | None, KPIValues | None]  # an action's flows' KPIs: before, watch
WINDOW_COLUMNS = (
    "run_id",
    "ts",
    "flow_id",
    "app_class",
    "throughput_mbps",
    "latency_ms",
    "loss_pct",
)


@dataclass(frozen=True)
class RunSeries:
    """One campaign run's telemetry, as the figures draw it (t_s: seconds into the run)."""

    run_id: str  # as the ledgers key the run
    scenario: str
    seed: int
    onset_s: float  # t_d: when the disruption starts to load the network
    end_s: float  # the run's end
    affected_ap: str  # the busiest AP just after the onset (Eq. (5)'s U(t) is its utilisation)
    ap_stats: Sequence[Row]  # every AP's stats rows: t_s, ap, channel_util, n_clients
    affected_kpis: Sequence[Row]  # the KPI rows of the affected flows, over the whole run
    start_xy: Mapping[str, Point]  # where each station was first seen
    onset_xy: Mapping[str, Point]  # ... and where it was last seen before the onset


@dataclass(frozen=True)
class Evidence:
    """Everything the paper's numbers and figures come from (see the module docstring)."""

    results: Json
    twin: Json
    anomaly: Json
    forecast: Json
    genai: Json
    intents: Json
    intents_local: Json
    intent_set: Sequence[Json]  # the 30 intents and what each should compile to
    intent_calls: Sequence[
        Json
    ]  # every LLM call of the two intent evaluations (one JSON line each)
    ledgers: Mapping[str, Mapping[str, Sequence[ActionRecord]]]  # mode -> passed run -> actions
    run_starts: Mapping[str, Mapping[str, datetime]]  # mode -> run -> when its t_s was 0
    config: Mapping[str, Json]  # config/<name>.yaml
    series: Mapping[str, Sequence[RunSeries]]  # mode -> its campaign runs, in run order; empty
    # when loaded without them (`make paper-check`: the generated text never reads them)
    watched: Mapping[str, Window]  # action id -> its flows' KPIs before it and over its watch
    # (`load_watched`); empty when loaded without the series

    def actions(self, mode: str) -> list[ActionRecord]:
        """Every action of the passed runs of one variant."""
        return [r for records in self.ledgers[mode].values() for r in records]

    def runs(self, mode: str, scenario: str) -> list[RunSeries]:
        """The telemetry of one variant's runs of one scenario, in run order."""
        return [s for s in self.series[mode] if s.scenario == scenario]


def _load(path: Path) -> Json:
    data: Json = json.loads(path.read_text())
    return data


def passed_runs(raw: Path) -> list[str]:
    """The run folders of a raw campaign (data/raw/eval<mode>-v1) that gave usable data: the
    same rule as the results tables (experiments/batch.py run_ok)."""
    batch = _load(raw / "batch.json")
    return [r["run_id"] for r in batch["runs"] if run_ok(r)]


def run_starts(dataset: Path) -> dict[str, datetime]:
    """When each run of a dataset started (its t_s = 0), from the telemetry timestamps: the
    ledgers date an action by the clock, the scenarios by seconds into the run."""
    table = pq.read_table(dataset / "kpi.parquet", columns=["run_id", "ts", "t_s"])
    first = table.group_by("run_id").aggregate([("ts", "min"), ("t_s", "min")])
    return {
        row["run_id"]: row["ts_min"] - timedelta(seconds=row["t_s_min"])
        for row in first.to_pylist()
    }


def load_series(dataset: Path) -> list[RunSeries]:
    """Every evaluation run of a campaign dataset, with its affected AP and flows defined as in
    the results tables (experiments/analysis/campaign.py)."""
    runs = []
    windows = {s: stress_window(load_scenario(s)) for s in SCENARIOS}
    for run_id, tables in sorted(run_tables(dataset, SERIES_COLUMNS).items()):
        aps, stations, kpis = tables["ap_stats"], tables["sta_stats"], tables["kpi"]
        window = windows[aps[0]["scenario_id"]]
        ap, flows = affected_flows(aps, stations, kpis, window)
        moves = sorted((r for r in stations if r["x"] is not None), key=lambda r: r["t_s"])
        start: dict[str, Point] = {}
        for r in moves:
            start.setdefault(r["sta"], (r["x"], r["y"]))
        onset = {r["sta"]: (r["x"], r["y"]) for r in moves if r["t_s"] < window.onset_s}
        runs.append(
            RunSeries(
                run_id=run_id,
                scenario=aps[0]["scenario_id"],
                seed=aps[0]["seed"],
                onset_s=window.onset_s,
                end_s=window.end_s,
                affected_ap=ap,
                ap_stats=aps,
                affected_kpis=[r for r in kpis if r["flow_id"] in flows],
                start_xy=start,
                onset_xy=onset,
            )
        )
    return runs


def load_evidence(root: Path = ROOT, *, series: bool = True) -> Evidence:
    """Read the recorded evaluation under `root` (a missing file is an error: say which); the
    figures' per-run telemetry only with `series` (most of the loading time)."""
    results = root / "experiments" / "results"
    models = root / "models"
    ledgers = {}
    for mode in LOOP_MODES:
        raw = root / "data" / "raw" / f"eval{mode.lower()}-v1"
        ledgers[mode] = {
            run_id: read_records(raw / run_id / "actions.db")
            for run_id in passed_runs(raw)
            if (raw / run_id / "actions.db").exists()
        }
    table = _load(results / "results.json")
    config = {
        name: yaml.safe_load((root / "config" / f"{name}.yaml").read_text())
        for name in ("sim", "optimizer", "loop", "executor", "campus_v1", "anomaly")
    }
    starts = {
        mode: run_starts(root / table["datasets"][mode]) if ledgers[mode] else {}
        for mode in LOOP_MODES
    }
    return Evidence(
        results=table,
        run_starts=starts,
        twin=_load(models / "twin" / "v1" / "validation.json"),
        anomaly=_load(models / "anomaly" / "v1" / "metrics.json"),
        forecast=_load(models / "forecast" / "v1" / "metrics.json"),
        genai=_load(models / "genai" / "v1" / "live.json"),
        intents=_load(results / "intents.json"),
        intents_local=_load(results / "intents_local.json"),
        intent_set=[
            json.loads(line)
            for line in (root / "genai" / "eval" / "intents.jsonl").read_text().splitlines()
            if line.strip()
        ],
        intent_calls=[
            json.loads(line)
            for name in ("intent_calls.jsonl", "intent_calls_local.jsonl")
            for line in (results / name).read_text().splitlines()
            if line.strip()
        ],
        ledgers=ledgers,
        config=config,
        series={
            mode: load_series(root / path) if series else []
            for mode, path in table["datasets"].items()
        },
        watched={
            action_id: windows
            for mode in JUDGED_MODES
            if series and ledgers[mode]
            for action_id, windows in load_watched(
                root / table["datasets"][mode], ledgers[mode], config["executor"]
            ).items()
        },
    )


def load_watched(
    dataset: Path, ledger: Mapping[str, Sequence[ActionRecord]], executor: Json
) -> dict[str, Window]:
    """For every resolved action of a campaign that the twin judged over a scope: the KPIs of
    the flows its verdict compared in the `watch_s` before it and over its watch (from
    `settle_s` on), recomputed from the recorded telemetry with the executor's own window
    function. The executor's ledger keeps only the network-wide KPIs before an action, so this
    is the one before-and-after comparison over the same flows."""
    watch = timedelta(seconds=executor["watch_s"])
    settle = timedelta(seconds=executor["settle_s"])
    table = pq.read_table(dataset / "kpi.parquet", columns=list(WINDOW_COLUMNS))
    by_run: dict[str, list[Row]] = defaultdict(list)
    for row in table.to_pylist():
        by_run[row["run_id"]].append(row)
    out = {}
    for run_id, records in ledger.items():
        rows = by_run.get(run_id, [])
        for r in records:
            if r.status not in RESOLVED or r.applied_at is None or not r.scope:
                continue
            at = r.applied_at
            out[r.action.action_id] = (
                _window(rows, at - watch, at, r.scope),
                _window(rows, at + settle, at + watch, r.scope),
            )
    return out


def _window(
    rows: Sequence[Row], start: datetime, end: datetime, scope: Sequence[str]
) -> KPIValues | None:
    """The KPIs of `scope`'s flows over [start, end), as the executor computes a window."""
    return window_kpis([r for r in rows if start <= r["ts"] < end], [], [], scope)


def kpi_cells(ev: Evidence) -> dict[tuple[str, str, str], Json]:
    """The results table by (variant, scenario, KPI)."""
    return {(r["mode"], r["scenario"], r["kpi"]): r for r in ev.results["table"]}


def kpi_range(ev: Evidence, mode: str, scenario: str, kpi: str) -> tuple[float, float]:
    """The smallest and the largest value of a KPI over the runs of one cell; a run that never
    recovered counts at its run end."""
    values = [
        run["censor_s"] if kpi == "ttr_s" and run["ttr_s"] is None else run[kpi]
        for run in ev.results["runs"][f"{mode}/{scenario}"]
    ]
    known = [v for v in values if v is not None]
    if not known:
        raise ValueError(f"no run of {mode}/{scenario} has a {kpi} value")
    return min(known), max(known)


def is_compound(expected: Json) -> bool:
    """An intent with a second objective, a hard constraint or two traffic classes."""
    classes = expected["scope"]["app_class"] or []
    return len(expected["objectives"]) > 1 or bool(expected.get("constraints")) or len(classes) > 1


def intent_kinds(ev: Evidence) -> dict[str, set[str]]:
    """The ids of the test intents by kind: single-clause and compound (`is_compound`)."""
    compound = {i["id"] for i in ev.intent_set if is_compound(i["expected"])}
    return {"single-clause": {i["id"] for i in ev.intent_set} - compound, "compound": compound}


def correct_by_kind(result: Json, kinds: Mapping[str, set[str]]) -> dict[str, tuple[int, int]]:
    """An intent evaluation's (intents translated correctly, intents) per kind of intent."""
    missed = set(result["misses"])
    return {kind: (len(ids - missed), len(ids)) for kind, ids in kinds.items()}


def resolved_actions(ev: Evidence) -> list[ActionRecord]:
    """The resolved actions of every variant (applied, and the watch has decided): V2's and V3's,
    as V1 proposes nothing."""
    return [r for m in LOOP_MODES for r in ev.actions(m) if r.status in RESOLVED]


def tainted_actions(ev: Evidence) -> set[str]:
    """The ids of the resolved actions of V2 and V3 whose verdict the scenario's scheduled
    disruption taints (the watch cannot tell the fault from the action's effect). The executor
    compares the watch's KPIs with those of the `watch_s` before the action, so the disruption
    taints the verdict if it falls within `watch_s` of the action, before or after. A run id
    starts with its scenario."""
    watch = timedelta(seconds=ev.config["executor"]["watch_s"])
    onsets = {s: timedelta(seconds=stress_window(load_scenario(s)).onset_s) for s in SCENARIOS}
    out = set()
    for mode in JUDGED_MODES:
        for run_id, records in ev.ledgers[mode].items():
            start, onset = ev.run_starts[mode][run_id], onsets[run_id.rsplit("-", 2)[0]]
            out |= {
                r.action.action_id
                for r in records
                if r.status in RESOLVED
                and r.applied_at is not None
                and abs(r.applied_at - start - onset) < watch
            }
    return out


def prediction_times(ev: Evidence) -> list[float]:
    """How long the twin took for each verdict of the campaign (ms)."""
    return [r.verdict.sim_time_ms for m in LOOP_MODES for r in ev.actions(m)]


def cochannel_pairs(campus: Json) -> list[tuple[str, str, float]]:
    """The APs that share a channel at the start of a run, and their distance (m)."""
    return [
        (a["name"], b["name"], math.dist(a["position"], b["position"]))
        for a, b in combinations(campus["aps"], 2)
        if a["channel"] == b["channel"]
    ]


def capacity_mbps(neighbour_distances_m: Sequence[float], params: RadioParams) -> float:
    """An AP's capacity (Eq. (1)) with same-channel APs at these distances; the nominal
    capacity when none interferes."""
    capped = capped_capacity_mbps(cochannel_load(neighbour_distances_m, params), params)
    return params.ap_capacity_mbps if capped is None else capped


def latency_cap_ms(params: SimParams) -> float:
    """The most the queue model (Eq. (3)) can predict: the base delay plus the service time of
    the K packets the queue holds (config/sim.yaml)."""
    return params.base_latency_ms + params.service_ms * params.queue_slots


def improvements(record: ActionRecord) -> list[float]:
    """The signed improvement of each KPI the twin predicted for the action, in percent."""
    before, after = record.verdict.baseline, record.verdict.predicted
    return [_better_pct(k, getattr(before, k), getattr(after, k)) for k in KPI_FIELDS]


def live_errors(records: Sequence[ActionRecord], kpi: str) -> tuple[list[float], list[float]]:
    """The relative error (%) of one KPI against what the watch measured, per action: of the
    twin's prediction, and of its no-action baseline ("nothing changes"). A measurement of 0
    has no relative error and is left out."""
    twin, unchanged = [], []
    for r in records:
        live = getattr(r.measured, kpi) if r.measured is not None else 0.0
        if live:
            twin.append(abs(getattr(r.verdict.predicted, kpi) - live) / abs(live) * 100)
            unchanged.append(abs(getattr(r.verdict.baseline, kpi) - live) / abs(live) * 100)
    return twin, unchanged
