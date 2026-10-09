"""P4.5 / P6 time to recover (problem statement §5.1): seconds from congestion onset until the
affected AP's channel utilisation is back under 80% **and** video flows meet their latency
objective, both holding for `hold_s` (a short dip is not recovery).

The latency objective is p95 video latency <= 50 ms per second (decision P4.5-A: the problem
statement names an objective without a number; 50 ms is PROJECT_PLAN §7.4's video example).
A second without video samples meets it; a second without the AP's stats does not count.
The affected AP is the busiest one in the first `window_s` after onset.
"""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

Row = dict[str, Any]  # a dataset row: column -> value, with t_s (seconds into the run)
P95 = 0.95


@dataclass(frozen=True)
class RecoveryRule:
    """When an AP counts as recovered."""

    util_limit: float = 0.8  # problem statement §5.1
    video_latency_ms: float = 50.0  # decision P4.5-A
    hold_s: float = 15.0

    def __post_init__(self) -> None:
        for name in ("util_limit", "video_latency_ms"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be > 0")
        if self.hold_s < 0:
            raise ValueError("hold_s must be >= 0")


def affected_ap(ap_rows: Sequence[Row], onset_s: float, window_s: float = 30.0) -> str:
    """The AP with the highest mean utilisation in [onset, onset + window)."""
    utils: dict[str, list[float]] = defaultdict(list)
    for r in ap_rows:
        if onset_s <= r["t_s"] < onset_s + window_s:
            utils[r["ap"]].append(r["channel_util"])
    return max(utils, key=lambda ap: (statistics.mean(utils[ap]), ap))


def time_to_recover(
    ap_rows: Sequence[Row], kpi_rows: Sequence[Row], ap: str, onset_s: float, rule: RecoveryRule
) -> float | None:
    """Seconds from onset to recovery; None if the run ends first."""
    util: dict[int, list[float]] = defaultdict(list)
    for r in ap_rows:
        if r["ap"] == ap:
            util[int(r["t_s"])].append(r["channel_util"])
    video: dict[int, list[float]] = defaultdict(list)
    for r in kpi_rows:
        if r["app_class"] == "video":
            video[int(r["t_s"])].append(r["latency_ms"])
    if not util:
        return None

    def ok(second: int) -> bool:
        if second not in util or statistics.mean(util[second]) >= rule.util_limit:
            return False
        latencies = sorted(video.get(second, []))
        return (
            not latencies or latencies[math.ceil(P95 * len(latencies)) - 1] <= rule.video_latency_ms
        )

    hold, last, start = int(rule.hold_s), max(util), math.ceil(onset_s)
    for second in range(start, last - hold + 2):
        if all(ok(s) for s in range(second, second + hold)):
            return float(second - onset_s)
    return None
