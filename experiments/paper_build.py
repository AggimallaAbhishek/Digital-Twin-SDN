"""The IEEE conference paper (final_submission/paper/): its numbers, tables and figures, generated
from the recorded evaluation, so that no result in the paper is typed by hand.

    make paper            # generated/ + figures/ from the evaluation, then paper.pdf (Tectonic)
    make paper-check      # fail if generated/ is out of date with the evaluation

`main.tex` takes every result from `generated/numbers.tex` (one `\\newcommand` per number) and
`generated/table_*.tex`, and the three figures from `figures/*.pdf`. They are rebuilt from:

- `experiments/results/results.json` (`make results`): the KPI table, H1, fairness, H2 counts;
- the executor ledgers of the 27 campaign runs (`data/raw/eval<mode>-v1/<run>/actions.db`,
  opened read-only): what became of every action, and the twin's prediction time;
- `models/{twin,anomaly,forecast,genai}/v1/*.json` and `experiments/results/intents*.json`;
- the configuration files and constants the method section quotes (config/*.yaml, the verifier).
"""

from __future__ import annotations

import argparse
import contextlib
import json
import logging
import statistics
import subprocess
from collections import Counter
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import matplotlib
import yaml
from matplotlib.axes import Axes
from matplotlib.figure import Figure

from common.schemas import MAX_STEER_FRACTION, MIN_TARGET_RSSI_DBM
from controller.executor.ledger import ActionRecord, read_records
from experiments.analysis.figures import GRID, MODE_COLOURS, SURFACE, error_bar
from experiments.batch import LOOP_MODES, run_ok
from experiments.shell import run
from twin.verify.verifier import CHANGE_PCT, TX_POWER_MAX_STEP_DB

log = logging.getLogger("experiments.paper_build")
ROOT = Path(__file__).resolve().parents[1]
PAPER = ROOT / "final_submission" / "paper"
GENERATED, FIGURES = PAPER / "generated", PAPER / "figures"
TEX_TIMEOUT_S = 600.0  # Tectonic fetches its bundle on the first run

SCENARIOS = {  # scenario -> (macro word, title)
    "lecture_flash_crowd": ("Flash", "Lecture flash crowd"),
    "ap_failure": ("ApFail", "AP failure"),
    "cochannel_interference": ("Cochan", "Co-channel interference"),
}
MODE_WORDS = {"V1": "Vone", "V2": "Vtwo", "V3": "Vthree"}  # LaTeX names have no digits
MODE_LABELS = {"V1": "V1 plain SDN", "V2": "V2 no twin", "V3": "V3 full"}
KPIS = {  # kpi -> (macro word, decimals, heading)
    "ttr_s": ("Ttr", 0, "Recovery (s)"),
    "throughput_mbps": ("Thr", 2, "Thr. (Mbit/s)"),
    "latency_p95_ms": ("Lat", 0, "p95 lat. (ms)"),
    "loss_pct": ("Loss", 1, "Loss (\\%)"),
    "jain": ("Jain", 2, "Jain"),
}
SAFETY_KEYS = {
    "recorded": "Recorded",
    "applied": "Applied",
    "applied_twin_rejected": "AppliedTwinRejected",
    "harmful_twin_rejected": "HarmfulTwinRejected",
    "slipped_past_twin": "SlippedPastTwin",
    "rollback_failed": "RollbackFailed",
    "high_impact_unapproved": "HighImpactUnapproved",
    "unresolved": "Unresolved",
}
STATUS_WORDS = {  # ledger status -> macro word and table heading
    "kept": ("Kept", "Kept"),
    "rolled_back": ("RolledBack", "Rolled back"),
    "rollback_failed": ("RollbackFailed", "Rollback failed"),
    "applied": ("Watched", "Still watched"),
    "rejected": ("Rejected", "Rejected by the twin"),
    "verified": ("Waiting", "Awaiting an operator"),
}
Json = dict[str, Any]  # Any: JSON


@dataclass(frozen=True)
class Evidence:
    """Everything the paper's numbers come from (see the module docstring)."""

    results: Json
    twin: Json
    anomaly: Json
    forecast: Json
    genai: Json
    intents: Json
    intents_local: Json
    ledgers: Mapping[str, Mapping[str, Sequence[ActionRecord]]]  # mode -> passed run -> actions
    config: Mapping[str, Json]  # config/<name>.yaml

    def actions(self, mode: str) -> list[ActionRecord]:
        """Every action of the passed runs of one variant."""
        return [r for records in self.ledgers[mode].values() for r in records]


