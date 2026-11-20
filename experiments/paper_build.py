"""The IEEE conference paper (final_submission/paper/): its numbers, tables and figures, generated
from the recorded evaluation, so that no result in the paper is typed by hand.

    make paper            # generated/ + figures/ from the evaluation, then paper.pdf (Tectonic)
    make paper-check      # fail if generated/ is out of date with the evaluation

`main.tex` takes every result from `generated/numbers.tex` (one `\\newcommand` per number) and
`generated/table_*.tex`, and its plots from `figures/*.pdf` (experiments/paper_figures.py). All
of them are rebuilt from the recorded evaluation (experiments/paper_evidence.py lists the files).
"""

from __future__ import annotations

import argparse
import logging
import math
import statistics
import subprocess
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from datetime import timedelta
from itertools import pairwise
from pathlib import Path
from typing import Any

from common.schemas import MAX_STEER_FRACTION, MIN_TARGET_RSSI_DBM
from controller.executor.ledger import ActionRecord
from experiments.analysis.results import H1_TARGET_PCT, stress_window
from experiments.batch import LOOP_MODES, load_scenario
from experiments.paper_evidence import (
    HARMFUL,
    KPI_FIELDS,
    KPIS,
    MODE_LABELS,
    MODE_WORDS,
    RESOLVED,
    ROOT,
    SCENARIOS,
    STATUS_WORDS,
    Evidence,
    capacity_mbps,
    cochannel_pairs,
    correct_by_kind,
    improvements,
    intent_kinds,
    kpi_cells,
    kpi_range,
    latency_cap_ms,
    live_errors,
    load_evidence,
    prediction_times,
    resolved_actions,
)
from experiments.paper_figures import ERROR_FLOOR_PCT, FIGURES, SYMLOG_LINEAR_PCT
from experiments.shell import run
from twin.radio import load_radio_params
from twin.sim.analytical import load_sim_params
from twin.verify.verifier import CHANGE_PCT, TX_POWER_MAX_STEP_DB, _kpi_rule

log = logging.getLogger("experiments.paper_build")
PAPER = ROOT / "final_submission" / "paper"
TEX_TIMEOUT_S = 600.0  # Tectonic fetches its bundle on the first run

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


# ---------------------------------------------------------------- numbers


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
    # H1 on the capped recovery times (a run that never recovers counts at its end): met only if
    # V3 is at least H1_TARGET_PCT faster in every scenario
    capped = all(h1["faster_pct"] >= H1_TARGET_PCT for h1 in res["h1"].values())
    out["HoneCapped"] = "met" if capped else "not met"
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
    sim_ms = prediction_times(ev)
    out["SimMedianMs"] = _f(statistics.median(sim_ms), 2) if sim_ms else "0"
    out |= _failed_rollbacks(ev)
    return (
        out
        | _model_numbers(ev)
        | _config_numbers(ev)
        | _verifier_numbers(ev)
        | _fault_numbers(ev)
        | _run_numbers(ev)
    )


# ---- the verifier against what the watch found (reviewer round 1: Eq. (6), unvalidated KPIs)

LIVE_WORDS = {"throughput_mbps": "Thr", "latency_ms": "Lat", "loss_pct": "Loss", "jain": "Jain"}


def _only_fairness_gain(record: ActionRecord) -> bool:
    """Whether the only KPI predicted to improve by more than the tolerance is Jain's index,
    which depends on the APs' client counts alone."""
    gain = dict(zip(KPI_FIELDS, improvements(record), strict=True))
    return gain["jain"] > CHANGE_PCT and all(
        v <= CHANGE_PCT for k, v in gain.items() if k != "jain"
    )


def _no_regression(record: ActionRecord) -> bool:
    return all(x >= -CHANGE_PCT for x in improvements(record))


def _accepts_on(record: ActionRecord, kpis: Sequence[str]) -> bool:
    """The acceptance rule as written, but over some of the KPIs only."""
    gain = dict(zip(KPI_FIELDS, improvements(record), strict=True))
    chosen = [gain[k] for k in kpis]
    return all(x >= -CHANGE_PCT for x in chosen) or any(x > CHANGE_PCT for x in chosen)


