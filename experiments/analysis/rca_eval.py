"""P5.6 eval on replayed runs: the first anomaly alert after the fault, explained by the LLM.

    uv run python -m experiments.analysis.rca_eval     # writes models/genai/v1/rca_replay.json
    uv run python -m experiments.analysis.rca_eval --config <llm.yaml with model: qwen2.5:3b> \
        --out models/genai/v1/rca_replay_local.json                       # offline model

Each recorded data/v1 run with a known fault is replayed through the *real* pipeline, with only
the telemetry source swapped: the live alert monitor (api/alerts.py) ticks every 5 s over the
run's rows until its first alert after the fault's onset; then the root-cause explainer
(genai/rca/) reads its evidence through the HTTP backend from a real API app (api/app.py) whose
twin state and metrics come from the same rows, as of the alert. Its suggested fixes are
verified by the real twin. A diagnosis is correct when the top likely cause has the fault's
category and names the AP at fault (EXPECTED).
"""

from __future__ import annotations

import argparse
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from api.alerts import Rows, build_alert_monitor
from api.app import Services, TwinSimulator, create_app
from api.metrics import measurement_for, series
from api.wiring import ROOT, load_yaml
from common.schemas import Action, KPIValues
from controller.executor.executor import Executor, load_executor_config
from controller.executor.ledger import Ledger
from experiments.inprocess import inprocess_backend
from genai.llm.client import LLM_CONFIG, LLMClient
from genai.rca.explainer import explain
from genai.tools.http_backend import HttpBackend
from genai.tools.tools import ToolLayer
from twin.radio import load_radio_params
from twin.sim.analytical import load_sim_params
from twin.state.builder import Snapshot, build_state, load_campus_aps
from twin.state.model import TwinState
from twin.state.sync import load_sync_config
from twin.verify.verifier import VerifyContext, load_verify_config

log = logging.getLogger("experiments.rca_eval")
DATASET = ROOT / "data" / "v1"
OUT = ROOT / "models" / "genai" / "v1" / "rca_replay.json"
# scenario -> (category, AP) of the right diagnosis (experiments/scenarios/*.yaml)
EXPECTED = {
    "ap_failure": ("ap_down", "ap2"),
    "cochannel_interference": ("cochannel_interference", "ap3"),
    "lecture_flash_crowd": ("congestion", "ap1"),
}
TICK_S = 5


@dataclass(frozen=True)
class Replay:
    """One recorded run's telemetry rows (real timestamps); `start` = its scenario t_s 0."""

    run_id: str
    scenario_id: str
    onset_s: float | None
    start: datetime
    ap: Rows
    sta: Rows
    kpi: Rows

    def rows(self, start: datetime, end: datetime) -> tuple[Rows, Rows, Rows]:
        """ap, sta and kpi rows in [start, end), like the live Influx query."""

        def cut(rows: Rows) -> Rows:
            return [r for r in rows if start <= r["ts"] < end]

        return cut(self.ap), cut(self.sta), cut(self.kpi)


def load_replay(dataset: Path, run_id: str) -> Replay:
    """A data/v1 run; onset = its first stress-labelled ap_stats row (decision P2.3-C)."""
    tables = {
        name: pq.read_table(dataset / f"{name}.parquet", filters=[("run_id", "=", run_id)])
        for name in ("ap_stats", "sta_stats", "kpi")
    }
    ap, sta, kpi = (tables[n].to_pylist() for n in ("ap_stats", "sta_stats", "kpi"))
    first = min(ap, key=lambda r: r["t_s"])
    stress = [r["t_s"] for r in ap if r["phase"] == "stress"]
    start = first["ts"] - timedelta(seconds=first["t_s"])
    onset = min(stress) if stress else None
    return Replay(run_id, first["scenario_id"], onset, start, ap, sta, kpi)


class _NoActuator:
    """The replay records verdicts only; nothing is ever applied."""

    def apply(self, action: Action, state: TwinState) -> dict[str, Any]:
        raise RuntimeError("the replay eval never applies actions")

    def revert(self, action: Action, previous: dict[str, Any]) -> None:
        raise RuntimeError("the replay eval never applies actions")


class _NoKpis:
    def window(self, start: datetime, end: datetime) -> KPIValues | None:
        return None