def _load(path: Path) -> Json:
    data: Json = json.loads(path.read_text())
    return data


def passed_runs(raw: Path) -> list[str]:
    """The run folders of a raw campaign (data/raw/eval<mode>-v1) that gave usable data: the
    same rule as the results tables (experiments/batch.py run_ok)."""
    batch = _load(raw / "batch.json")
    return [r["run_id"] for r in batch["runs"] if run_ok(r)]


def load_evidence(root: Path = ROOT) -> Evidence:
    """Read the recorded evaluation under `root` (a missing file is an error: say which)."""
    results = root / "experiments" / "results"
    models = root / "models"
    ledgers = {}
    for mode in LOOP_MODES:
        raw = root / "data" / "raw" / f"eval{mode.lower()}-v1"
        ledgers[mode] = {
            run_id: read_records(raw / run_id / "actions.db")
            for run_id in passed_runs(raw)
            if (raw / run_id / "actions.db").exists()
        }
    return Evidence(
        results=_load(results / "results.json"),
        twin=_load(models / "twin" / "v1" / "validation.json"),
        anomaly=_load(models / "anomaly" / "v1" / "metrics.json"),
        forecast=_load(models / "forecast" / "v1" / "metrics.json"),
        genai=_load(models / "genai" / "v1" / "live.json"),
        intents=_load(results / "intents.json"),
        intents_local=_load(results / "intents_local.json"),
        ledgers=ledgers,
        config={
            name: yaml.safe_load((root / "config" / f"{name}.yaml").read_text())
            for name in ("sim", "optimizer", "loop", "executor", "campus_v1", "anomaly")
        },
    )


# ---------------------------------------------------------------- numbers


def kpi_cells(ev: Evidence) -> dict[tuple[str, str, str], Json]:
    """The results table by (variant, scenario, KPI)."""
    return {(r["mode"], r["scenario"], r["kpi"]): r for r in ev.results["table"]}


def _f(value: float, decimals: int) -> str:
    return f"{value:.{decimals}f}"


def status_counts(records: Sequence[ActionRecord]) -> Counter[str]:
    """How many actions ended in each ledger status."""
    return Counter(r.status for r in records)


def numbers(ev: Evidence) -> dict[str, str]:
    """Every number the paper's text quotes, by LaTeX macro name (letters only)."""
    out: dict[str, str] = {}
    res = ev.results
    out["NumRuns"] = str(sum(len(runs) for runs in res["runs"].values()))
    for (mode, scenario, kpi), row in kpi_cells(ev).items():
        word, decimals, _ = KPIS[kpi]
        name = f"{SCENARIOS[scenario][0]}{{}}{MODE_WORDS[mode]}"
        out["Kpi" + name.format(word)] = _f(row["mean"], decimals)
        if kpi == "ttr_s":  # runs of the three that never recovered
            out["Never" + name.format("")] = str(row["never"])
    for scenario, h1 in res["h1"].items():
        word = SCENARIOS[scenario][0]
        out[f"HoneFaster{word}"] = _f(h1["faster_pct"], 0)
        out[f"HoneVerdict{word}"] = h1["verdict"]
    for mode, fair in res["fairness"].items():
        out[f"FairJain{MODE_WORDS[mode]}"] = _f(fair["jain"], 2)
    for mode, safety in res["safety"].items():
        for key, word in SAFETY_KEYS.items():
            out[f"Safe{MODE_WORDS[mode]}{word}"] = str(safety[key])
    for mode in LOOP_MODES:
        records = ev.actions(mode)
        counts = status_counts(records)
        out[f"Led{MODE_WORDS[mode]}Proposed"] = str(len(records))
        for status, (word, _) in STATUS_WORDS.items():
            out[f"Led{MODE_WORDS[mode]}{word}"] = str(counts[status])
    sim_ms = [r.verdict.sim_time_ms for mode in LOOP_MODES for r in ev.actions(mode)]
    out["SimMedianMs"] = _f(statistics.median(sim_ms), 2) if sim_ms else "0"
    out |= _failed_rollbacks(ev)
    return out | _model_numbers(ev) | _config_numbers(ev)


def _failed_rollbacks(ev: Evidence) -> dict[str, str]:
    """How many rollbacks failed, and how many of those were in the AP-failure scenario (a run
    id starts with its scenario)."""
    failed = Counter(
        run_id.startswith("ap_failure")
        for runs in ev.ledgers.values()
        for run_id, records in runs.items()
        for r in records
        if r.status == "rollback_failed"
    )
    return {"RbFailAll": str(failed.total()), "RbFailApFail": str(failed[True])}


