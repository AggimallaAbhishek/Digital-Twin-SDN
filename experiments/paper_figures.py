"""The IEEE paper's plots (final_submission/paper/figures/*.pdf), drawn when `make paper` builds the
paper (experiments/paper_build.py). Every mark comes from the recorded evaluation
(experiments/paper_evidence.py) or, for the model curves, from the twin's own code and
configuration: nothing is typed by hand.

Each figure is a vector PDF drawn at its printed size (an IEEE column is 3.45 in, the page
7.16 in) with embedded TrueType text and no creation date, so a rebuild from the same evaluation
gives the same bytes. Colours follow the dataviz reference palette, validated on the chart surface
(adjacent pairs): the three variants keep slots 1-3 as in the results figures
(experiments/analysis/figures.py); the four APs take slots 7, 5, 4 and 6; a method beside its
baseline is violet beside grey, and a second measure beside it yellow with a texture; an action's
fate takes the status colours, each with its own marker and legend label, never colour alone.
Colours under 3:1 contrast on the surface always carry a direct label or a legend entry.
"""

from __future__ import annotations

import contextlib
import math
import statistics
from collections.abc import Callable, Iterator, Mapping, Sequence
from itertools import pairwise
from pathlib import Path
from typing import Literal

import matplotlib
from matplotlib.artist import Artist
from matplotlib.axes import Axes
from matplotlib.figure import Figure  # no pyplot: no global state, no display backend
from matplotlib.lines import Line2D
from matplotlib.patches import Patch, Rectangle

from controller.executor.live_kpis import p95
from experiments.analysis.campaign import KPI_TITLES, jain_per_window
from experiments.analysis.figures import GRID, INK, MODE_COLOURS, MUTED, SURFACE
from experiments.analysis.results import JAIN_TARGET
from experiments.analysis.time_to_recover import RecoveryRule
from experiments.batch import LOOP_MODES, load_scenario
from experiments.paper_evidence import (
    KPIS,
    MODE_LABELS,
    RESOLVED,
    SCENARIOS,
    STATUS_WORDS,
    Evidence,
    Json,
    Point,
    Row,
    RunSeries,
    capacity_mbps,
    cochannel_pairs,
    correct_by_kind,
    intent_kinds,
    kpi_cells,
    kpi_range,
    latency_cap_ms,
    live_errors,
    prediction_times,
    resolved_actions,
)
from twin.radio import load_radio_params
from twin.sim.analytical import _mm1k_mean_number, load_sim_params
from twin.verify.verifier import _better_pct

COLUMN_IN, PAGE_IN = 3.45, 7.16  # IEEE column and page width
FLASH_CROWD = "lecture_flash_crowd"  # the scenario whose walkers the campus map draws
MOVED_M = 2.0  # a station that moved further than this before the onset is drawn as a walker
CURVE_POINTS = 200  # segments of each model curve
MAX_LOAD = 2.0  # the queueing curve runs from no load to this (demand over capacity)
VIOLET, MAGENTA, YELLOW, GREEN = "#6250d6", "#e87ba4", "#eda100", "#008300"  # slots 7, 5, 4, 6
AP_SLOTS = (VIOLET, MAGENTA, YELLOW, GREEN)  # the APs, in their configured order
METHOD, SECOND, BASELINE = VIOLET, YELLOW, "#8a8984"
ZONE_FILL = "#f0efec"  # the reference palette's neutral (the diverging midpoint)
LABEL_BOX = {"boxstyle": "round,pad=0.15", "fc": SURFACE, "ec": "none", "alpha": 0.85}
BAR_STYLES = {  # a bar series' role -> (colour, hatch): the texture tells them apart in print
    "method": (METHOD, ""),
    "second": (SECOND, "///"),
    "baseline": (BASELINE, "\\\\\\"),
}
FATES: dict[str, tuple[str, str, bool]] = {  # ledger status -> colour, marker, filled
    "kept": ("#0ca30c", "o", True),
    "rolled_back": ("#ec835a", "v", True),
    "rollback_failed": ("#d03b3b", "X", True),
    "applied": (MUTED, "P", True),
    "rejected": (MUTED, "s", False),
    "verified": ("#fab219", "D", False),
}
ERROR_FLOOR_PCT = 0.1  # the error axis is logarithmic: smaller errors are drawn here
SYMLOG_LINEAR_PCT = 10.0  # a symmetric-log axis is linear within ±this (%), logarithmic beyond
LABEL_GAP = 0.085  # direct labels at line ends: at least this share of the y-axis apart
CASE_WORDS = {  # twin validation case kind -> what the figure calls it
    "steady": "steady state",
    "steer_clients": "client steering",
    "set_ap_channel": "channel change",
    "ap_admin_state": "AP down / up",
    "set_qos_queue": "QoS queue",
    "rate_limit_flow": "rate limit",
    "set_ap_tx_power": "tx power",
}
LIVE_TITLES = {"throughput_mbps": "Throughput", "latency_ms": "Latency", "loss_pct": "Loss"}
SHORT_TITLES = {  # scenario -> its name on an axis tick or a map label
    "lecture_flash_crowd": "Flash crowd",
    "ap_failure": "AP failure",
    "cochannel_interference": "Interference",
}
Metric = Callable[[RunSeries, float], list[float]]  # a run, the window (s) -> a value per window


# ---------------------------------------------------------------- data shaping


