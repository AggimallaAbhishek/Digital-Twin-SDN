"""P6.6 campaign analysis: the problem statement §5.1 KPIs of every run, and mean ± 95% CI per
mode and scenario (decision P6.6-A).

Per run, over the stress window (from the scenario's disruption to the run's end):

- **time to recover**: P4.5-A (experiments/analysis/time_to_recover.py); a run that never
  recovers is censored at the run end and counted apart;
- **throughput, loss**: mean over the *affected flows*: the flows of the stations on the AP the
  scenario's event names (AP down, forced channel) in the 30 s before it, else (flash crowd) on
  the busiest AP in the 30 s after the onset. They stay affected when steered away;
- **latency**: p95 of the affected video flows (all affected flows if none is video);
- **Jain**: Jain's index of the client counts of the APs that report (down APs do not), per
  5 s step, averaged over the window.
"""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from controller.executor.live_kpis import jain, window_kpis
from experiments.analysis.time_to_recover import RecoveryRule, affected_ap, time_to_recover

Row = dict[str, Any]  # a dataset row: column -> value, with t_s (seconds into the run)
KPI_TITLES = {  # the KPIs a run reports (RunKpis fields), in report order, with their titles
    "ttr_s": "Time to recover (s)",
    "throughput_mbps": "Throughput, affected flows (Mbit/s)",
    "latency_p95_ms": "p95 video latency (ms)",
    "loss_pct": "Loss, affected flows (%)",
    "jain": "Jain fairness (client load)",
}
AFFECTED_WINDOW_S = 30.0  # as affected_ap(): the stations on the affected AP right after onset
JAIN_STEP_S = 5.0
# two-sided 95% t quantiles t(0.975, df) for df = 1..9 (any statistics table); n = 3 seeds
T95 = (12.706, 4.303, 3.182, 2.776, 2.571, 2.447, 2.365, 2.306, 2.262)


@dataclass(frozen=True)
class RunKpis:
    """One run's KPIs over its stress window (None where the run had no sample)."""

    affected_ap: str
    ttr_s: float | None  # None: never recovered before the run ended
    censor_s: float  # the run end, counted from the onset
    throughput_mbps: float | None
    latency_p95_ms: float | None
    loss_pct: float | None
    jain: float | None


@dataclass(frozen=True)
class Summary:
    """Mean and the half-width of its 95% confidence interval (t distribution)."""

    mean: float | None
    ci95: float | None
    n: int


@dataclass(frozen=True)
class StressWindow:
    """From the scenario's disruption to the run's end; `event_ap` = the AP its event names."""

    onset_s: float
    end_s: float
    event_ap: str | None = None  # ap_down / force_channel; None for the flash crowd


def run_kpis(
    ap_rows: Sequence[Row], sta_rows: Sequence[Row], kpi_rows: Sequence[Row], window: StressWindow
) -> RunKpis:
    """The KPIs of one run over its stress window."""
    onset_s = window.onset_s
    ap = affected_ap(ap_rows, onset_s, AFFECTED_WINDOW_S)
    # the affected stations: those on the event's AP just before it (they lose service), else
    # those on the busiest AP just after the onset (the crowd)
    on, start = (window.event_ap, onset_s - AFFECTED_WINDOW_S) if window.event_ap else (ap, onset_s)
    stations = {
        r["sta"]
        for r in sta_rows
        if r["ap"] == on and start <= r["t_s"] < start + AFFECTED_WINDOW_S
    }
    stress = [r for r in kpi_rows if r["t_s"] >= onset_s]
    flows = {r["flow_id"] for r in stress if r["flow_id"].split("-", 1)[0] in stations}
    # the verifier's own KPI definitions (throughput and loss means, p95 video latency);
    # its Jain needs association rows per window, so Jain is computed over time below
    kpis = window_kpis(stress, [], [], flows)
    return RunKpis(
        affected_ap=ap,
        ttr_s=time_to_recover(ap_rows, kpi_rows, ap, onset_s, RecoveryRule()),
        censor_s=window.end_s - onset_s,
        throughput_mbps=kpis.throughput_mbps if kpis else None,
        latency_p95_ms=kpis.latency_ms if kpis else None,
        loss_pct=kpis.loss_pct if kpis else None,
        jain=_mean_jain([r for r in ap_rows if r["t_s"] >= onset_s]),
    )


def _mean_jain(ap_rows: Sequence[Row]) -> float | None:
    steps: dict[int, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for r in ap_rows:
        steps[int(r["t_s"] // JAIN_STEP_S)][r["ap"]].append(r["n_clients"])
    values = [jain([statistics.fmean(v) for v in per_ap.values()]) for per_ap in steps.values()]
    return statistics.fmean(values) if values else None


def summarise(values: Sequence[float]) -> Summary:
    """Mean ± t(0.975, n-1) · s / sqrt(n); no interval for fewer than 2 values."""
    n = len(values)
    if n == 0:
        return Summary(None, None, 0)
    if n == 1:
        return Summary(values[0], None, 1)
    if n - 1 > len(T95):
        raise ValueError(f"no t quantile for {n} values (at most {len(T95) + 1})")
    return Summary(
        statistics.fmean(values), T95[n - 2] * statistics.stdev(values) / math.sqrt(n), n
    )