def backend_for(replay: Replay, clock: Callable[[], datetime], ledger: Path) -> HttpBackend:
    """The HTTP backend over a real API app serving `replay` as of `clock()`."""
    campus_raw = load_yaml("campus_v1.yaml")
    campus = load_campus_aps(campus_raw)
    sync = load_sync_config(load_yaml("twin.yaml"))
    context = VerifyContext(
        campus,
        load_radio_params(campus_raw),
        load_sim_params(load_yaml("sim.yaml")),
        load_verify_config(load_yaml("verify.yaml")),
    )

    def state() -> TwinState:
        now = clock()
        rows = replay.rows(now - timedelta(seconds=sync.sync_window_s), now)
        return build_state(Snapshot(*rows), campus, now, sync.ap_stale_s)

    def metrics(entity: str, metric: str, window_s: int) -> list[dict[str, Any]]:
        measurement, tag = measurement_for(entity)
        now = clock()
        ap, sta, kpi = replay.rows(now - timedelta(seconds=window_s), now)
        rows = {"ap_stats": ap, "sta_stats": sta, "kpi": kpi}[measurement]
        return series(rows, tag, entity, metric)

    executor = Executor(
        Ledger(ledger),
        _NoActuator(),
        _NoKpis(),
        load_executor_config(load_yaml("executor.yaml")),
        clock=clock,
    )
    services = Services(
        state=state,
        simulator=TwinSimulator(state, context),
        sim_enabled=True,  # evaluation: the twin verifies the suggestions whatever the B-5 flag
        executor=executor,
        operator_token=None,  # nothing can be approved or applied
        intents=None,
        metrics=metrics,
        clock=clock,
    )
    return inprocess_backend(create_app(services))


def score(scenario: str, report: dict[str, Any]) -> bool:
    """True when the top likely cause has the fault's category and names its AP."""
    top = report["likely_causes"][0]
    return (top["category"], top.get("entity")) == EXPECTED[scenario]


def evaluate(replay: Replay, client: LLMClient, ledger: Path) -> dict[str, Any]:
    """The first alert after the onset of `replay`, and the explainer's report on it."""
    clock = [replay.start]
    monitor = build_alert_monitor(replay.rows, lambda: clock[0])
    if monitor is None or replay.onset_s is None:
        raise ValueError(f"{replay.run_id}: no detector or no fault to explain")
    end = max(r["ts"] for r in replay.ap)
    early, alert = 0, None
    clock[0] = replay.start + timedelta(seconds=30)
    while alert is None and clock[0] <= end:
        found = monitor.tick()
        after_onset = clock[0] - replay.start > timedelta(seconds=replay.onset_s)
        if found is not None and not after_onset:
            early += 1  # a false alert before the fault: noted, not explained
        elif found is not None:
            alert = found
        clock[0] += timedelta(seconds=TICK_S)
    if alert is None:
        return {"run_id": replay.run_id, "alert": None, "correct": False, "early_alerts": early}
    clock[0] = datetime.fromisoformat(alert["ts"])
    backend = backend_for(replay, lambda: clock[0], ledger)
    report = explain(client, backend, ToolLayer(backend), alert, clock=lambda: clock[0])
    delay = (clock[0] - replay.start).total_seconds() - replay.onset_s
    return {
        "run_id": replay.run_id,
        "scenario": replay.scenario_id,
        "alert_after_onset_s": round(delay, 1),
        "early_alerts": early,
        "correct": score(replay.scenario_id, report),
        "report": report,
    }


def main(argv: list[str] | None = None) -> int:
    """Replay every run of the EXPECTED scenarios; write the reports and the accuracy."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dataset", type=Path, default=DATASET)
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--config", type=Path, default=LLM_CONFIG, help="LLM config (models)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # one line per in-process API call
    runs = sorted(
        {
            r["run_id"]
            for r in pq.read_table(
                args.dataset / "ap_stats.parquet", columns=["run_id"]
            ).to_pylist()
        }
    )
    client = LLMClient.from_config(args.config)
    results = []
    args.out.parent.mkdir(parents=True, exist_ok=True)
    for run_id in runs:
        replay = load_replay(args.dataset, run_id)
        if replay.scenario_id not in EXPECTED:
            continue
        ledger = args.out.parent / f"rca_{run_id}.db"
        ledger.unlink(missing_ok=True)
        result = evaluate(replay, client, ledger)
        top = result.get("report", {}).get("likely_causes", [{}])[0]
        log.info("%s: %s %s", run_id, "OK" if result["correct"] else "WRONG", top)
        results.append(result)
    correct = sum(r["correct"] for r in results)
    summary = {"correct": correct, "runs": len(results), "model": client.config.model}
    args.out.write_text(json.dumps({"summary": summary, "runs": results}, indent=1, default=str))
    print(f"RCA replay: {correct}/{len(results)} correct -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