RULES: dict[str, Callable[[ActionRecord], bool]] = {  # macro word -> does the rule accept it?
    # the verifier's own rule, called as the code has it, so "as written" cannot drift from it
    "Written": lambda r: not _kpi_rule(r.verdict.baseline, r.verdict.predicted),
    "NoReg": _no_regression,
    "Conj": lambda r: _no_regression(r) and any(x > CHANGE_PCT for x in improvements(r)),
    # only the KPIs whose prediction was validated offline: throughput and Jain's index
    "ThrJain": lambda r: _accepts_on(r, ("throughput_mbps", "jain")),
}


def fisher_one_sided(a: int, b: int, c: int, d: int) -> float:
    """Fisher's exact test, one-sided: P(at least `a`) in the 2x2 table [[a, b], [c, d]] under
    independence (the hypergeometric tail). Row 1 is the group that should have more of the
    first column."""
    row1, first, total = a + b, a + c, a + b + c + d
    ways = math.comb(total, row1)
    tail = sum(
        math.comb(first, x) * math.comb(total - first, row1 - x)
        for x in range(a, min(row1, first) + 1)
    )
    return tail / ways


def _verifier_numbers(ev: Evidence) -> dict[str, str]:
    """What became of the actions the twin judged. The harm counts, the stricter rules and the
    Fisher test use V2 only: V2 applies every action whatever the verdict, so it is the one
    sample in which the twin's rejections can be compared with its acceptances (V3 applies only
    accepted actions, so its harmful ones can never have been rejected and would bias the rate
    against the twin). Its harmful actions are counted apart. The prediction error uses both."""
    out: dict[str, str] = {}
    resolved = {m: [r for r in ev.actions(m) if r.status in RESOLVED] for m in ("V2", "V3")}
    v2 = resolved["V2"]
    harmful = [r for r in v2 if r.status in HARMFUL]
    kept = [r for r in v2 if r.status == "kept"]
    out["HarmAll"], out["KeptAll"] = str(len(harmful)), str(len(kept))
    out["HarmRejected"] = str(sum(not r.verdict.accepted for r in harmful))
    out["HarmAccepted"] = str(sum(r.verdict.accepted for r in harmful))
    out["HarmVthree"] = str(sum(r.status in HARMFUL for r in resolved["V3"]))
    out["HarmAnyRegress"] = str(sum(min(improvements(r)) < 0 for r in harmful))
    out["HarmJainOnly"] = str(
        sum(
            r.verdict.accepted and _only_fairness_gain(r)
            for m in resolved.values()
            for r in m
            if r.status in HARMFUL
        )
    )
    for word, rule in RULES.items():
        out[f"Rule{word}Harm"] = str(sum(not rule(r) for r in harmful))
        out[f"Rule{word}Kept"] = str(sum(not rule(r) for r in kept))
    both = resolved_actions(ev)  # V2's and V3's
    out["RuleAgree"] = str(sum(RULES["Written"](r) == r.verdict.accepted for r in both))
    out["RuleTotal"] = str(len(both))
    cells = [
        [_count(v2, accepted, bad) for bad in (True, False)] for accepted in (False, True)
    ]  # rows: twin rejected, accepted; columns: harmful, kept
    out["HarmFisherP"] = _f(fisher_one_sided(cells[0][0], cells[0][1], cells[1][0], cells[1][1]), 2)
    out["VtwoRejHarm"], out["VtwoRejTotal"] = str(cells[0][0]), str(sum(cells[0]))
    out["VtwoAccHarm"], out["VtwoAccTotal"] = str(cells[1][0]), str(sum(cells[1]))
    return out | _live_error_numbers(both)


def _count(records: Sequence[ActionRecord], accepted: bool, harmful: bool) -> int:
    """How many of the resolved `records` the twin accepted (or rejected) and the watch found
    harmful (or kept)."""
    return sum(r.verdict.accepted == accepted and (r.status in HARMFUL) == harmful for r in records)


