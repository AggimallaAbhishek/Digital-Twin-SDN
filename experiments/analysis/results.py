"""P6.5 / P6.6 every evaluation number from the data, by one command (decision P6.6-A).

    make results     # -> experiments/results/{results.json, results.md, figures/*.png}

- H1 and the §5.1 KPIs: per mode (V1/V2/V3) and scenario, mean ± 95% CI over the seeds of the
  campaign datasets (data/evalv1-v1, evalv2-v1, evalv3-v1; --v1/--v2/--v3 point elsewhere);
- H2 and the §5.3 safety counts: the executor ledgers of the raw runs (twin_blocking.py);
- §5.4: LLM latency from logs/llm_calls.jsonl, intent accuracy from experiments/results/
  intents.json (`make intent-eval`; this script never calls an LLM).

A mode whose dataset is missing is left out and named in the output.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from common.schemas import Scenario
from controller.executor.ledger import read_records
from experiments.analysis.campaign import KPI_TITLES, RunKpis, StressWindow, run_kpis, summarise
from experiments.analysis.figures import kpi_figure
from experiments.analysis.llm_latency import genai_numbers
from experiments.analysis.twin_blocking import audit
from experiments.batch import LOOP_MODES, load_scenario, run_ok
from experiments.dataset import disruption
from experiments.shell import git_commit

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "experiments" / "results"
SCENARIOS = ("lecture_flash_crowd", "ap_failure", "cochannel_interference")
MODES = LOOP_MODES
KPIS = tuple(KPI_TITLES)
H1_TARGET_PCT = 30.0  # V3 recovers >= 30% faster than V1 (problem statement §5.1)
JAIN_TARGET = 0.8  # during the flash crowd (problem statement §5.1)
TWIN_VALIDATION = ROOT / "models" / "twin" / "v1" / "validation.json"  # P3.5
INTENT_EVALS = {"intents": "", "intents_local": "_local"}  # make intent-eval: name -> suffix
COLUMNS = {
    "ap_stats": ["run_id", "scenario_id", "t_s", "ap", "channel_util", "n_clients"],
    "sta_stats": ["run_id", "t_s", "sta", "ap"],
    "kpi": ["run_id", "t_s", "flow_id", "app_class", "throughput_mbps", "latency_ms", "loss_pct"],
}
Row = dict[str, Any]  # Any: JSON values
Runs = Mapping[tuple[str, str], Sequence[RunKpis]]  # (mode, scenario) -> one entry per seed


def kpi_table(runs: Runs) -> list[Row]:
    """One row per mode, scenario and KPI: mean, ci95, n, and how many runs never recovered
    (counted at their run end, so the time-to-recover mean is then a lower bound)."""
    rows = []
    for (mode, scenario), kpis in runs.items():
        for kpi in KPIS:
            if kpi == "ttr_s":
                values = [k.ttr_s if k.ttr_s is not None else k.censor_s for k in kpis]
                never = sum(k.ttr_s is None for k in kpis)
            else:
                values = [v for k in kpis if (v := getattr(k, kpi)) is not None]
                never = 0
            s = summarise(values)
            rows.append(
                {"mode": mode, "scenario": scenario, "kpi": kpi}
                | {"mean": s.mean, "ci95": s.ci95, "n": s.n, "never": never}
            )
    return rows


def h1(table: Sequence[Row]) -> dict[str, Row]:
    """Per scenario with V1 and V3 runs: how much faster V3 recovers, against the 30% target."""
    ttr = {(r["mode"], r["scenario"]): r for r in table if r["kpi"] == "ttr_s"}
    out = {}
    for scenario in SCENARIOS:
        v1, v3 = ttr.get(("V1", scenario)), ttr.get(("V3", scenario))
        if v1 is None or v3 is None:
            continue
        faster = 100.0 * (v1["mean"] - v3["mean"]) / v1["mean"] if v1["mean"] > 0 else None
        out[scenario] = {
            "v1_s": v1["mean"],
            "v3_s": v3["mean"],
            "faster_pct": faster,
            "verdict": _h1_verdict(faster, v1["never"], v3["never"]),
            "v1_never": v1["never"],
            "v3_never": v3["never"],
        }
    return out


def _h1_verdict(faster: float | None, v1_never: int, v3_never: int) -> str:
    """met / not met / inconclusive. A run that never recovered counts at its run end, so V1's
    make the shown speed-up a lower bound (a "met" holds) and V3's an upper bound (a "not met"
    holds); otherwise the censored runs could change the answer."""
    if faster is None:
        return "inconclusive"
    met = faster >= H1_TARGET_PCT
    if (v1_never and v3_never) or (v1_never and not met) or (v3_never and met):
        return "inconclusive"
    return "met" if met else "not met"


def load_runs(dataset: Path, mode: str) -> dict[tuple[str, str], list[RunKpis]]:
    """The KPIs of every evaluation run of one mode's dataset."""
    tables: dict[str, dict[str, list[Row]]] = defaultdict(lambda: defaultdict(list))
    only = [("scenario_id", "in", list(SCENARIOS))]
    for name, cols in COLUMNS.items():
        for row in pq.read_table(
            dataset / f"{name}.parquet", columns=cols, filters=only
        ).to_pylist():
            tables[row["run_id"]][name].append(row)
    windows = {s: stress_window(load_scenario(s)) for s in SCENARIOS}
    runs: dict[tuple[str, str], list[RunKpis]] = defaultdict(list)
    for _, t in sorted(tables.items()):
        scenario = t["ap_stats"][0]["scenario_id"]
        kpis = run_kpis(t["ap_stats"], t["sta_stats"], t["kpi"], windows[scenario])
        runs[(mode, scenario)].append(kpis)
    return runs


