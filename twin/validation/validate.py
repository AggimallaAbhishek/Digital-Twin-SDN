"""P3.5 twin validation: the twin's per-flow throughput prediction against what was measured.

A **case** is one flow at one moment. The twin state is rebuilt from the run's last
`lookback_s` of telemetry before time t (twin/state/builder.py, as the live sync does), then:

- **steady**: predict with no action, compare with the flow's median throughput over
  [t, t + horizon_s);
- **action**: apply the action in the twin (twin/sim/apply.py), predict, and compare with the
  median over [t + settle_s, t + settle_s + measure_s), once the network has reacted.

Only video and bulk flows are scored (decision P3.5-A: a web probe reports one fetch's rate, so
it is reported apart). MAPE = mean |predicted - measured| / measured over the cases whose
measured median is at least MIN_MEASURED_MBPS (a dead flow has no meaningful ratio).
"""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from common.schemas import Action
from twin.radio import RadioParams
from twin.sim.analytical import SimParams, SimResult, simulate
from twin.sim.apply import apply
from twin.state.builder import CampusAPs, Snapshot, build_state
from twin.state.model import TwinState

SCORED = ("video", "bulk")
MIN_MEASURED_MBPS = 0.05
LOOKBACK_S = 10.0  # = config/twin.yaml sync_window_s
STALE_S = 5.0  # = config/twin.yaml ap_stale_s
Row = dict[str, Any]  # a telemetry row: column -> value, with `ts` and `t_s` (seconds into the run)


@dataclass(frozen=True)
class RunTelemetry:
    """One run's telemetry rows (data/v1 or a validation batch)."""

    run_id: str
    scenario_id: str
    split: str
    ap_rows: Sequence[Row]
    sta_rows: Sequence[Row]
    kpi_rows: Sequence[Row]


@dataclass(frozen=True)
class TwinModel:
    """The twin's fixed parts: campus layout, radio model and simulator parameters."""

    campus: CampusAPs
    radio: RadioParams
    params: SimParams


@dataclass(frozen=True)
class Applied:
    """An action applied at `t_s` seconds into the run."""

    t_s: float
    action: Action


@dataclass(frozen=True)
class Case:
    """One flow's predicted and measured throughput at one moment."""

    run_id: str
    scenario_id: str
    split: str
    kind: str  # "steady" or the action type
    t_s: float
    flow_id: str
    app_class: str
    predicted_mbps: float
    measured_mbps: float


def state_at(run: RunTelemetry, t_s: float, campus: CampusAPs) -> TwinState | None:
    """The twin state from the `LOOKBACK_S` of telemetry before `t_s`; None without telemetry."""
    snapshot = Snapshot(
        *(
            _window(rows, t_s - LOOKBACK_S, t_s)
            for rows in (run.ap_rows, run.sta_rows, run.kpi_rows)
        )
    )
    every = [*snapshot.ap_rows, *snapshot.sta_rows, *snapshot.kpi_rows]
    if not snapshot.kpi_rows:
        return None
    return build_state(snapshot, campus, max(r["ts"] for r in every), STALE_S)


def steady_cases(
    run: RunTelemetry, model: TwinModel, times: Sequence[float], horizon_s: float
) -> list[Case]:
    """Cases at each of `times` with no action."""
    cases = []
    for t in times:
        state = state_at(run, t, model.campus)
        if state is not None:
            predicted = simulate(state, model.radio, model.params)
            measured = _medians(run, t, t + horizon_s)
            cases += _cases(run, ("steady", t), state, predicted, measured)
    return cases


def action_cases(
    run: RunTelemetry, applied: Applied, model: TwinModel, settle_s: float, measure_s: float
) -> list[Case]:
    """Cases for an action applied in the run."""
    t = applied.t_s
    state = state_at(run, t, model.campus)
    if state is None:
        return []
    predicted = simulate(apply(state, applied.action), model.radio, model.params)
    measured = _medians(run, t + settle_s, t + settle_s + measure_s)
    return _cases(run, (applied.action.type, t), state, predicted, measured)


def mape(cases: Sequence[Case]) -> float | None:
    """Mean absolute percentage error as a fraction; None if no case can be scored."""
    errors = [
        abs(c.predicted_mbps - c.measured_mbps) / c.measured_mbps
        for c in cases
        if c.measured_mbps >= MIN_MEASURED_MBPS
    ]
    return math.fsum(errors) / len(errors) if errors else None


def summary(cases: Sequence[Case]) -> dict[str, dict[str, Any]]:  # Any: mape float | None, n int
    """MAPE and case count overall and per kind/app class."""
    groups: dict[str, list[Case]] = defaultdict(list)
    for c in cases:
        groups[f"{c.kind}/{c.app_class}"].append(c)
    table = {"all": _stats(cases)}
    table |= {key: _stats(group) for key, group in sorted(groups.items())}
    return table


def _stats(cases: Sequence[Case]) -> dict[str, Any]:  # Any: mape float | None, n int
    return {"mape": mape(cases), "n": len(cases)}


def _window(rows: Sequence[Row], start: float, end: float) -> list[Row]:
    return [r for r in rows if start <= r["t_s"] < end]


def _medians(run: RunTelemetry, start: float, end: float) -> dict[str, float]:
    by_flow: dict[str, list[float]] = defaultdict(list)
    for r in _window(run.kpi_rows, start, end):
        by_flow[r["flow_id"]].append(r["throughput_mbps"])
    return {f: statistics.median(v) for f, v in by_flow.items()}


def _cases(
    run: RunTelemetry,
    when: tuple[str, float],  # (kind, t_s)
    state: TwinState,
    predicted: SimResult,
    measured: dict[str, float],
) -> list[Case]:
    kind, t_s = when
    return [
        Case(
            run.run_id,
            run.scenario_id,
            run.split,
            kind,
            t_s,
            fid,
            flow.app_class,
            predicted.flows[fid].throughput_mbps,
            measured[fid],
        )
        for fid, flow in sorted(state.flows.items())
        if flow.app_class in SCORED and fid in measured
    ]