def windows(
    rows: Sequence[Row],
    value: Callable[[Row], float | None],
    reduce: Callable[[list[float]], float],
    end_s: float,
    step_s: float,
) -> list[float]:
    """One value per `step_s` window from 0 to `end_s`: `reduce` of the rows' values in it, NaN
    for a window without any (a gap in the line)."""
    bins: list[list[float]] = [[] for _ in range(math.ceil(end_s / step_s))]
    for r in rows:
        v, i = value(r), int(r["t_s"] // step_s)
        if v is not None and 0 <= i < len(bins):
            bins[i].append(v)
    return [reduce(b) if b else math.nan for b in bins]


def midpoints(count: int, step_s: float) -> list[float]:
    """The middle of each of `count` windows of `step_s` from 0: where a window's value is drawn."""
    return [(i + 0.5) * step_s for i in range(count)]


def across_runs(series: Sequence[Sequence[float]]) -> tuple[list[float], list[float], list[float]]:
    """Per window: the mean, the smallest and the largest value over the runs that have one
    (NaN where none has)."""
    mean, low, high = [], [], []
    for values in zip(*series, strict=True):
        known = [v for v in values if not math.isnan(v)]
        mean.append(statistics.fmean(known) if known else math.nan)
        low.append(min(known, default=math.nan))
        high.append(max(known, default=math.nan))
    return mean, low, high


def ecdf(values: Sequence[float]) -> tuple[list[float], list[float]]:
    """The empirical distribution: the sorted values and the share of values up to each."""
    ordered = sorted(values)
    return ordered, [(i + 1) / len(ordered) for i in range(len(ordered))]


def dodge(values: Sequence[float], gap: float) -> list[float]:
    """Positions for labels at `values`, moved up where needed so that any two are at least
    `gap` apart (direct labels at the ends of lines that end close together)."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    out = list(values)
    for below, above in pairwise(order):
        out[above] = max(out[above], out[below] + gap)
    return out


def ap_series(run: RunSeries, ap: str, column: str, step_s: float) -> list[float]:
    """One AP's stat (a column of its rows) per window, averaged."""
    rows = [r for r in run.ap_stats if r["ap"] == ap]
    return windows(rows, lambda r: r[column], statistics.fmean, run.end_s, step_s)


def utilisation(run: RunSeries, step_s: float) -> list[float]:
    """U(t) of Eq. (5): the affected AP's utilisation per window."""
    return ap_series(run, run.affected_ap, "channel_util", step_s)


def fairness(run: RunSeries, step_s: float) -> list[float]:
    """Jain's index (Eq. (4)) of the APs' client counts per window, as the results tables
    compute it before averaging it over the stress window."""
    by_window = jain_per_window(run.ap_stats, step_s)
    return [by_window.get(i, math.nan) for i in range(math.ceil(run.end_s / step_s))]


def video_p95(run: RunSeries, step_s: float) -> list[float]:
    """The p95 latency of the affected video flows per window (ms), by nearest rank as the
    results tables take it."""
    rows = [r for r in run.affected_kpis if r["app_class"] == "video"]
    return windows(rows, lambda r: r["latency_ms"], lambda b: p95(sorted(b)), run.end_s, step_s)


def mean_loss(run: RunSeries, step_s: float) -> list[float]:
    """The mean loss of the affected flows per window (%)."""
    return windows(run.affected_kpis, lambda r: r["loss_pct"], statistics.fmean, run.end_s, step_s)


def walkers(run: RunSeries) -> dict[str, tuple[Point, Point]]:
    """The stations that moved more than MOVED_M before the onset: where each started and where
    it was just before the onset."""
    return {
        sta: (start, run.onset_xy[sta])
        for sta, start in run.start_xy.items()
        if sta in run.onset_xy and math.dist(start, run.onset_xy[sta]) > MOVED_M
    }


def action_times(ev: Evidence, mode: str) -> dict[str, list[tuple[float, str]]]:
    """Per run of a variant: when each action was proposed (seconds into the run) and its fate."""
    return {
        run_id: [
            ((r.action.created_at - ev.run_starts[mode][run_id]).total_seconds(), r.status)
            for r in records
        ]
        for run_id, records in ev.ledgers[mode].items()
    }


def throughput_changes(ev: Evidence) -> list[tuple[float, float, str]]:
    """Every resolved action that the watch measured: the change in throughput the twin
    predicted and the change the watch measured against the live KPIs before the action (both
    in %, positive is better, over the flows the verdict compared), and its fate."""
    kpi = "throughput_mbps"
    out = []
    for r in resolved_actions(ev):
        if r.measured is None or r.baseline is None:
            continue
        predicted = _better_pct(
            kpi, r.verdict.baseline.throughput_mbps, r.verdict.predicted.throughput_mbps
        )
        measured = _better_pct(kpi, r.baseline.throughput_mbps, r.measured.throughput_mbps)
        if math.isfinite(predicted) and math.isfinite(measured):  # a change from 0 has no %
            out.append((predicted, measured, r.status))
    return out


def intent_results(ev: Evidence) -> dict[str, tuple[dict[str, tuple[int, int]], list[float]]]:
    """Per model (its name in the evaluation file): (correct, intents) per kind of intent, and
    the seconds each intent took."""
    kinds = intent_kinds(ev)
    return {
        " + ".join(r["models"]): (correct_by_kind(r, kinds), r["seconds"])
        for r in (ev.intents, ev.intents_local)
    }


def detections(ev: Evidence) -> dict[str, Json]:
    """The first-alert delay of each test run by its scenario (the run ids start with it); one
    test run per scenario, or the figure would have to choose."""
    out: dict[str, Json] = {}
    for run_id, entry in ev.anomaly["test_detection"].items():
        scenario = next((s for s in SCENARIOS if run_id.startswith(f"{s}-")), None)
        if scenario in out:
            raise ValueError(f"two test runs of {scenario} in the anomaly evaluation")
        if scenario is not None:
            out[scenario] = entry
    return out


def _period_s(ev: Evidence) -> float:
    """The control loop's period (s): the window the time series are averaged over."""
    return float(ev.config["loop"]["period_s"])


def _title(scenario: str) -> str:
    """A scenario's title; one outside the campaign by its id."""
    title = SCENARIOS[scenario][1] if scenario in SCENARIOS else scenario.replace("_", " ")
    return title[0].upper() + title[1:]


def _short(scenario: str) -> str:
    """A scenario's name where a full title does not fit (an axis tick, a map label)."""
    return SHORT_TITLES.get(scenario) or _title(scenario)


def _scenario_order(keys: Sequence[str]) -> list[str]:
    """The campaign's scenarios in the paper's order, then any other (e.g. normal)."""
    return [s for s in SCENARIOS if s in keys] + sorted(k for k in keys if k not in SCENARIOS)


def _ap_colours(ev: Evidence) -> dict[str, str]:
    names = [ap["name"] for ap in ev.config["campus_v1"]["aps"]]
    return dict(zip(names, AP_SLOTS, strict=True))


def _symlog_limits(values: Sequence[float]) -> tuple[float, float]:
    """Axis limits a little beyond the values on a symmetric-log axis (linear within ±10)."""

    def pad(v: float) -> float:
        return v * 1.6 if abs(v) > SYMLOG_LINEAR_PCT else v + math.copysign(SYMLOG_LINEAR_PCT, v)

    return pad(min([*values, -1.0])), pad(max([*values, 1.0]))  # no values: ±11


# ---------------------------------------------------------------- style


@contextlib.contextmanager
def _pdf_style() -> Iterator[None]:
    """IEEE-ready PDF text (embedded TrueType, no Type 3) for the figures drawn inside."""
    with matplotlib.rc_context():  # restores the settings on exit
        params = matplotlib.rcParams
        params["pdf.fonttype"] = 42
        params["font.family"] = "serif"
        params["font.size"] = 7
        params["axes.linewidth"] = 0.6
        params["legend.fontsize"] = 6
        params["axes.titlesize"] = 7
        params["hatch.color"] = SURFACE  # texture (the second series) as light lines on the fill
        params["hatch.linewidth"] = 0.6
        yield


def _to_pdf(draw: Callable[[Evidence], Figure]) -> Callable[[Evidence, Path], None]:
    """A drawing as a figure file: drawn in the paper's style (the settings apply while it is
    drawn, not only when saved) and written as a PDF without a creation date."""

    def write(ev: Evidence, path: Path) -> None:
        with _pdf_style():
            draw(ev).savefig(path, format="pdf", metadata={"CreationDate": None})

    return write


def _figure(width: float, height: float) -> Figure:
    return Figure(figsize=(width, height), facecolor=SURFACE, layout="constrained")


def _style(ax: Axes, grid: Literal["both", "x", "y"] = "y") -> None:
    ax.set_facecolor(SURFACE)
    ax.grid(axis=grid, color=GRID, linewidth=0.5)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.tick_params(length=2, width=0.5)


def _legend(fig: Figure, handles: Sequence[Artist], *, below: bool = False, rows: int = 1) -> None:
    """The figure's legend in a row (or `rows` rows) above its panels, or below them."""
    fig.legend(
        handles=handles,
        loc="outside lower center" if below else "outside upper center",
        ncols=math.ceil(len(handles) / rows),
        frameon=False,
    )


def _handles(ax: Axes) -> list[Artist]:
    return list(ax.get_legend_handles_labels()[0])


def _onset(ax: Axes, onset_s: float) -> None:
    """The disruption's onset t_d, a dotted line labelled at the top."""
    ax.axvline(onset_s, color=MUTED, linestyle=":", linewidth=0.8)
    ax.text(
        onset_s,
        0.98,
        "$t_d$",
        transform=ax.get_xaxis_transform(),
        ha="center",
        va="top",
        fontsize=6,
        color=MUTED,
        bbox={"boxstyle": "round,pad=0.1", "fc": SURFACE, "ec": "none"},
        zorder=4,
    )


def _limit(ax: Axes, value: float, label: str) -> None:
    """A threshold line, labelled at its right end."""
    ax.axhline(value, color=INK, linestyle="--", linewidth=0.6)
    ax.text(
        1.0,
        value,
        label,
        transform=ax.get_yaxis_transform(),
        ha="right",
        va="bottom",
        fontsize=6,
        color=INK,
    )


def _fate_marker(ax: Axes, xs: Sequence[float], ys: Sequence[float], status: str) -> None:
    colour, marker, filled = FATES[status]
    ax.scatter(
        xs,
        ys,
        s=14,
        marker=marker,
        c=colour if filled else "none",
        edgecolors=colour,
        linewidths=0.8,
        zorder=3,
    )


def _fate_handle(status: str, count: int) -> Line2D:
    colour, marker, filled = FATES[status]
    return Line2D(
        [],
        [],
        linestyle="none",
        marker=marker,
        markersize=4,
        markerfacecolor=colour if filled else "none",
        markeredgecolor=colour,
        label=f"{STATUS_WORDS[status][1]} ({count})",
    )


def _grouped_barh(
    ax: Axes, scenarios: Sequence[str], series: Sequence[tuple[str, Sequence[float], str]]
) -> None:
    """Horizontal bars, a group per scenario (top to bottom) and in it a bar per series
    (label, value per scenario, role in BAR_STYLES)."""
    height = 0.8 / len(series)
    for k, (label, values, role) in enumerate(series):
        colour, hatch = BAR_STYLES[role]
        ys = [i + _offset(k, len(series), height) for i in range(len(scenarios))]
        ax.barh(ys, values, height * 0.9, color=colour, hatch=hatch, label=label)
    ax.set_yticks(range(len(scenarios)), [_short(s) for s in scenarios])
    if not ax.yaxis_inverted():  # panels sharing the axis invert it once between them
        ax.invert_yaxis()


def _offset(k: int, count: int, width: float) -> float:
    """Where bar `k` of `count` side by side sits from its group's centre."""
    return (k - (count - 1) / 2) * width


# ---------------------------------------------------------------- the campus and the model


def figure_campus(ev: Evidence) -> Figure:
    """The campus: zones, APs with their channels and scripted events, the co-channel pair, and
    the stations at the start of a flash-crowd run (the first seed of V1, which does not steer)
    with the walkers' paths into the hall."""
    campus = ev.config["campus_v1"]
    run = min(ev.runs(LOOP_MODES[0], FLASH_CROWD), key=_seed)
    fig = _figure(COLUMN_IN, 3.0)
    ax = fig.subplots()
    ax.set_facecolor(SURFACE)
    _draw_zones(ax, campus)
    moved = walkers(run)
    still = [xy for sta, xy in run.start_xy.items() if sta not in moved]
    ax.scatter([x for x, _ in still], [y for _, y in still], s=6, c=MUTED, zorder=2)
    for (x0, y0), (x1, y1) in moved.values():
        ax.annotate(
            "",
            (x1, y1),
            (x0, y0),
            arrowprops={"arrowstyle": "-|>", "color": BASELINE, "lw": 0.5, "mutation_scale": 5},
            zorder=2,
        )
        ax.scatter([x0], [y0], s=7, facecolors="none", edgecolors=INK, lw=0.5, zorder=2)
    _draw_aps(ax, campus, _ap_colours(ev))
    width_m, height_m = campus["area_m"]
    ax.set(xlim=(0, width_m), ylim=(0, height_m), xlabel="x (m)", ylabel="y (m)", aspect="equal")
    ax.tick_params(length=2, width=0.5)
    walker = f"walker (seed {run.seed}): start, path to $t_d$"
    _legend(
        fig,
        [
            Line2D([], [], ls="none", marker="^", mfc="white", mec=INK, ms=5, label="AP"),
            Line2D([], [], ls="none", marker="o", mfc=MUTED, mec=MUTED, ms=2.5, label="station"),
            Line2D(
                [], [], color=BASELINE, lw=0.6, marker="o", mfc="none", mec=INK, ms=3, label=walker
            ),
            Line2D([], [], color=MUTED, ls="--", lw=0.8, label="same channel"),
        ],
        below=True,
        rows=2,
    )
    return fig


def _seed(run: RunSeries) -> int:
    return run.seed


def _draw_zones(ax: Axes, campus: Json) -> None:
    """The campus's zones, named, and a dashed line between APs that share a channel."""
    for zone, box in campus["zones"].items():
        (x0, x1), (y0, y1) = box["x"], box["y"]
        ax.add_patch(
            Rectangle((x0, y0), x1 - x0, y1 - y0, facecolor=ZONE_FILL, edgecolor=GRID, lw=0.8)
        )
        ax.text(x0 + 1.2, y1 - 1.2, zone.replace("_", " "), va="top", fontsize=6, color=MUTED)
    places = {ap["name"]: ap["position"] for ap in campus["aps"]}
    for a, b, distance_m in cochannel_pairs(campus):
        (xa, ya), (xb, yb) = places[a], places[b]
        ax.plot([xa, xb], [ya, yb], color=MUTED, linestyle="--", lw=0.8)
        ax.text((xa + xb) / 2, (ya + yb) / 2, f"{distance_m:.0f} m", fontsize=5.5, ha="center",
                va="center", bbox=LABEL_BOX, zorder=4)  # fmt: skip


def _draw_aps(ax: Axes, campus: Json, colours: Mapping[str, str]) -> None:
    """Each AP with its channel and the event each scenario scripts for it."""
    events: dict[str, list[str]] = {ap: [] for ap in colours}
    for scenario in SCENARIOS:
        for e in load_scenario(scenario).events:
            what = "down" if e.type == "ap_down" else f"to ch {e.channel}"
            events[e.ap].append(f"{_short(scenario)}: {what} at {e.at_s:.0f} s")
    for ap in campus["aps"]:
        x, y = ap["position"]
        ax.scatter(
            [x], [y], s=40, marker="^", c=colours[ap["name"]], edgecolors=INK, lw=0.5, zorder=5
        )
        text = "\n".join([f"{ap['name']} (ch {ap['channel']})", *events[ap["name"]]])
        ax.text(x + 2, y - 1.5, text, fontsize=5.5, va="top", bbox=LABEL_BOX, zorder=4)


def figure_model(ev: Evidence) -> Figure:
    """The twin's model with its own functions and parameters: an AP's capacity against the
    distance of one or two same-channel APs (Eq. (1)), and the queueing delay against the load
    (Eq. (3), the M/M/1/K mean number of the twin's simulator) with its cap and the recovery
    criterion's latency limit."""
    radio = load_radio_params(ev.config["campus_v1"])
    sim = load_sim_params(ev.config["sim"])
    fig = _figure(COLUMN_IN, 1.65)
    cap_ax, lat_ax = fig.subplots(1, 2)
    far_m = radio.cochannel_zero_m * 4 / 3
    distances_m = [far_m * i / CURVE_POINTS for i in range(CURVE_POINTS + 1)]
    for n, style, label in ((1, "-", "one same-channel AP"), (2, "--", "two, equally far")):
        caps = [capacity_mbps([d] * n, radio) for d in distances_m]
        cap_ax.plot(distances_m, caps, style, color=METHOD, linewidth=1.0, label=label)
    for a, b, distance_m in cochannel_pairs(ev.config["campus_v1"]):
        cap = capacity_mbps([distance_m], radio)
        cap_ax.plot([distance_m], [cap], "o", color=INK, ms=3)
        cap_ax.annotate(
            f"{a}, {b}",
            (distance_m, cap),
            xytext=(-4, 3),
            textcoords="offset points",
            ha="right",
            va="bottom",
            fontsize=6,
        )
    _style(cap_ax)
    cap_ax.set(xlabel="Distance to the AP (m)", ylabel="Capacity $C_i$ (Mbit/s)")
    cap_ax.set_ylim(0, radio.ap_capacity_mbps * 1.1)
    cap_ax.legend(loc="lower right", frameon=False, handlelength=1.6)
    loads = [MAX_LOAD * i / CURVE_POINTS for i in range(CURVE_POINTS + 1)]
    delays_ms = [
        sim.base_latency_ms + sim.service_ms * _mm1k_mean_number(r, sim.queue_slots) for r in loads
    ]
    _style(lat_ax)
    lat_ax.plot(loads, delays_ms, color=METHOD, linewidth=1.0)
    top_ms = latency_cap_ms(sim)
    lat_ax.axhline(top_ms, color=METHOD, linestyle=":", linewidth=0.8)
    lat_ax.text(0.02, top_ms, "model's cap", va="bottom", fontsize=6, color=INK)
    _limit(lat_ax, RecoveryRule().video_latency_ms, "recovery limit")
    lat_ax.set(xlabel=r"Load $\rho_q$", ylabel="Delay $d_q$ (ms)", ylim=(0, None))
    return fig


# ---------------------------------------------------------------- results per run


def figure_kpis(ev: Evidence) -> Figure:
    """Loss and throughput of the affected flows, per scenario and variant."""
    cells = kpi_cells(ev)
    rows = (("loss_pct", "Loss (%)"), ("throughput_mbps", "Throughput (Mbit/s)"))
    fig = _figure(PAGE_IN, 2.2)
    grid = fig.subplots(len(rows), len(SCENARIOS), sharex=True)
    for r, (kpi, label) in enumerate(rows):
        for c, (scenario, (_, title)) in enumerate(SCENARIOS.items()):
            ax = grid[r][c]
            _style(ax)
            for i, mode in enumerate(LOOP_MODES):
                cell = cells[(mode, scenario, kpi)]
                lo, hi = kpi_range(ev, mode, scenario, kpi)  # the runs' own range
                low, up = max(0.0, cell["mean"] - lo), max(0.0, hi - cell["mean"])
                ax.bar(
                    i,
                    cell["mean"],
                    0.62,
                    color=MODE_COLOURS[mode],
                    yerr=[[low], [up]],
                    error_kw={"linewidth": 0.7, "capsize": 2},
                )
                ax.annotate(  # the value above the interval: the colours alone do not say it
                    f"{cell['mean']:.{KPIS[kpi][1]}f}",
                    (i, cell["mean"] + up),
                    xytext=(0, 2),
                    textcoords="offset points",
                    ha="center",
                    va="bottom",
                    fontsize=6,
                )
            if r == 0:
                ax.set_title(title)
            if c == 0:
                ax.set_ylabel(label)
            ax.set_xticks(range(len(LOOP_MODES)), list(LOOP_MODES))
    return fig


def figure_recovery(ev: Evidence) -> Figure:
    """Time to recover of every run; a hollow triangle is a run that never recovered (counted at
    its run end)."""
    runs = ev.results["runs"]
    fig = _figure(COLUMN_IN, 2.0)
    ax = fig.subplots()
    _style(ax)
    ticks = [si * 4 + mi for si in range(len(SCENARIOS)) for mi in range(len(LOOP_MODES))]
    for si, scenario in enumerate(SCENARIOS):
        for mi, mode in enumerate(LOOP_MODES):
            x = si * 4 + mi
            for k, run in enumerate(runs[f"{mode}/{scenario}"]):
                xs = x + (k - 1) * 0.26  # apart, so runs with near-equal times stay visible
                if run["ttr_s"] is None:
                    ax.plot(
                        xs,
                        run["censor_s"],
                        "^",
                        mfc="white",
                        mec=MODE_COLOURS[mode],
                        ms=4.5,
                        mew=0.9,
                    )
                else:
                    ax.plot(xs, run["ttr_s"], "o", color=MODE_COLOURS[mode], ms=4, alpha=0.8)
        ax.text(
            si * 4 + 1,
            -0.24,
            SCENARIOS[scenario][1].replace(" ", "\n", 1),
            ha="center",
            va="top",
            fontsize=6,
            transform=ax.get_xaxis_transform(),
        )
    ax.set_xticks(ticks, list(LOOP_MODES) * len(SCENARIOS))
    ax.set_ylabel("Time to recover (s)")
    ax.set_ylim(0, None)
    return fig


def _over_time(
    ev: Evidence, metric: Metric, label: str, limit: tuple[float, str] | None = None
) -> tuple[Figure, list[Axes]]:
    """One panel per scenario: a KPI per window over the run, per variant the mean over its seeds
    (line) and their smallest to largest value (band)."""
    step_s = _period_s(ev)
    fig = _figure(PAGE_IN, 1.85)
    axes = list(fig.subplots(1, len(SCENARIOS), sharey=True))
    for ax, scenario in zip(axes, SCENARIOS, strict=True):
        _style(ax)
        runs: list[RunSeries] = []
        for mode in LOOP_MODES:
            runs = ev.runs(mode, scenario)
            mean, low, high = across_runs([metric(s, step_s) for s in runs])
            t = midpoints(len(mean), step_s)
            ax.fill_between(t, low, high, color=MODE_COLOURS[mode], alpha=0.14, linewidth=0)
            ax.plot(t, mean, color=MODE_COLOURS[mode], linewidth=0.9, label=MODE_LABELS[mode])
        _onset(ax, runs[0].onset_s)
        if limit is not None:  # labelled in the legend: a label on the line would cover data
            ax.axhline(limit[0], color=INK, linestyle="--", linewidth=0.6, label=limit[1])
        ax.set_title(_title(scenario))
        ax.set_xlim(0, runs[0].end_s)
        ax.set_xlabel("Time into the run (s)")
    axes[0].set_ylabel(label)
    _legend(fig, _handles(axes[0]))
    return fig, axes


def figure_utilisation(ev: Evidence) -> Figure:
    """U(t), the utilisation of the affected AP, against the recovery criterion's limit."""
    limit = RecoveryRule().util_limit
    label = "Utilization of the affected AP"
    return _over_time(ev, utilisation, label, (limit, f"Recovery limit {limit:g}"))[0]


def figure_latency(ev: Evidence) -> Figure:
    """The p95 latency of the affected video flows, against the recovery criterion's limit."""
    limit = RecoveryRule().video_latency_ms
    label = KPI_TITLES["latency_p95_ms"]
    fig, axes = _over_time(ev, video_p95, label, (limit, f"Recovery limit {limit:g} ms"))
    axes[0].set_yscale("log")
    return fig


def figure_loss(ev: Evidence) -> Figure:
    """The mean loss of the affected flows."""
    return _over_time(ev, mean_loss, KPI_TITLES["loss_pct"])[0]


def figure_fairness(ev: Evidence) -> Figure:
    """Jain's index of the APs' client counts, against the flash crowd's fairness target."""
    label = "Jain's index (clients per AP)"
    fig, axes = _over_time(ev, fairness, label, (JAIN_TARGET, f"Fairness target {JAIN_TARGET:g}"))
    axes[0].set_ylim(0, 1.05)
    return fig


def figure_clients(ev: Evidence) -> Figure:
    """The flash crowd: each AP's clients over the run under each variant (mean over seeds),
    with a legend and each line labelled at its end."""
    step_s = _period_s(ev)
    colours = _ap_colours(ev)
    runs = {m: ev.runs(m, FLASH_CROWD) for m in LOOP_MODES}
    means = {
        m: {
            ap: across_runs([ap_series(s, ap, "n_clients", step_s) for s in runs[m]])[0]
            for ap in colours
        }
        for m in LOOP_MODES
    }
    top = 1.1 * max(
        (
            v
            for lines in means.values()
            for line in lines.values()
            for v in line
            if not math.isnan(v)
        ),
        default=1.0,
    )
    places = {  # the labels at the lines' ends, apart by a share of the axis
        m: dodge([_last(line) for line in lines.values()], LABEL_GAP * top)
        for m, lines in means.items()
    }
    top = max(top, *(y for ys in places.values() for y in ys))
    fig = _figure(PAGE_IN, 1.75)
    axes = fig.subplots(1, len(LOOP_MODES), sharey=True)
    for ax, mode in zip(axes, LOOP_MODES, strict=True):
        _style(ax)
        for (ap, line), y in zip(means[mode].items(), places[mode], strict=True):
            ax.plot(midpoints(len(line), step_s), line, color=colours[ap], lw=1.0, label=ap)
            ax.text(runs[mode][0].end_s + 4, y, ap, va="center", fontsize=6, color=INK)
        _onset(ax, runs[mode][0].onset_s)
        ax.set_title(MODE_LABELS[mode])
        ax.set_xlim(0, runs[mode][0].end_s)
        ax.set_xlabel("Time into the run (s)")
    axes[0].set_ylabel("Associated clients")
    axes[0].set_ylim(0, top)
    _legend(fig, _handles(axes[0]))
    return fig


def _last(line: Sequence[float]) -> float:
    """A line's last value that is not a gap (0 if it is all gaps)."""
    return next((v for v in reversed(line) if not math.isnan(v)), 0.0)


# ---------------------------------------------------------------- actions and the twin


def figure_timeline(ev: Evidence) -> Figure:
    """Every action of the variants that act, at the time it was proposed, by its fate; one row
    per run, a short bar at the disruption's onset."""
    modes = [m for m in LOOP_MODES if ev.actions(m)]
    order = list(SCENARIOS)
    fig = _figure(PAGE_IN, 2.5)
    axes = fig.subplots(1, len(modes), sharey=True, squeeze=False)[0]
    shown: dict[str, int] = {}
    labels: list[str] = []
    for ax, mode in zip(axes, modes, strict=True):
        _style(ax, grid="x")
        times = action_times(ev, mode)
        series = {s.run_id: s for s in ev.series[mode]}
        runs = sorted((series[r] for r in times), key=lambda s: (order.index(s.scenario), s.seed))
        labels = [f"{_title(run.scenario)}, {run.seed}" for run in runs]
        for y, run in enumerate(runs):
            ax.plot([run.onset_s] * 2, [y - 0.38, y + 0.38], color=MUTED, linewidth=1.2)
            for status in FATES:
                at = [t for t, s in times[run.run_id] if s == status]
                if at:
                    _fate_marker(ax, at, [y] * len(at), status)
                    shown[status] = shown.get(status, 0) + len(at)
            if y and run.scenario != runs[y - 1].scenario:
                ax.axhline(y - 0.5, color=GRID, linewidth=0.8)
        ax.set_title(MODE_LABELS[mode])
        ax.set_xlim(0, max(run.end_s for run in runs))
        ax.set_xlabel("Time into the run (s)")
    axes[0].set_yticks(range(len(labels)), labels)
    axes[0].set_ylabel("Run (scenario, seed)")
    axes[0].invert_yaxis()
    handles: list[Artist] = [_fate_handle(s, shown[s]) for s in FATES if s in shown]
    handles.append(Line2D([], [], color=MUTED, linewidth=1.2, label="Onset $t_d$"))
    _legend(fig, handles, below=True, rows=2)
    return fig


def figure_prediction(ev: Evidence) -> Figure:
    """The change in throughput the twin predicted against the change the watch measured, for
    every resolved action, by its fate (symmetric log axes)."""
    points = throughput_changes(ev)
    fig = _figure(COLUMN_IN, 2.55)
    ax = fig.subplots()
    _style(ax, grid="both")
    for status in RESOLVED:
        mine = [(x, y) for x, y, s in points if s == status]
        if mine:
            _fate_marker(ax, [x for x, _ in mine], [y for _, y in mine], status)
    ax.set_xscale("symlog", linthresh=SYMLOG_LINEAR_PCT)
    ax.set_yscale("symlog", linthresh=SYMLOG_LINEAR_PCT)
    xlim = _symlog_limits([x for x, _, _ in points])
    ylim = _symlog_limits([y for _, y, _ in points])
    diagonal = (max(xlim[0], ylim[0]), min(xlim[1], ylim[1]))
    ax.plot(diagonal, diagonal, color=MUTED, linestyle="--", linewidth=0.6)
    ax.annotate(
        "measured = predicted",
        (diagonal[1], diagonal[1]),
        xytext=(-2, -2),
        textcoords="offset points",
        ha="right",
        va="top",
        fontsize=6,
        color=MUTED,
    )
    ax.axhline(0, color=INK, linewidth=0.5)
    ax.axvline(0, color=INK, linewidth=0.5)
    ax.set(xlim=xlim, ylim=ylim)
    ax.set_xlabel("Throughput change predicted by the twin (%)")
    ax.set_ylabel("Throughput change measured (%)")
    counts = {s: sum(p[2] == s for p in points) for s in RESOLVED}
    _legend(fig, [_fate_handle(s, n) for s, n in counts.items() if n])
    return fig


def figure_live_error(ev: Evidence) -> Figure:
    """The distribution of the closed-loop relative error per KPI: the twin's prediction and its
    no-action baseline ("nothing changes") against what the watch measured."""
    resolved = resolved_actions(ev)
    fig = _figure(COLUMN_IN, 1.6)
    axes = fig.subplots(1, len(LIVE_TITLES), sharey=True)
    for ax, kpi in zip(axes, LIVE_TITLES, strict=True):
        _style(ax, grid="both")
        twin, unchanged = live_errors(resolved, kpi)
        for errors, colour, style, label in (
            (twin, METHOD, "-", "Twin's prediction"),
            (unchanged, BASELINE, "--", "Nothing changes"),
        ):
            if errors:
                xs, ys = ecdf([max(e, ERROR_FLOOR_PCT) for e in errors])
                ax.step(xs, ys, style, where="post", color=colour, lw=1.0, label=label)
        ax.axhline(0.5, color=MUTED, linestyle=":", linewidth=0.6)
        ax.set_xscale("log")
        ax.set_title(LIVE_TITLES[kpi])
        ax.set_xlabel("Error (%)")
    axes[0].set_ylabel("Share of actions")
    axes[0].set_ylim(0, 1.02)
    _legend(fig, _handles(axes[0]))
    return fig


def figure_twin(ev: Evidence) -> Figure:
    """The twin offline and in the loop: its per-flow throughput error on the held-out test split
    by case and traffic class, and the time each of its predictions took in the campaign."""
    test = ev.twin["after_calibration"]["test"]
    cases = sorted(
        ((*k.split("/"), v) for k, v in test.items() if k != "all"),
        key=lambda c: (c[1] != "video", -c[2]["mape"]),
    )
    sim_ms = prediction_times(ev)
    fig = _figure(COLUMN_IN, 2.9)
    bars, times = fig.subplots(2, 1, height_ratios=[2.3, 1])
    _style(bars, grid="x")
    for y, (_, app, row) in enumerate(cases):
        colour, hatch = BAR_STYLES["method" if app == "video" else "second"]
        bars.barh(y, row["mape"] * 100, 0.7, color=colour, hatch=hatch)
        label = f" {row['mape'] * 100:.1f}% (n={row['n']})"
        bars.text(row["mape"] * 100, y, label, va="center", fontsize=5.5)
    bars.set_yticks(range(len(cases)), [CASE_WORDS.get(k, k.replace("_", " ")) for k, *_ in cases])
    bars.invert_yaxis()
    bars.set_xlabel("Per-flow throughput error, MAPE (%)")
    bars.set_xlim(0, 1.45 * max((c[2]["mape"] * 100 for c in cases), default=1.0))
    styles = [("video", BAR_STYLES["method"]), ("bulk", BAR_STYLES["second"])]
    bars.legend(
        handles=[Patch(facecolor=c, hatch=h, label=app) for app, (c, h) in styles],
        loc="upper right",
        frameon=False,
    )
    _style(times, grid="both")
    if sim_ms:
        xs, ys = ecdf(sim_ms)
        times.step(xs, ys, where="post", color=METHOD, linewidth=1.0)
        median = statistics.median(sim_ms)
        times.axvline(median, color=MUTED, linestyle=":", linewidth=0.8)
        times.text(median, 0.08, f" median {median:.2f} ms", fontsize=6, color=INK)
    times.set_xlabel(f"Twin prediction time (ms), {len(sim_ms)} verdicts")
    times.set_ylabel("Share")
    times.set_ylim(0, 1.02)
    return fig


# ---------------------------------------------------------------- LLM, detection, forecasting


def figure_intents(ev: Evidence) -> Figure:
    """The intent evaluation: intents translated correctly per model and kind of intent, and the
    time each intent took (dots, with the median as a bar)."""
    results = intent_results(ev)
    styles = dict(zip(results, (BAR_STYLES["method"], BAR_STYLES["second"]), strict=True))
    kinds = list(intent_kinds(ev))
    fig = _figure(COLUMN_IN, 1.8)
    acc_ax, time_ax = fig.subplots(1, 2, width_ratios=[1.25, 1])
    _style(acc_ax)
    _style(time_ax)
    width = 0.8 / len(results)
    for m, (model, (accuracy, seconds)) in enumerate(results.items()):
        colour, hatch = styles[model]
        for k, kind in enumerate(kinds):
            correct, total = accuracy[kind]
            x = k + _offset(m, len(results), width)
            acc_ax.bar(x, total, width * 0.9, facecolor="none", edgecolor=GRID, lw=0.8)
            acc_ax.bar(x, correct, width * 0.9, color=colour, hatch=hatch)
            acc_ax.text(x, total, f"{correct}/{total}", ha="center", va="bottom", fontsize=5.5)
        jitter = [((i % 7) - 3) * 0.045 for i in range(len(seconds))]
        time_ax.scatter([m + j for j in jitter], seconds, s=5, c=colour, alpha=0.8)
        median = statistics.median(seconds)
        time_ax.plot([m - 0.25, m + 0.25], [median, median], color=INK, linewidth=1.0)
    acc_ax.set_xticks(range(len(kinds)), kinds)
    acc_ax.set_ylabel("Intents translated correctly")
    totals = [total for accuracy, _ in results.values() for _, total in accuracy.values()]
    acc_ax.set_ylim(0, max(totals) * 1.25)
    time_ax.set_xticks(range(len(results)), [m.replace(":", ":\n", 1) for m in results])
    time_ax.set_ylabel("Seconds per intent")
    time_ax.set_ylim(0, None)
    time_ax.set_xlim(-0.6, len(results) - 0.4)
    _legend(fig, [Patch(facecolor=c, hatch=h, label=m) for m, (c, h) in styles.items()])
    return fig


def figure_anomaly(ev: Evidence) -> Figure:
    """The Isolation Forest on the test split: precision and recall per disruption scenario, and
    how long after the disruption its first alert came (with the false alarms before it)."""
    by_scenario = ev.anomaly["test_by_scenario"]
    scenarios = [s for s in SCENARIOS if s in by_scenario]
    detection = detections(ev)
    fig = _figure(COLUMN_IN, 1.6)
    score_ax, delay_ax = fig.subplots(1, 2, sharey=True)
    _style(score_ax, grid="x")
    _grouped_barh(
        score_ax,
        scenarios,
        [
            ("Precision", [by_scenario[s]["precision"] for s in scenarios], "method"),
            ("Recall", [by_scenario[s]["recall"] for s in scenarios], "second"),
        ],
    )
    score_ax.set_xlim(0, 1.0)
    score_ax.set_xlabel("Score on the test split")
    _style(delay_ax, grid="x")
    for y, s in enumerate(scenarios):
        if s in detection:
            delay, early = detection[s]["delay_s"], detection[s].get("false_alarms_before")
            delay_ax.barh(y, delay, 0.5, color=METHOD)
            note = f" {delay:.0f} s" + (f"; {early} false\n alarms before $t_d$" if early else "")
            delay_ax.text(delay, y, note, va="center", fontsize=5.5)
    delay_ax.set_xlabel("First alert after $t_d$ (s)")
    delay_ax.set_xlim(0, 2.2 * max((d["delay_s"] for d in detection.values()), default=1.0))
    _legend(fig, _handles(score_ax))
    return fig


def figure_forecast(ev: Evidence) -> Figure:
    """Forecasting AP utilisation on the test split: the RMSE of Holt's method and of the moving
    average per scenario, at each forecast horizon."""
    by_scenario = ev.forecast["test_by_scenario"]
    scenarios = _scenario_order(list(by_scenario))
    methods = (
        ("holt", "Holt's linear trend", "method"),
        ("moving_average", "Moving average", "baseline"),
    )
    horizons = ev.forecast["config"]["horizons_s"]
    fig = _figure(COLUMN_IN, 1.75)
    axes = fig.subplots(1, len(horizons), sharey=True, sharex=True)
    for ax, horizon in zip(axes, horizons, strict=True):
        _style(ax, grid="x")
        _grouped_barh(
            ax,
            scenarios,
            [
                (label, [by_scenario[s][key][f"rmse_{horizon}s"] for s in scenarios], role)
                for key, label, role in methods
            ],
        )
        ax.set_title(f"{horizon} s ahead")
        ax.set_xlabel("RMSE of utilization")
    _legend(fig, _handles(axes[0]))
    return fig


FIGURES: dict[str, Callable[[Evidence, Path], None]] = {  # file -> drawing, in the paper's order
    "fig_campus.pdf": _to_pdf(figure_campus),
    "fig_model.pdf": _to_pdf(figure_model),
    "fig_kpis.pdf": _to_pdf(figure_kpis),
    "fig_recovery.pdf": _to_pdf(figure_recovery),
    "fig_utilisation.pdf": _to_pdf(figure_utilisation),
    "fig_latency.pdf": _to_pdf(figure_latency),
    "fig_loss.pdf": _to_pdf(figure_loss),
    "fig_fairness.pdf": _to_pdf(figure_fairness),
    "fig_clients.pdf": _to_pdf(figure_clients),
    "fig_timeline.pdf": _to_pdf(figure_timeline),
    "fig_prediction.pdf": _to_pdf(figure_prediction),
    "fig_live_error.pdf": _to_pdf(figure_live_error),
    "fig_twin.pdf": _to_pdf(figure_twin),
    "fig_intents.pdf": _to_pdf(figure_intents),
    "fig_anomaly.pdf": _to_pdf(figure_anomaly),
    "fig_forecast.pdf": _to_pdf(figure_forecast),
}
