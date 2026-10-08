"""P4.2 window features for the anomaly detector: one vector per 30 s of the whole network.

Telemetry rows of one run (from the P2.3 dataset) are put in `step_s` bins; a window is
`window_s / step_s` consecutive bins, sliding by one bin. Per AP (in the given order):

    util_mean, util_max   utilisation of the AP's capacity over the window's bins (0 if silent)
    clients_mean          associated clients per bin (0 if silent)
    clients_delta         clients in the last bin minus the first (a crowd arriving / leaving)
    silent                share of bins with no ap_stats: a down AP stops reporting

Network: `unassociated` stations per bin, `loss_mean` of the flows' KPI records, and their
`latency_p95` (nearest rank). A window is `stress` if it ends at or after the run's onset
(experiments/dataset.py disruption; None for a normal run). Pure Python.
"""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

PER_AP = ("util_mean", "util_max", "clients_mean", "clients_delta", "silent")
NETWORK = ("unassociated", "loss_mean", "latency_p95")
P95 = 0.95
Row = dict[str, Any]  # a dataset row: column -> value (str, float, None)


@dataclass(frozen=True)
class RunRows:
    """One run's telemetry rows (t_s = seconds since the scenario started)."""

    run_id: str
    scenario_id: str
    split: str
    onset_s: float | None
    ap_rows: list[Row]
    sta_rows: list[Row]
    kpi_rows: list[Row]


@dataclass(frozen=True)
class Window:
    """Feature vector of one window (order: feature_names) and its label."""

    run_id: str
    scenario_id: str
    split: str
    t_end_s: float
    features: list[float]
    stress: bool


def feature_names(aps: Sequence[str]) -> list[str]:
    """Names of the window features, in vector order."""
    return [f"{ap}.{f}" for ap in aps for f in PER_AP] + [f"net.{f}" for f in NETWORK]


def windows(run: RunRows, aps: Sequence[str], step_s: float, window_s: float) -> list[Window]:
    """Sliding windows over a run; none if it is shorter than one window."""
    bins = _bin_rows(run, step_s)
    n_bins = 1 + max((b for rows in bins.values() for b in rows), default=-1)
    width = round(window_s / step_s)
    out = []
    for end in range(width - 1, n_bins):
        span = range(end - width + 1, end + 1)
        t_end = (end + 1) * step_s
        features = [x for ap in aps for x in _ap_features(bins[f"ap:{ap}"], span)]
        features += _network_features(bins["sta"], bins["kpi"], span)
        stress = run.onset_s is not None and t_end >= run.onset_s
        out.append(Window(run.run_id, run.scenario_id, run.split, t_end, features, stress))
    return out


def _bin_rows(run: RunRows, step_s: float) -> dict[str, dict[int, list[Row]]]:
    """Rows by series ("ap:<name>", "sta", "kpi"), then by time bin."""
    bins: dict[str, dict[int, list[Row]]] = defaultdict(lambda: defaultdict(list))
    keyed = [(f"ap:{r['ap']}", r) for r in run.ap_rows]
    keyed += [("sta", r) for r in run.sta_rows] + [("kpi", r) for r in run.kpi_rows]
    for key, row in keyed:
        bins[key][int(row["t_s"] // step_s)].append(row)
    return bins


def _ap_features(rows: dict[int, list[Row]], span: range) -> list[float]:
    util = [
        statistics.mean(r["channel_util"] for r in rows[b]) if rows.get(b) else 0.0 for b in span
    ]
    clients = [
        statistics.mean(r["n_clients"] for r in rows[b]) if rows.get(b) else 0.0 for b in span
    ]
    silent = sum(1 for b in span if not rows.get(b)) / len(span)
    return [
        statistics.mean(util),
        max(util),
        statistics.mean(clients),
        clients[-1] - clients[0],
        silent,
    ]


def _network_features(
    sta: dict[int, list[Row]], kpi: dict[int, list[Row]], span: range
) -> list[float]:
    unassociated = []
    for b in span:
        latest: dict[str, Row] = {}
        for row in sorted(sta.get(b, []), key=lambda r: r["t_s"]):
            latest[row["sta"]] = row
        unassociated.append(sum(1 for r in latest.values() if r["ap"] is None))
    flows = [r for b in span for r in kpi.get(b, [])]
    loss = statistics.mean(r["loss_pct"] for r in flows) if flows else 0.0
    latencies = sorted(r["latency_ms"] for r in flows)
    p95 = latencies[math.ceil(P95 * len(latencies)) - 1] if latencies else 0.0
    return [statistics.mean(unassociated), loss, p95]