def _model_numbers(ev: Evidence) -> dict[str, str]:
    test = ev.twin["after_calibration"]["test"]
    bulk = [v["mape"] for k, v in test.items() if k.endswith("/bulk")]
    ano, fc = ev.anomaly, ev.forecast["metrics"]["test"]
    detect = ano["test_detection"]
    return {
        "TwinMape": _f(100 * test["all"]["mape"], 1),
        "TwinN": str(test["all"]["n"]),
        "TwinSteadyVideo": _f(100 * test["steady/video"]["mape"], 1),
        "TwinSteer": _f(100 * test["steer_clients/video"]["mape"], 1),
        "TwinChannel": _f(100 * test["set_ap_channel/video"]["mape"], 1),
        "TwinChannelN": str(test["set_ap_channel/video"]["n"]),
        "TwinSteadyN": str(test["steady/video"]["n"]),
        "TwinBulkLow": _f(100 * min(bulk), 0),
        "TwinBulkHigh": _f(100 * max(bulk), 0),
        "AnoPrecision": _f(ano["test"]["precision"], 3),
        "AnoRecall": _f(ano["test"]["recall"], 3),
        "AnoF": _f(ano["test"]["f1"], 3),
        "AnoDelayFail": _f(detect["ap_failure-s44"]["delay_s"], 0),
        "AnoDelayCochan": _f(detect["cochannel_interference-s44"]["delay_s"], 0),
        "FcHoltOne": _f(fc["holt"]["rmse_60s"], 3),
        "FcMaOne": _f(fc["moving_average"]["rmse_60s"], 3),
        "FcHoltThree": _f(fc["holt"]["rmse_180s"], 3),
        "FcMaThree": _f(fc["moving_average"]["rmse_180s"], 3),
        "IntCases": str(ev.intents["cases"]),
        "IntCloudOk": str(ev.intents["correct"]),
        "IntLocalOk": str(ev.intents_local["correct"]),
        "IntCloudSeconds": _f(statistics.median(ev.intents["seconds"]), 1),
        "IntLocalSeconds": _f(statistics.median(ev.intents_local["seconds"]), 1),
        "GenCopilotOk": str(ev.genai["summary"]["copilot_correct"]),
        "GenCopilotN": str(ev.genai["summary"]["copilot_questions"]),
        "GenRcaOk": str(ev.genai["summary"]["rca_correct"]),
        "GenRcaN": str(ev.genai["summary"]["rca_alerts"]),
        "GenActions": str(ev.genai["summary"]["llm_actions"]),
        "GenActionsVerdict": str(ev.genai["summary"]["llm_actions_with_verdict_in_audit_log"]),
    }


def _config_numbers(ev: Evidence) -> dict[str, str]:
    cfg = ev.config
    radio = cfg["campus_v1"]["radio_model"]
    return {
        "CfgCapacity": _f(radio["ap_capacity_mbps"], 1),
        "CfgStationSeed": str(cfg["campus_v1"]["stations"]["seed"]),
        "CfgForestSeed": str(cfg["anomaly"]["seed"]),
        "CfgCochanFull": _f(radio["cochannel_full_m"], 0),
        "CfgCochanZero": _f(radio["cochannel_zero_m"], 0),
        "CfgQueueSlots": str(cfg["sim"]["queue_slots"]),
        "CfgBaseLatency": _f(cfg["sim"]["base_latency_ms"], 1),
        "CfgServiceMs": _f(cfg["sim"]["service_ms"], 1),
        "CfgUtilHigh": _f(cfg["optimizer"]["util_high"], 1),
        "CfgUtilTarget": _f(cfg["optimizer"]["util_target"], 1),
        "CfgMaxSteerPct": _f(100 * MAX_STEER_FRACTION, 0),
        "CfgMinRssi": _f(MIN_TARGET_RSSI_DBM, 0),
        "CfgTxStep": _f(TX_POWER_MAX_STEP_DB, 0),
        "CfgChangePct": _f(CHANGE_PCT, 0),
        "CfgPeriod": str(cfg["loop"]["period_s"]),
        "CfgWatch": str(cfg["executor"]["watch_s"]),
        "CfgSettle": str(cfg["executor"]["settle_s"]),
        "CfgRegressPct": str(cfg["executor"]["regression_pct"]),
        "CfgHighImpactGap": str(cfg["executor"]["high_impact_per_ap_s"]),
        "CfgMaxActions": str(cfg["executor"]["max_actions_per_loop"]),
    }


