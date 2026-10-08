"""P4.2 anomaly metrics: window-level precision/recall/F1, threshold choice, detection delay."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any


def precision_recall_f1(
    labels: Sequence[bool], flags: Sequence[bool]
) -> tuple[float, float, float]:
    """Precision, recall and F1 of `flags` against `labels` (0.0 where undefined)."""
    tp = sum(1 for y, f in zip(labels, flags, strict=True) if y and f)
    fp = sum(1 for y, f in zip(labels, flags, strict=True) if not y and f)
    fn = sum(1 for y, f in zip(labels, flags, strict=True) if y and not f)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return precision, recall, f1


def best_threshold(scores: Sequence[float], labels: Sequence[bool]) -> float:
    """The score threshold (flag score >= threshold) with the best F1; lowest on ties."""
    if not scores:
        raise ValueError("no scores to choose a threshold from")
    return max(
        sorted(set(scores)), key=lambda t: precision_recall_f1(labels, [s >= t for s in scores])[2]
    )


def detection_delays(
    rows: Sequence[tuple[str, float | None, float, bool]],
) -> dict[str, dict[str, Any]]:  # Any: delay_s float | None, false_alarms_before int
    """Per run with a disruption: seconds from onset to the first alert (None if never) and
    alerts raised before the onset. `rows` are (run_id, onset_s, window t_end_s, flagged)."""
    out: dict[str, dict[str, Any]] = {}
    for run, onset, t_end, flagged in sorted(rows, key=lambda r: (r[0], r[2])):
        if onset is None:
            continue
        entry = out.setdefault(run, {"delay_s": None, "false_alarms_before": 0})
        if flagged and t_end < onset:
            entry["false_alarms_before"] += 1
        elif flagged and entry["delay_s"] is None:
            entry["delay_s"] = t_end - onset
    return out