def _live_error_numbers(resolved: Sequence[ActionRecord], prefix: str = "Live") -> dict[str, str]:
    """Median relative error, per KPI, of the twin's prediction against the KPIs the watch
    measured for the same flows; and of "nothing changes" (the twin's own baseline)."""
    measured = [r for r in resolved if r.measured is not None]
    out = {f"{prefix}N": str(len(measured))}
    for kpi, word in LIVE_WORDS.items():
        twin, unchanged = live_errors(measured, kpi)
        out[f"{prefix}{word}N"] = str(len(twin))  # how many of the measurements this KPI covers
        for suffix, errors in (("Err", twin), ("Base", unchanged)):
            out[f"{prefix}{word}{suffix}"] = _f(statistics.median(errors), 1) if errors else "n/a"
    return out


def _run_numbers(ev: Evidence) -> dict[str, str]:
    """Per-seed values of the runs the intervals are widest for, how many runs recovered, and
    the retries of the intent evaluation."""
    runs = ev.results["runs"]
    out = {}
    for mode in ("V2", "V3"):
        seeds = runs[f"{mode}/ap_failure"]
        word = MODE_WORDS[mode]
        out[f"PerSeedLossApFail{word}"] = ", ".join(_f(r["loss_pct"], 1) for r in seeds)
        out[f"PerSeedLatApFail{word}"] = ", ".join(_f(r["latency_p95_ms"], 0) for r in seeds)
    for mode in LOOP_MODES:
        recovered = sum(r["ttr_s"] is not None for s in SCENARIOS for r in runs[f"{mode}/{s}"])
        out[f"Recov{MODE_WORDS[mode]}"] = str(recovered)
    out["IntCalls"] = str(len(ev.intent_calls))
    local = correct_by_kind(ev.intents_local, intent_kinds(ev))
    (out["IntLocalSimpleOk"], out["IntSimple"]) = map(str, local["single-clause"])
    (out["IntLocalCompoundOk"], out["IntCompound"]) = map(str, local["compound"])
    out["IntRepairs"] = str(sum(call.get("attempt", 1) > 1 for call in ev.intent_calls))
    out["IntFirstValid"] = str(
        sum(call.get("attempt", 1) == 1 and call.get("valid", False) for call in ev.intent_calls)
    )
    return out