def _tex(value: str) -> str:
    """`value` as LaTeX text: the characters TeX reads as commands are escaped."""
    return "".join(f"\\{c}" if c in "&%$#_{}" else c for c in value)


def render_numbers(values: Mapping[str, str]) -> str:
    """generated/numbers.tex: one \\newcommand per number."""
    lines = [f"\\newcommand{{\\{name}}}{{{_tex(value)}}}" for name, value in sorted(values.items())]
    return (
        "% Generated by experiments/paper_build.py from the recorded evaluation. Do not edit.\n"
        + ("\n".join(lines) + "\n")
    )


# ---------------------------------------------------------------- tables


def _pm(row: Mapping[str, Any], decimals: int) -> str:
    return f"{_f(row['mean'], decimals)} $\\pm$ {_f(row['ci95'], decimals)}"


def table_kpis(ev: Evidence) -> str:
    """The KPI table: mean ± 95% interval per scenario and variant (tabular only)."""
    cells = kpi_cells(ev)
    head = " & ".join(["Scenario", "Variant", *(k[2] for k in KPIS.values())])
    lines = ["\\begin{tabular}{@{}llccccc@{}}", "\\toprule", f"{head} \\\\", "\\midrule"]
    for si, (scenario, (_, title)) in enumerate(SCENARIOS.items()):
        for mi, mode in enumerate(LOOP_MODES):
            row = [title if mi == 0 else "", MODE_LABELS[mode]]
            for kpi, (_, decimals, _) in KPIS.items():
                cell = cells[(mode, scenario, kpi)]
                text = _pm(cell, decimals)
                if kpi == "ttr_s" and cell["never"]:  # a mean that includes runs never recovered
                    text = f"$\\geq$ {text} ({cell['never']})"
                row.append(text)
            lines.append(" & ".join(row) + " \\\\")
        if si < len(SCENARIOS) - 1:
            lines.append("\\addlinespace")
    return "\n".join([*lines, "\\bottomrule", "\\end{tabular}"]) + "\n"


def table_actions(ev: Evidence) -> str:
    """What became of every action, from the executor ledgers: one row per fate, one column per
    variant (tabular only)."""
    counts = {mode: status_counts(ev.actions(mode)) for mode in LOOP_MODES}
    lines = [
        "\\begin{tabular}{@{}lrrr@{}}",
        "\\toprule",
        " & ".join(["Actions", *LOOP_MODES]) + " \\\\",
        "\\midrule",
        " & ".join(["Proposed", *(str(sum(counts[m].values())) for m in LOOP_MODES)]) + " \\\\",
    ]
    for status, (_, heading) in STATUS_WORDS.items():
        lines.append(" & ".join([heading, *(str(counts[m][status]) for m in LOOP_MODES)]) + " \\\\")
    return "\n".join([*lines, "\\bottomrule", "\\end{tabular}"]) + "\n"


# ---------------------------------------------------------------- figures


@contextlib.contextmanager
def _pdf_style() -> Iterator[None]:
    """IEEE-ready PDF text (embedded TrueType, no Type 3) for the figures drawn inside."""
    with matplotlib.rc_context():  # restores the settings on exit
        params = matplotlib.rcParams
        params["pdf.fonttype"] = 42
        params["font.family"] = "serif"
        params["font.size"] = 7
        params["axes.linewidth"] = 0.6
        yield


def _style(ax: Axes) -> None:
    ax.set_facecolor(SURFACE)
    ax.grid(axis="y", color=GRID, linewidth=0.5)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.tick_params(length=2, width=0.5)