def stress_window(scenario: Scenario) -> StressWindow:
    """The scenario's stress window and the AP its scripted event names (decision P6.6-A)."""
    onset = disruption(scenario)
    if onset is None:
        raise ValueError(f"{scenario.scenario_id} has no disruption: no stress window")
    event_ap = scenario.events[0].ap if scenario.events else None
    return StressWindow(onset.at_s, float(scenario.duration_s), event_ap)


def ledger_counts(raw: Path) -> dict[str, float]:
    """The H2 / safety counts summed over the ledgers of a raw campaign folder's passed runs (the
    runs the KPI tables use), with the harmful share of applied actions (§5.3: count and %).
    Read-only: the raw ledgers are evidence."""
    batch = json.loads((raw / "batch.json").read_text())
    passed = [r["run_id"] for r in batch["runs"] if run_ok(r)]
    total: Counter[str] = Counter()
    for run_id in passed:
        db = raw / run_id / "actions.db"
        if db.exists():
            total.update(audit(read_records(db)))
    applied = total["applied"]
    harmful = total["harmful_twin_rejected"]
    return {
        "runs": len(passed),
        **total,
        "harmful_pct": 100.0 * harmful / applied if applied else 0.0,
    }


def fairness(table: Sequence[Row]) -> dict[str, Row]:
    """Per mode: the flash crowd's Jain index against its target (§5.1: >= 0.8)."""
    return {
        r["mode"]: {"jain": r["mean"], "target_met": r["mean"] >= JAIN_TARGET}
        for r in table
        if r["scenario"] == "lecture_flash_crowd" and r["kpi"] == "jain" and r["mean"] is not None
    }


def twin_mape(validation: Path) -> Row | None:
    """§5.2: the calibrated twin's throughput MAPE on the held-out test split (P3.5), in %."""
    if not validation.exists():
        return None
    test = json.loads(validation.read_text())["after_calibration"]["test"]["all"]
    return {"mape_pct": round(100.0 * test["mape"], 2), "n": test["n"]}


def markdown(report: Mapping[str, Any]) -> str:  # Any: the results.json report
    """results.md: the KPI tables, H1, fairness, H2 and safety, the twin, GenAI."""
    lines = [
        "# Evaluation results",
        "",
        "Mean ± 95% CI over seeds (n). never = runs that did not recover: counted at their run",
        "end, so that mean is a lower bound; H1 says inconclusive where such runs could change",
        "the answer (decision P6.6-A).",
        "",
        *_kpi_tables(report["table"]),
        *_h1_lines(report["h1"]),
        *_fairness_lines(report.get("fairness", {})),
        *_safety_lines(report["safety"]),
        *_twin_lines(report.get("twin")),
        *_genai_lines(report.get("genai", {})),
    ]
    return "\n".join([*lines, ""])


def _kpi_tables(table: Sequence[Row]) -> list[str]:
    lines = []
    for scenario in SCENARIOS:
        cells = {(r["mode"], r["kpi"]): r for r in table if r["scenario"] == scenario}
        modes = [m for m in MODES if any(k[0] == m for k in cells)]
        if not modes:
            continue
        lines += [
            f"## {scenario}",
            "",
            "| KPI | " + " | ".join(modes) + " |",
            "|---|" + "---|" * len(modes),
        ]
        for kpi in KPIS:
            lines.append(
                f"| {kpi} | " + " | ".join(_cell(cells.get((m, kpi))) for m in modes) + " |"
            )
        lines.append("")
    return lines


def _h1_lines(h1_result: Mapping[str, Row]) -> list[str]:
    lines = [f"## H1: V3 recovers faster than V1 (target >= {H1_TARGET_PCT:.0f}%)", ""]
    for scenario, r in h1_result.items():
        faster = f"{r['faster_pct']:.0f}% faster" if r["faster_pct"] is not None else "n/a"
        lines.append(
            f"- {scenario}: V1 {r['v1_s']:.0f} s, V3 {r['v3_s']:.0f} s, {faster}:"
            f" **{r['verdict']}** (never recovered: V1 {r['v1_never']}, V3 {r['v3_never']})"
        )
    return [*lines, ""]


