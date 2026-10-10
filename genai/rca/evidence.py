"""P5.6 evidence: what changed in the network around an anomaly alert, as a small JSON summary.

The explainer's model reads this summary, not raw telemetry (PROJECT_PLAN §5.3: the alert, a
metric window and recent actions). Per AP over the WINDOW_S before the alert: utilisation,
clients and channel *before* (older than RECENT_S) and *now* (the last RECENT_S), and whether it
still reports (any ap_stats in the last REPORTING_S), and its stations now (so a suggested steer
can name them). Plus the stations without an AP, the flows with the worst loss and latency, and
the newest audit-log entries.
"""

from __future__ import annotations

import statistics
from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Any

from genai.tools.backend import Backend

WINDOW_S = 300  # the 5 minutes before the alert
RECENT_S = 60  # "now": the last minute before the alert
REPORTING_S = 30  # an AP with no ap_stats this long is not reporting (ap_stats come every ~1 s)
WORST_FLOWS = 5
RECENT_ACTIONS = 5


def gather(backend: Backend, alert: dict[str, Any]) -> dict[str, Any]:  # Any: JSON
    """The evidence for `alert` (its `ts` is the time the window ends at)."""
    at = datetime.fromisoformat(alert["ts"])
    topology = backend.topology()
    stations = topology.get("stations", [])
    aps = []
    for a in topology["aps"]:
        name = str(a.get("name", a.get("ap")))
        mine = [s["name"] for s in stations if s.get("ap") == name]
        aps.append(_ap(backend, name, bool(a.get("up", True)), at) | {"stations": _by_number(mine)})
    flows = sorted(topology.get("flows", []), key=lambda f: (-f["loss_pct"], -f["latency_ms"]))[
        :WORST_FLOWS
    ]
    return {
        "alert": alert,
        "aps": aps,
        "unassociated_stations": _by_number(s["name"] for s in stations if s.get("ap") is None),
        "worst_flows": [
            {k: f[k] for k in ("flow_id", "throughput_mbps", "latency_ms", "loss_pct")}
            for f in flows
        ],
        "recent_actions": backend.recent_actions(RECENT_ACTIONS),
    }


def _ap(backend: Backend, ap: str, up: bool, at: datetime) -> dict[str, Any]:  # Any: JSON
    split = at - timedelta(seconds=RECENT_S)
    series = {m: _points(backend, ap, m) for m in ("channel_util", "n_clients", "channel")}

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


def _points(backend: Backend, ap: str, metric: str) -> list[tuple[datetime, float]]:
    return sorted(
        (datetime.fromisoformat(p["ts"]), float(p["value"]))
        for p in backend.metrics(ap, metric, WINDOW_S)
        if p["value"] is not None
    )