def figure_kpis(ev: Evidence, path: Path) -> None:
    """Fig. 2: loss and throughput of the affected flows, per scenario and variant (PDF)."""
    cells = kpi_cells(ev)
    rows = (("loss_pct", "Loss (%)"), ("throughput_mbps", "Throughput (Mbit/s)"))
    with _pdf_style():
        fig = Figure(figsize=(7.16, 2.5), facecolor=SURFACE, layout="constrained")
        grid = fig.subplots(len(rows), len(SCENARIOS), sharex=True)
        for r, (kpi, label) in enumerate(rows):
            for c, (scenario, (_, title)) in enumerate(SCENARIOS.items()):
                ax = grid[r][c]
                _style(ax)
                for i, mode in enumerate(LOOP_MODES):
                    cell = cells[(mode, scenario, kpi)]
                    low, up = error_bar(kpi, cell)  # clipped to what the KPI can be
                    ax.bar(
                        i,
                        cell["mean"],
                        0.62,
                        color=MODE_COLOURS[mode],
                        yerr=[[low], [up]],
                        error_kw={"linewidth": 0.7, "capsize": 2},
                    )
                    ax.annotate(  # the value above the interval: the colours alone do not say it
                        _f(cell["mean"], KPIS[kpi][1]),
                        (i, cell["mean"] + up),
                        xytext=(0, 2),
                        textcoords="offset points",
                        ha="center",
                        va="bottom",
                        fontsize=6,
                    )
                if r == 0:
                    ax.set_title(title, fontsize=7)
                if c == 0:
                    ax.set_ylabel(label)
                ax.set_xticks(range(len(LOOP_MODES)), list(LOOP_MODES))
        fig.savefig(path, format="pdf")


def figure_recovery(ev: Evidence, path: Path) -> None:
    """Fig. 3: time to recover of every run; a hollow triangle is a run that never recovered
    (counted at its run end) (PDF)."""
    runs = ev.results["runs"]
    with _pdf_style():
        fig = Figure(figsize=(3.45, 2.2), facecolor=SURFACE, layout="constrained")
        ax = fig.subplots()
        _style(ax)
        ticks = [si * 4 + mi for si in range(len(SCENARIOS)) for mi in range(len(LOOP_MODES))]
        for si, scenario in enumerate(SCENARIOS):
            for mi, mode in enumerate(LOOP_MODES):
                x = si * 4 + mi
                for k, run in enumerate(runs[f"{mode}/{scenario}"]):
                    xs = x + (k - 1) * 0.16
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
                        ax.plot(xs, run["ttr_s"], "o", color=MODE_COLOURS[mode], ms=4)
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
        fig.savefig(path, format="pdf")


# ---------------------------------------------------------------- build


def build_generated(ev: Evidence, out: Path) -> list[Path]:
    """Write numbers.tex, the tables and the figures under `out`; the files written."""
    gen, figs = out / "generated", out / "figures"
    gen.mkdir(parents=True, exist_ok=True)
    figs.mkdir(parents=True, exist_ok=True)
    files = {gen / name: text for name, text in texts(ev).items()}
    for path, text in files.items():
        path.write_text(text)
    plots: dict[Path, Callable[[Evidence, Path], None]] = {
        figs / "fig_kpis.pdf": figure_kpis,
        figs / "fig_recovery.pdf": figure_recovery,
    }
    for path, draw in plots.items():
        draw(ev, path)
    return [*files, *plots]


def texts(ev: Evidence) -> dict[str, str]:
    """The generated LaTeX files by name: what the evaluation gives now."""
    return {
        "numbers.tex": render_numbers(numbers(ev)),
        "table_kpis.tex": table_kpis(ev),
        "table_actions.tex": table_actions(ev),
    }


def out_of_date(ev: Evidence, out: Path) -> list[str]:
    """The generated text files under `out` that differ from what the evaluation gives now."""
    gen = out / "generated"
    return [
        name
        for name, text in texts(ev).items()
        if not (gen / name).exists() or (gen / name).read_text() != text
    ]


def compile_pdf(paper: Path = PAPER) -> Path:
    """main.tex -> main.pdf with Tectonic (the page count of the IEEE paper is checked by
    the caller). Returns the PDF's path."""
    run(["tectonic", "--keep-logs", "main.tex"], cwd=paper, check=True, timeout=TEX_TIMEOUT_S)
    return paper / "main.pdf"


def main(argv: list[str] | None = None) -> int:
    """`make paper` / `make paper-check`."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="only report out-of-date files")
    parser.add_argument("--no-pdf", action="store_true", help="skip compiling main.tex")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        ev = load_evidence()
    except FileNotFoundError as exc:  # a part of the recorded evaluation is not there
        log.error("the recorded evaluation is incomplete: %s", exc)
        return 1
    if args.check:
        stale = out_of_date(ev, PAPER)
        if stale:
            log.error("out of date with the evaluation: %s (run `make paper`)", ", ".join(stale))
        return 1 if stale else 0
    for path in build_generated(ev, PAPER):
        log.info("wrote %s", path.relative_to(ROOT))
    if not args.no_pdf:
        try:
            log.info("wrote %s", compile_pdf().relative_to(ROOT))
        except (OSError, subprocess.SubprocessError) as exc:
            log.error("could not compile main.tex: %s", exc)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