def _fairness_lines(by_mode: Mapping[str, Row]) -> list[str]:
    lines = [f"## Fairness in the flash crowd (Jain, target >= {JAIN_TARGET})", ""]
    lines += ["| Mode | Jain | Target |", "|---|---|---|"]
    lines += [
        f"| {m} | {r['jain']:.2f} | {'met' if r['target_met'] else 'not met'} |"
        for m, r in by_mode.items()
    ]
    return [*lines, ""]


def _safety_lines(safety: Mapping[str, Mapping[str, float]]) -> list[str]:
    lines = ["## H2 and safety (executor ledgers of the passed runs)", ""]
    counts = list(dict.fromkeys(k for c in safety.values() for k in c))  # a mode may have none
    if counts:
        lines += ["| Mode | " + " | ".join(counts) + " |", "|---|" + "---|" * len(counts)]
        lines += [
            f"| {mode} | " + " | ".join(f"{c.get(k, 0):g}" for k in counts) + " |"
            for mode, c in safety.items()
        ]
    return [*lines, ""]


def _twin_lines(twin: Row | None) -> list[str]:
    if twin is None:
        return []
    mape = f"{twin['mape_pct']:.2f}% over {twin['n']} predictions"
    return ["## Twin accuracy (P3.5, held-out test split)", "", f"- Throughput MAPE: {mape}", ""]


def _genai_lines(genai: Mapping[str, Row]) -> list[str]:
    if not genai:
        return []
    lines = ["## GenAI (intent evals; per intent, retries and fallback included)", ""]
    lines += [
        "| Run | Correct | Schema-valid | p95 s | Under 10 s | Invalid caught |",
        "|---|---|---|---|---|---|",
    ]
    for name, g in genai.items():
        latency = g["latency"]
        caught = sum(c["invalid_caught"] for c in g["calls"].values())
        lines.append(
            f"| {name} | {g['correct']}/{g['cases']} ({g['accuracy']:.1%}) |"
            f" {g['schema_valid']}/{g['cases']} | {latency.get('p95_s', 0):.2f} |"
            f" {latency.get('under_10_s', 0):.0%} | {caught} |"
        )
    return [*lines, ""]


def _cell(row: Row | None) -> str:
    if row is None or row["mean"] is None:
        return "-"
    ci = f" ± {row['ci95']:.2f}" if row["ci95"] is not None else ""
    never = f", never {row['never']}" if row["never"] else ""
    return f"{row['mean']:.2f}{ci} (n {row['n']}{never})"


def main(argv: list[str] | None = None) -> int:
    """Regenerate experiments/results/ from the data; 0 always (the report is the output)."""

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    for mode in MODES:
        default = ROOT / "data" / f"eval{mode.lower()}-v1"
        parser.add_argument(f"--{mode.lower()}", type=Path, default=default)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args(argv)
    datasets = {m: getattr(args, m.lower()) for m in MODES}
    runs: dict[tuple[str, str], list[RunKpis]] = {}
    missing = []
    for mode, dataset in datasets.items():
        if (dataset / "kpi.parquet").exists():
            runs |= load_runs(dataset, mode)
        else:
            missing.append(f"{mode} ({dataset})")
    table = kpi_table(runs)
    h1_result = h1(table)
    raws = {mode: ROOT / "data" / "raw" / dataset.name for mode, dataset in datasets.items()}
    safety = {m: ledger_counts(raw) for m, raw in raws.items() if (raw / "batch.json").exists()}
    genai = {
        name: genai_numbers(args.out / f"{name}.json", args.out / f"intent_calls{suffix}.jsonl")
        for name, suffix in INTENT_EVALS.items()
        if (args.out / f"{name}.json").exists()
    }
    report = {
        "created": datetime.now(UTC).isoformat(timespec="seconds"),
        "git_commit": git_commit(),
        "datasets": {m: str(d) for m, d in datasets.items()},
        "missing": missing,
        "runs": {f"{m}/{s}": [asdict(k) for k in ks] for (m, s), ks in runs.items()},
        "table": table,
        "h1": h1_result,
        "fairness": fairness(table),
        "safety": safety,
        "twin": twin_mape(TWIN_VALIDATION),
        "genai": genai,
    }
    figures = args.out / "figures"
    figures.mkdir(parents=True, exist_ok=True)
    for scenario in SCENARIOS:
        rows = [r for r in table if r["scenario"] == scenario]
        if rows:
            kpi_figure(rows, scenario, figures / f"kpis_{scenario}.png")
    (args.out / "results.json").write_text(json.dumps(report, indent=1))
    (args.out / "results.md").write_text(markdown(report))
    print(f"RESULTS {args.out} (missing: {', '.join(missing) or 'none'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
