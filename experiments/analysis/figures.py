"""P6.6 figures: one per scenario, one panel per KPI, each mode a point with its 95% CI.

Colours: the dataviz reference categorical slots 1-3, validated on the chart surface (CVD and
normal-vision separation pass; aqua is under 3:1 contrast, so every point carries a direct
value label and its mode on the axis, and results.md is the table view).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from matplotlib.axes import Axes
from matplotlib.figure import Figure  # no pyplot: no global state, no display backend
from matplotlib.lines import Line2D

from experiments.analysis.campaign import KPI_TITLES
from experiments.batch import LOOP_MODES

WHOLE_FROM = 10.0  # labels drop the decimals from here on
MODES = LOOP_MODES
MODE_COLOURS = dict(zip(MODES, ("#2a78d6", "#eb6834", "#1baf7a"), strict=True))
SURFACE, INK, MUTED, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
BOUNDS = {"loss_pct": (0.0, 100.0), "jain": (0.0, 1.0)}  # what each KPI can be; others >= 0
Row = dict[str, Any]  # Any: a row of the results table (results.kpi_table), JSON values


def kpi_figure(rows: Sequence[Row], scenario: str, path: Path) -> None:
    """Write `path` (PNG): one scenario's rows (the results table), mean ± 95% CI per mode."""
    fig = Figure(figsize=(3.2 * len(KPI_TITLES), 3.4), facecolor=SURFACE)
    axes = fig.subplots(1, len(KPI_TITLES))
    cells = {(r["mode"], r["kpi"]): r for r in rows}
    drawn: set[str] = set()
    for ax, (kpi, title) in zip(axes, KPI_TITLES.items(), strict=True):
        for x, mode in enumerate(MODES):
            r = cells.get((mode, kpi))
            if r is not None and r["mean"] is not None:
                _point(ax, x, mode, kpi, r)
                drawn.add(mode)
        _style(ax, kpi, title)
    handles = [  # only the modes with data in this figure
        Line2D([], [], marker="o", linestyle="", color=MODE_COLOURS[m], label=m)
        for m in MODES
        if m in drawn
    ]
    fig.legend(handles=handles, loc="upper right", ncol=3, frameon=False, fontsize=9)
    title = f"{scenario.replace('_', ' ')}: mean ± 95% CI over seeds"
    fig.suptitle(title, x=0.01, ha="left", fontsize=11, color=INK)
    fig.tight_layout(rect=(0, 0, 1, 0.92))
    fig.savefig(path, dpi=200)


def _point(ax: Axes, x: int, mode: str, kpi: str, r: Row) -> None:
    """One mode's mean, its interval clipped to what the KPI can be (with n = 3 the t interval
    can pass it), and a direct value label."""
    low, high = BOUNDS.get(kpi, (0.0, math.inf))
    mean, ci = r["mean"], r["ci95"] or 0.0
    down = max(0.0, mean - max(low, mean - ci))
    up = max(0.0, min(high, mean + ci) - mean)
    colour = MODE_COLOURS[mode]
    ax.errorbar(
        x, mean, yerr=[[down], [up]], fmt="o", markersize=7, color=colour, ecolor=colour,
        elinewidth=2, capsize=0, markeredgecolor=SURFACE, markeredgewidth=2, label=mode,
    )  # fmt: skip
    label = f"{mean:.0f}" if mean >= WHOLE_FROM else f"{mean:.2f}"
    if r["never"]:
        label = f"≥{label} ({r['never']} never)"
    ax.annotate(
        label, (x, mean), xytext=(9, 0), textcoords="offset points", va="center", fontsize=8,
        color=INK,
    )  # fmt: skip


def _style(ax: Axes, kpi: str, title: str) -> None:
    """A recessive panel: zero baseline, light grid, mode names on the axis."""
    ax.set_facecolor(SURFACE)
    ax.set_title(title, fontsize=9.5, color=INK, loc="left")
    ax.set_ylim(bottom=0.0)  # magnitudes: a cut axis would exaggerate the gaps
    if kpi == "jain":  # a ratio: its whole range (loss keeps its own scale, not 0-100)
        ax.set_ylim(0.0, 1.05)
    ax.set_xticks(range(len(MODES)), MODES, fontsize=9, color=MUTED)
    ax.set_xlim(-0.5, len(MODES) - 0.2)
    ax.tick_params(axis="y", labelsize=8, colors=MUTED, length=0)
    ax.tick_params(axis="x", length=0)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
