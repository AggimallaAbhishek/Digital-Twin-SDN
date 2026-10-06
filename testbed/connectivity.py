"""Connectivity verdict for emulated Wi-Fi: every pair reachable + single-ping loss within budget.

With wmediumd interference mode the radio drops packets according to SNR/interference, like real
Wi-Fi, so a one-shot ping matrix sees ~1% transient loss (docs/setup.md, Known problems #8).
The check therefore separates *reachability* (retry failed pairs) from *loss rate* (first-try
single pings vs a budget). Pure Python, unit-tested on the Mac; Python 3.8-compatible.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Mapping, Tuple

Pair = Tuple[str, str]  # runtime alias: typing.Tuple, because tuple[...] fails on Python 3.8

_RECEIVED = re.compile(r"(\d+) received")


def ping_received(output: str) -> bool:
    """Return True if a `ping` run's summary reports at least one reply."""
    match = _RECEIVED.search(output)
    if match is None:
        return False
    return int(match.group(1)) > 0


@dataclass(frozen=True)
class ConnectivityReport:
    """Result of a ping-matrix check."""

    pairs: int
    loss_pct: float
    max_loss_pct: float
    first_try_failures: list[Pair] = field(default_factory=list)
    unreachable: list[Pair] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        """True if every pair is reachable and first-try loss is within budget."""
        return not self.unreachable and self.loss_pct <= self.max_loss_pct

    def summary(self, tag: str, assoc_ok: int, assoc_total: int) -> str:
        """One greppable result line, e.g. for CAMPUS_RESULT."""
        reachable = self.pairs - len(self.unreachable)
        ok = self.passed and assoc_ok == assoc_total
        return (
            f"{tag} assoc={assoc_ok}/{assoc_total} reachable={reachable}/{self.pairs} "
            f"loss={self.loss_pct:.2f}% (budget {self.max_loss_pct}%) "
            f"first_try_failures={len(self.first_try_failures)} -> {'PASS' if ok else 'FAIL'}"
        )


def evaluate(
    first: Mapping[Pair, bool], retry: Mapping[Pair, bool], max_loss_pct: float
) -> ConnectivityReport:
    """Combine a first-try ping matrix with retries of its failures into a verdict.

    A pair that failed first and has no successful retry counts as unreachable.
    """
    if not first:
        raise ValueError("no ping results to evaluate")
    failures = [pair for pair, ok in first.items() if not ok]
    unreachable = [pair for pair in failures if not retry.get(pair, False)]
    return ConnectivityReport(
        pairs=len(first),
        loss_pct=100.0 * len(failures) / len(first),
        max_loss_pct=max_loss_pct,
        first_try_failures=failures,
        unreachable=unreachable,
    )