def _fault_numbers(ev: Evidence) -> dict[str, str]:
    """When the actions of V2 and V3 were applied: how many had the scenario's scheduled
    disruption inside the window they were judged on (the watch cannot tell the fault from the
    action's effect), how the twin and its closed-loop error fare without them, and how many
    ticks applied more than one action (their watches then run side by side). The executor
    compares the watch's KPIs with those of the `watch_s` before the action, so the disruption
    taints the verdict if it falls within `watch_s` before the action or within `watch_s` after."""
    watch = timedelta(seconds=ev.config["executor"]["watch_s"])
    same_tick = timedelta(seconds=ev.config["loop"]["period_s"] / 2)
    straddling, multi = 0, 0
    v2_harm, v2_straddling, v2_rejected_clear, v2_kept_straddling = 0, 0, 0, 0
    clear: list[ActionRecord] = []  # resolved actions whose verdict the disruption did not taint
    for mode in ("V2", "V3"):
        for run_id, records in ev.ledgers[mode].items():
            start = ev.run_starts[mode][run_id]
            onset = timedelta(
                seconds=stress_window(load_scenario(run_id.rsplit("-", 2)[0])).onset_s
            )
            for r in records:
                if r.status not in RESOLVED or r.applied_at is None:
                    continue
                at = r.applied_at - start
                tainted = at - watch < onset < at + watch
                if not tainted:
                    clear.append(r)
                if r.status in HARMFUL:
                    straddling += tainted
                    if mode == "V2":
                        v2_harm += 1
                        v2_straddling += tainted
                        v2_rejected_clear += not tainted and not r.verdict.accepted
                elif mode == "V2":
                    v2_kept_straddling += tainted
            times = sorted(r.applied_at for r in records if r.applied_at is not None)
            group = 1
            for before, after in pairwise(times):
                if after - before < same_tick:
                    group += 1
                    multi += group == 2  # noqa: PLR2004 - count a group once, when it reaches two
                else:
                    group = 1
    return {
        "HarmStraddle": str(straddling),
        "HarmStraddleVtwo": str(v2_straddling),
        "HarmClearVtwo": str(v2_harm - v2_straddling),
        "HarmClearRejected": str(v2_rejected_clear),
        "KeptStraddleVtwo": str(v2_kept_straddling),
        "TickMulti": str(multi),
    } | _live_error_numbers(clear, "LiveClear")


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
    params = load_radio_params(cfg["campus_v1"])
    aps = {a["name"]: a["position"] for a in cfg["campus_v1"]["aps"]}
    # ap1 and ap4 share channel 1 (the text says so: a KeyError if the campus changes): the
    # capacity each keeps from the start of every run
    pairs = {(a, b): d for a, b, d in cochannel_pairs(cfg["campus_v1"])}
    shared = capacity_mbps([pairs[("ap1", "ap4")]], params)
    floor = cfg["executor"]["noise_floor"]
    places = ", ".join(f"{n} ({x:g}, {y:g})" for n, (x, y) in aps.items())
    return {
        "CfgVideo": _f(cfg["sim"]["apps"]["video"]["offered_mbps"], 1),
        "CfgWebRate": _f(cfg["sim"]["apps"]["web"]["offered_mbps"], 2),
        "CfgApPlaces": places.replace(", ap4", " and ap4"),
        "CfgFloorThr": _f(floor["throughput_mbps"], 2),
        "CfgFloorLat": _f(floor["latency_ms"], 1),
        "CfgFloorLoss": _f(floor["loss_pct"], 2),
        "CfgFloorJain": _f(floor["jain"], 2),
        "CfgSharedCapacity": _f(shared, 2),
        "CfgRssiOne": _f(params.rssi_at_1m_dbm, 0),
        "CfgPathExp": _f(params.path_loss_exp, 1),
        "CfgCapacity": _f(radio["ap_capacity_mbps"], 1),
        "CfgBaseLoss": _f(cfg["sim"]["base_loss_pct"], 1),
        "CfgFetch": _f(cfg["sim"]["fetch_efficiency"], 1),
        "CfgBulk": _f(cfg["sim"]["apps"]["bulk"]["offered_mbps"], 3),
        # the most the queue model can predict: base delay + service time x the K packets it holds
        "CfgLatCap": _f(latency_cap_ms(load_sim_params(cfg["sim"])), 1),
        # how two figures draw (captions quote them): the symmetric-log axes are linear within
        # this many %, and the error axis draws smaller errors at its floor
        "FigLinearPct": _f(SYMLOG_LINEAR_PCT, 0),
        "FigErrorFloorPct": _f(ERROR_FLOOR_PCT, 1),
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


def _span(ev: Evidence, cell: Mapping[str, Any], decimals: int) -> str:
    low, high = kpi_range(ev, cell["mode"], cell["scenario"], cell["kpi"])
    return f"{_f(cell['mean'], decimals)} [{_f(low, decimals)}--{_f(high, decimals)}]"


def _boxed_tabular(
    columns: Sequence[str],
    head: Sequence[str],
    rows: Sequence[Sequence[str]],
    rules: Sequence[str] | None = None,
) -> str:
    """A fully boxed tabular: a border around it and between every column and row. `rules[i]`
    is the rule under body row i (default: \\hline under every row)."""
    under = ["\\hline"] * len(rows) if rules is None else rules
    lines = [
        f"\\begin{{tabular}}{{|{'|'.join(columns)}|}}",
        "\\hline",
        " & ".join(head) + " \\\\",
        "\\hline",
    ]
    for row, rule in zip(rows, under, strict=True):
        lines += [" & ".join(row) + " \\\\", rule]
    return "\n".join([*lines, "\\end{tabular}"]) + "\n"


def table_kpis(ev: Evidence) -> str:
    """The KPI table: mean and [smallest--largest] over the seeds, per scenario and variant
    (tabular only). Within a scenario the rules leave the cell of its name open."""
    cells = kpi_cells(ev)
    rows: list[list[str]] = []
    rules: list[str] = []
    for scenario, (_, title) in SCENARIOS.items():
        for mi, mode in enumerate(LOOP_MODES):
            row = [title if mi == 0 else "", MODE_LABELS[mode]]
            for kpi, (_, decimals, _) in KPIS.items():
                cell = cells[(mode, scenario, kpi)]
                text = _span(ev, cell, decimals)
                if kpi == "ttr_s":  # how many of the runs never recovered, counted at the run end
                    text = f"$\\geq$ {text} ({cell['never']})" if cell["never"] else f"{text} (0)"
                row.append(text)
            rows.append(row)
            last = mi == len(LOOP_MODES) - 1  # a full rule only under a scenario's last row
            rules.append("\\hline" if last else f"\\cline{{2-{2 + len(KPIS)}}}")
    head = ["Scenario", "Variant", *(k[2] for k in KPIS.values())]
    return _boxed_tabular(["l", "l", *["c"] * len(KPIS)], head, rows, rules)


RULE_LABELS = {
    "Written": "As written (no KPI $>$5\\% worse, or one $>$5\\% better)",
    "NoReg": "No KPI more than 5\\% worse",
    "Conj": "No KPI more than 5\\% worse and one more than 5\\% better",
    "ThrJain": "As written, on throughput and Jain's index only",
}


def table_rules(ev: Evidence) -> str:
    """What each acceptance rule would have rejected among the resolved actions of V2 and V3
    that the watch found harmful, and among those it kept (tabular only)."""
    n = numbers(ev)
    rows = [
        [
            label,
            f"{n[f'Rule{word}Harm']} of {n['HarmAll']}",
            f"{n[f'Rule{word}Kept']} of {n['KeptAll']}",
        ]
        for word, label in RULE_LABELS.items()
    ]
    head = ["Acceptance rule", "Harmful rejected", "Kept rejected"]
    label = ">{\\raggedright\\arraybackslash}p{3.6cm}"  # ragged: a narrow justified cell stretches
    return _boxed_tabular([label, "c", "c"], head, rows)


def table_actions(ev: Evidence) -> str:
    """What became of every action, from the executor ledgers: one row per fate, one column per
    variant (tabular only)."""
    counts = {mode: status_counts(ev.actions(mode)) for mode in LOOP_MODES}
    rows = [["Proposed", *(str(sum(counts[m].values())) for m in LOOP_MODES)]]
    ignored = sum(not r.verdict.accepted for r in ev.actions("V2"))  # applied anyway in V2
    for status, (_, heading) in STATUS_WORDS.items():
        cells = [str(counts[m][status]) for m in LOOP_MODES]
        if status == "rejected" and ignored:
            cells[LOOP_MODES.index("V2")] += f" ({ignored} ignored)"
        rows.append([heading, *cells])
    return _boxed_tabular(["l", *["r"] * len(LOOP_MODES)], ["Actions", *LOOP_MODES], rows)


# ---------------------------------------------------------------- build


def build_generated(ev: Evidence, out: Path) -> list[Path]:
    """Write numbers.tex, the tables and the figures under `out`; the files written."""
    gen, figs = out / "generated", out / "figures"
    gen.mkdir(parents=True, exist_ok=True)
    figs.mkdir(parents=True, exist_ok=True)
    files = {gen / name: text for name, text in texts(ev).items()}
    for path, text in files.items():
        path.write_text(text)
    for name, draw in FIGURES.items():
        draw(ev, figs / name)
    return [*files, *(figs / name for name in FIGURES)]


def texts(ev: Evidence) -> dict[str, str]:
    """The generated LaTeX files by name: what the evaluation gives now."""
    return {
        "numbers.tex": render_numbers(numbers(ev)),
        "table_kpis.tex": table_kpis(ev),
        "table_actions.tex": table_actions(ev),
        "table_rules.tex": table_rules(ev),
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
    logging.getLogger("fontTools").setLevel(logging.WARNING)  # its font-subsetting notes per PDF
    try:
        ev = load_evidence(series=not args.check)  # the check compares text, not the figures
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
