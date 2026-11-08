"""P5.6 evidence: what changed in the network around an anomaly alert, as a small JSON summary.

The explainer's model reads this summary, not raw telemetry (PROJECT_PLAN §5.3: the alert, a
metric window and recent actions). Per AP over the WINDOW_S before the alert: utilisation,
clients and channel *before* (older than RECENT_S) and *now* (the last RECENT_S), and whether it
still reports (any ap_stats in the last REPORTING_S), and its stations now (so a suggested steer
can name them). Plus the stations without an AP, the flows with the worst loss and latency, and
the newest audit-log entries.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Any, Protocol

from genai.tools.tools import MAX_WINDOW_S

WINDOW_S = 300  # the 5 minutes before the alert
RECENT_S = 60  # "now": the last minute before the alert
REPORTING_S = 30  # an AP with no ap_stats this long is not reporting (ap_stats come every ~1 s)
WORST_FLOWS = 5
RECENT_ACTIONS = 5


class EvidenceSource(Protocol):
    """What the evidence is read from: the API's reads plus the audit log (HttpBackend)."""

    def topology(self) -> dict[str, Any]: ...

    def metrics(self, entity: str, metric: str, window_s: int) -> list[dict[str, Any]]: ...

    def recent_actions(self, limit: int) -> list[dict[str, Any]]: ...


def gather(
    backend: EvidenceSource, alert: dict[str, Any], now: datetime
) -> dict[str, Any]:  # Any: JSON
    """The evidence for `alert`, explained at `now`: the metric window ends at the alert's `ts`
    (the backend's window ends at `now`, so it is asked to reach back far enough and the points
    after the alert are left out). Topology, stations and flows are as they are now. ValueError
    if the window reaches past what the backend keeps (every AP would look silent)."""
    at = datetime.fromisoformat(alert["ts"])
    window_s = WINDOW_S + max(0, math.ceil((now - at).total_seconds()))
    if window_s > MAX_WINDOW_S:
        raise ValueError(
            f"the alert is too old to explain: its {WINDOW_S} s window starts "
            f"{window_s} s ago, past the {MAX_WINDOW_S} s the metrics go back"
        )
    topology = backend.topology()
    stations = topology["stations"]  # the GET /topology shape (the twin state)
    aps = []
    for a in topology["aps"]:
        mine = [s["name"] for s in stations if s["ap"] == a["name"]]
        ap = _ap(backend, a["name"], a["up"], at, window_s)
        aps.append(ap | {"stations": _by_number(mine)})
    worst = sorted(topology["flows"], key=lambda f: (-f["loss_pct"], -f["latency_ms"]))
    flows = worst[:WORST_FLOWS]
    return {
        "alert": alert,
        "aps": aps,
        "unassociated_stations": _by_number(s["name"] for s in stations if s["ap"] is None),
        "worst_flows": [
            {k: f[k] for k in ("flow_id", "throughput_mbps", "latency_ms", "loss_pct")}
            for f in flows
        ],
        "recent_actions": backend.recent_actions(RECENT_ACTIONS),
    }


def _ap(
    backend: EvidenceSource, ap: str, up: bool, at: datetime, window_s: int
) -> dict[str, Any]:  # Any: JSON
    split = at - timedelta(seconds=RECENT_S)
    series = {
        m: _points(backend, ap, m, at, window_s) for m in ("channel_util", "n_clients", "channel")
    }

    def mean(metric: str, recent: bool) -> float | None:
        values = [v for t, v in series[metric] if (t >= split) == recent]
        return round(statistics.mean(values), 3) if values else None

    channels = [v for _, v in series["channel"]]
    last_report = max((t for points in series.values() for t, _ in points), default=None)
    return {
        "ap": ap,
        "up": up,
        "reporting": last_report is not None and last_report >= at - timedelta(seconds=REPORTING_S),
        "channel_before": int(channels[0]) if channels else None,
        "channel_now": int(channels[-1]) if channels else None,
        "util_before": mean("channel_util", recent=False),
        "util_now": mean("channel_util", recent=True),
        "clients_before": mean("n_clients", recent=False),
        "clients_now": mean("n_clients", recent=True),
    }


def _by_number(names: Iterable[str]) -> list[str]:
    """Station names in number order (sta2 before sta10)."""
    return sorted(names, key=lambda n: int("".join(c for c in n if c.isdigit()) or 0))


def _points(
    backend: EvidenceSource, ap: str, metric: str, at: datetime, window_s: int
) -> list[tuple[datetime, float]]:
    """The metric's points in the WINDOW_S up to `at`, oldest first: the backend is asked for
    `window_s` up to now, so the points after the alert are left out here."""
    start = at - timedelta(seconds=WINDOW_S)
    points = (
        (datetime.fromisoformat(p["ts"]), p["value"])
        for p in backend.metrics(ap, metric, window_s)
        if p["value"] is not None
    )
    return sorted((t, float(v)) for t, v in points if start <= t <= at)
