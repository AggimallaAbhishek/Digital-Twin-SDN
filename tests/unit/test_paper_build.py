"""The IEEE paper's generated numbers, tables and figures (experiments/paper_build.py)."""

from __future__ import annotations

import dataclasses
import json
import re
import shutil
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from common.schemas import ACTION_ADAPTER, KPIValues, Verdict
from controller.executor.ledger import ActionRecord, Ledger, read_records
from experiments import paper_build, paper_evidence, paper_figures
from experiments.batch import LOOP_MODES, load_scenario

REPO = Path(__file__).resolve().parents[2]
T0 = datetime(2026, 10, 12, 8, 0, tzinfo=UTC)
MODES = LOOP_MODES
SCENARIOS = tuple(paper_evidence.SCENARIOS)
KPI_MEANS = {  # kpi -> mean of every cell (V3 flash-crowd loss is made distinctive below)
    "ttr_s": 390.0,
    "throughput_mbps": 0.52,
    "latency_p95_ms": 24.0,
    "loss_pct": 9.2,
    "jain": 0.78,
}
STEER = {
    "source": "optimizer.heuristic",
    "reason": "ap1 at 100% of capacity",
    "created_at": "2026-10-12T08:00:00Z",
    "type": "steer_clients",
    "params": {"from_ap": "ap1", "to_ap": "ap3", "stations": ["sta2"]},
}
KPIS = {"throughput_mbps": 0.5, "latency_ms": 12.0, "loss_pct": 20.0, "jain": 0.5}


def _json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def _table() -> list[dict[str, Any]]:
    rows = []
    for mode in MODES:
        for scenario in SCENARIOS:
            for kpi, mean in KPI_MEANS.items():
                never = 3 if kpi == "ttr_s" and mode == "V1" else 0
                value = 8.57 if (mode, scenario, kpi) == ("V3", SCENARIOS[0], "loss_pct") else mean
                rows.append(
                    {"mode": mode, "scenario": scenario, "kpi": kpi, "mean": value, "ci95": 1.5}
                    | {"n": 3, "never": never, "high": value}
                )
    return rows


def _results() -> dict[str, Any]:
    safety = {
        mode: {
            "runs": 9,
            "recorded": n,
            "applied": n,
            "applied_twin_rejected": 0,
            "harmful_twin_rejected": 0,
            "slipped_past_twin": 2,
            "rollback_failed": 1,
            "high_impact_unapproved": 0,
            "unresolved": 0,
            "harmful_pct": 0.0,
        }
        for mode, n in zip(MODES, (0, 5, 6), strict=True)
    }
    runs = {
        f"{mode}/{scenario}": [
            {"ttr_s": None if mode == "V1" or k == 0 else 100.0 * k, "censor_s": 390.0}
            | {"loss_pct": 1.0 + k, "latency_p95_ms": 10.0 * (k + 1)}
            | {"throughput_mbps": 0.5 + 0.1 * k, "jain": 0.7 + 0.05 * k}
            for k in range(3)
        ]
        for mode in MODES
        for scenario in SCENARIOS
    }
    h1 = {
        s: {"faster_pct": 7.86, "verdict": "inconclusive", "v1_s": 390.0, "v3_s": 359.0}
        for s in SCENARIOS
    }
    return {
        "table": _table(),
        "datasets": {m: f"data/eval{m.lower()}-v1" for m in MODES},
        "runs": runs,
        "h1": h1,
        "fairness": {m: {"jain": 0.5 + 0.1 * i, "target_met": False} for i, m in enumerate(MODES)},
        "safety": safety,
    }


def _ledger(path: Path, outcomes: list[tuple[str, float]]) -> None:
    """A run's ledger: one steer per (status, twin prediction time in ms)."""
    db = Ledger(path)
    for i, (status, sim_ms) in enumerate(outcomes):
        action = ACTION_ADAPTER.validate_python(
            STEER | {"action_id": f"act_{path.parent.name.replace('-', '_')}_{i}"}
        )
        verdict = Verdict.model_validate(
            {
                "action_id": action.action_id,
                "accepted": status != "rejected",
                "predicted": KPIS,
                "baseline": KPIS,
                "violations": [],
                "impact": "medium",
                "needs_approval": False,
                "sim_mode": "analytical",
                "sim_time_ms": sim_ms,
            }
        )
        db.add([action], [verdict], T0)
        if status not in ("rejected", "verified"):
            db.update(action.action_id, status, T0, applied_at=T0)


RUN_START = T0 - timedelta(seconds=230)  # an action at T0 is 230 s into a run: 10 s before 240 s
TELEMETRY_STEP_S = 5  # as the figures average: every window has a row
HOME = {"sta1": "ap2", "sta2": "ap1", "sta3": "ap3", "sta4": "ap4"}  # one station per AP
UTIL = {"ap1": 0.9, "ap2": 0.5, "ap3": 0.4, "ap4": 0.3}  # ap1 is the busiest in every run
WALKER = "sta4"  # walks 30 m before the flash crowd's onset


def _write(dataset: Path, name: str, rows: list[dict[str, Any]]) -> None:
    pq.write_table(pa.Table.from_pylist(rows), dataset / f"{name}.parquet")


def _telemetry(dataset: Path, runs: list[str]) -> None:
    """A dataset's AP, station and flow telemetry: per run (`<scenario>-<mode>-s<seed>`), every
    TELEMETRY_STEP_S of 600 s, four APs with one station and one video flow each."""
    aps, stations, kpis = [], [], []
    for run_id in runs:
        scenario, _, seed = run_id.rsplit("-", 2)
        common = {"run_id": run_id, "scenario_id": scenario}
        for t in range(0, 600, TELEMETRY_STEP_S):
            for ap, util in UTIL.items():
                aps.append(
                    common
                    | {"seed": int(seed[1:]), "t_s": float(t), "ap": ap}
                    | {"channel_util": util, "n_clients": 1 + (ap == "ap1") * (t >= 200)}
                )
            for k, (sta, ap) in enumerate(HOME.items()):
                x = 10.0 + 30 * (sta == WALKER and t >= 100)
                stations.append(
                    common | {"t_s": float(t), "sta": sta, "ap": ap, "x": x, "y": 5.0 * k}
                )
                kpis.append(
                    common
                    | {"ts": RUN_START + timedelta(seconds=t), "t_s": float(t)}
                    | {"flow_id": f"{sta}-video", "app_class": "video"}
                    | {"throughput_mbps": 0.5, "latency_ms": 10.0 + k, "loss_pct": 2.0 * k}
                )
    dataset.mkdir(parents=True, exist_ok=True)
    _write(dataset, "ap_stats", aps)
    _write(dataset, "sta_stats", stations)
    _write(dataset, "kpi", kpis)


def make_tree(tmp_path: Path) -> Path:
    """A repository-shaped folder holding a small recorded evaluation."""
    root = tmp_path / "repo"
    results = root / "experiments" / "results"
    _json(results / "results.json", _results())
    cloud = {"cases": 30, "correct": 30, "seconds": [1.0, 2.0, 3.0], "misses": []}
    _json(results / "intents.json", cloud | {"models": {"cloud-model": 30}})
    local = {"cases": 30, "correct": 21, "seconds": [2.0, 4.0], "misses": ["i01", "i12"]}
    _json(results / "intents_local.json", local | {"models": {"local-model": 30}})
    shutil.copytree(REPO / "genai" / "eval", root / "genai" / "eval")  # the real intent set
    calls = [{"attempt": 1, "valid": True}, {"attempt": 1, "valid": False}, {"attempt": 2}]
    (results / "intent_calls.jsonl").write_text("".join(json.dumps(c) + "\n" for c in calls))
    (results / "intent_calls_local.jsonl").write_text(json.dumps({"attempt": 1}) + "\n")
    twin = {"after_calibration": {"test": {
        "all": {"mape": 0.0449, "n": 586},
        "steady/video": {"mape": 0.0397, "n": 495},
        "steer_clients/video": {"mape": 0.0325, "n": 39},
        "set_ap_channel/video": {"mape": 0.0813, "n": 10},
        "steady/bulk": {"mape": 0.1726, "n": 20},
        "steer_clients/bulk": {"mape": 0.2075, "n": 2},
        "set_qos_queue/bulk": {"mape": 0.1241, "n": 1},
    }}}  # fmt: skip
    _json(root / "models" / "twin" / "v1" / "validation.json", twin)
    anomaly = {
        "test": {"precision": 0.95, "recall": 0.979, "f1": 0.964},
        "test_by_scenario": {s: {"precision": 0.9, "recall": 1.0} for s in (*SCENARIOS, "normal")},
        "test_detection": {
            "ap_failure-s44": {"delay_s": 5.0},
            "cochannel_interference-s44": {"delay_s": 25.0},
            "lecture_flash_crowd-s44": {"delay_s": 5.0, "false_alarms_before": 12},
        },
    }
    _json(root / "models" / "anomaly" / "v1" / "metrics.json", anomaly)
    rmse = {"holt": {"rmse_60s": 0.1294, "rmse_180s": 0.2562}}
    rmse["moving_average"] = {"rmse_60s": 0.1171, "rmse_180s": 0.2116}
    forecast = {
        "metrics": {"test": rmse},
        "test_by_scenario": {s: rmse for s in (*SCENARIOS, "normal")},
        "config": {"horizons_s": [60, 180]},
    }
    _json(root / "models" / "forecast" / "v1" / "metrics.json", forecast)
    genai = {
        "copilot_correct": 5,
        "copilot_questions": 5,
        "rca_correct": 3,
        "rca_alerts": 3,
        "llm_actions": 6,
        "llm_actions_with_verdict_in_audit_log": 6,
    }
    _json(root / "models" / "genai" / "v1" / "live.json", {"summary": genai})
    shutil.copytree(REPO / "config", root / "config")  # the real, tracked configuration
    outcomes = {
        "V1": [],
        "V2": [
            ("kept", 0.1),
            ("kept", 0.3),
            ("rolled_back", 0.2),
            ("applied", 0.2),
            ("rollback_failed", 0.2),
        ],
        "V3": [("kept", 0.5), ("rolled_back", 0.5), ("rejected", 0.5), ("verified", 0.5)],
    }
    for mode, actions in outcomes.items():
        raw = root / "data" / "raw" / f"eval{mode.lower()}-v1"
        passed, other = f"ap_failure-{mode.lower()}-s42", f"normal-{mode.lower()}-s43"
        ok = {"passed": True, "scenario_ok": True}
        runs = [{"run_id": passed} | ok, {"run_id": other} | ok | {"scenario_ok": False}]
        _json(raw / "batch.json", {"runs": runs})  # the second run did not pass: left out
        telemetry = [f"{s}-{mode.lower()}-s42" for s in SCENARIOS]  # passed is one of them
        _telemetry(root / "data" / f"eval{mode.lower()}-v1", [*telemetry, other])
        if actions:
            _ledger(raw / passed / "actions.db", actions)
            _ledger(raw / other / "actions.db", [("kept", 0.1)])
    return root


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    return make_tree(tmp_path)


@pytest.fixture
def evidence(tree: Path) -> paper_evidence.Evidence:
    return paper_evidence.load_evidence(tree)


def test_numbers_come_from_the_recorded_results(evidence: paper_evidence.Evidence) -> None:
    n = paper_build.numbers(evidence)
    assert n["KpiFlashLossVthree"] == "8.6"  # the table's 8.57, to one decimal
    assert n["KpiApFailTtrVone"] == "390"
    assert (n["NeverFlashVone"], n["NeverFlashVtwo"]) == ("3", "0")
    assert (n["HoneFasterCochan"], n["HoneVerdictCochan"]) == ("8", "inconclusive")
    assert n["FairJainVthree"] == "0.70"
    assert (n["SafeVtwoApplied"], n["SafeVthreeSlippedPastTwin"]) == ("5", "2")
    assert n["NumRuns"] == "27"


def test_what_became_of_actions_is_counted_in_the_ledgers_of_passed_runs(
    evidence: paper_evidence.Evidence,
) -> None:
    n = paper_build.numbers(evidence)
    assert n["LedVoneProposed"] == "0"
    # V2: run 1 has kept x2, rolled back, still watched; the run that did not pass is left out
    assert (n["LedVtwoProposed"], n["LedVtwoKept"], n["LedVtwoRolledBack"]) == ("5", "2", "1")
    assert n["LedVtwoWatched"] == "1"
    assert (n["LedVthreeRejected"], n["LedVthreeWaiting"], n["LedVthreeKept"]) == ("1", "1", "1")


def test_failed_rollbacks_are_counted_by_the_scenario_of_their_run(
    evidence: paper_evidence.Evidence, tree: Path
) -> None:
    n = paper_build.numbers(evidence)
    assert (n["RbFailAll"], n["RbFailApFail"]) == ("1", "1")  # V2's, in its ap_failure run
    batch = tree / "data" / "raw" / "evalv2-v1"
    shutil.move(batch / "ap_failure-v2-s42", batch / "cochannel_interference-v2-s42")
    _json(
        batch / "batch.json",
        {
            "runs": [
                {"run_id": "cochannel_interference-v2-s42", "passed": True, "scenario_ok": True}
            ]
        },
    )
    _telemetry(tree / "data" / "evalv2-v1", ["cochannel_interference-v2-s42"])
    moved = paper_build.numbers(paper_evidence.load_evidence(tree))
    assert (moved["RbFailAll"], moved["RbFailApFail"]) == ("1", "0")


def test_the_twins_prediction_time_is_the_ledgers_median(evidence: paper_evidence.Evidence) -> None:
    # twin prediction times of the 9 actions of passed runs: 0.1 0.2 0.2 0.2 0.3 and 0.5 x4
    assert paper_build.numbers(evidence)["SimMedianMs"] == "0.30"  # the middle one of nine


def test_model_and_configuration_numbers(evidence: paper_evidence.Evidence) -> None:
    n = paper_build.numbers(evidence)
    assert (n["TwinMape"], n["TwinN"], n["TwinChannel"]) == ("4.5", "586", "8.1")
    assert (n["TwinBulkLow"], n["TwinBulkHigh"]) == ("12", "21")
    assert (n["TwinChannelN"], n["TwinSteadyN"]) == ("10", "495")  # the cases behind a percentage
    assert (n["CfgStationSeed"], n["CfgForestSeed"]) == ("7", "42")  # seeds from the configuration
    assert (n["AnoF"], n["AnoDelayFail"], n["AnoDelayCochan"]) == ("0.964", "5", "25")
    assert (n["FcHoltOne"], n["FcMaThree"]) == ("0.129", "0.212")
    assert (n["IntCloudOk"], n["IntLocalOk"], n["IntCases"]) == ("30", "21", "30")
    assert (n["IntCloudSeconds"], n["IntLocalSeconds"]) == ("2.0", "3.0")
    assert (n["GenCopilotOk"], n["GenRcaN"], n["GenActionsVerdict"]) == ("5", "3", "6")
    # the constants the method section quotes come from the code, not from the text
    assert (n["CfgMaxSteerPct"], n["CfgMinRssi"], n["CfgChangePct"]) == ("30", "-75", "5")
    assert (n["CfgCapacity"], n["CfgWatch"], n["CfgRegressPct"]) == ("4.6", "30", "10")
    # the queue model's cap d0 + sigma K (config/sim.yaml: 0.8 + 2.5 x 6) and how the figures
    # draw, which their captions quote
    assert n["CfgLatCap"] == "15.8"
    assert (n["FigLinearPct"], n["FigErrorFloorPct"]) == ("10", "0.1")


def test_every_number_is_a_valid_latex_macro(evidence: paper_evidence.Evidence) -> None:
    text = paper_build.render_numbers(paper_build.numbers(evidence))
    macros = re.findall(r"^\\newcommand\{\\([^}]*)\}\{([^}]*)\}$", text, flags=re.MULTILINE)
    assert len(macros) == text.count("\\newcommand")
    assert all(re.fullmatch(r"[A-Za-z]+", name) for name, _ in macros)  # no digits in a name
    assert all(value for _, value in macros)


def test_the_kpi_table_marks_means_that_include_runs_that_never_recovered(
    evidence: paper_evidence.Evidence,
) -> None:
    table = paper_build.table_kpis(evidence)
    rows = [line for line in table.splitlines() if line.endswith("\\\\") and "&" in line]
    body = [r for r in rows if any(label in r for label in paper_evidence.MODE_LABELS.values())]
    assert len(body) == 9  # three variants in each of three scenarios
    assert "$\\geq$ 390 [390--390] (3)" in body[0]  # V1: all three runs never recovered
    assert "$\\geq$" not in body[1]  # V2: every run recovered ...
    assert body[1].count("(0)") == 1  # ... and the table says none never did
    assert body[2].startswith(" & V3 full & ")  # the scenario's name only on its first row


@pytest.mark.parametrize("table", ["table_kpis", "table_actions", "table_rules"])
def test_every_table_is_fully_boxed(evidence: paper_evidence.Evidence, table: str) -> None:
    lines = getattr(paper_build, table)(evidence).splitlines()
    spec = re.fullmatch(r"\\begin\{tabular\}\{(.*)\}", lines[0])
    assert spec is not None
    columns = spec.group(1)
    assert columns.startswith("|")  # a border on the left, the right ...
    assert columns.endswith("|")
    assert columns.count("|") == lines[2].count("&") + 2  # ... and between every two columns
    assert lines[1] == "\\hline"  # closed at the top ...
    assert lines[-2] == "\\hline"  # ... and at the bottom
    rows = [i for i, line in enumerate(lines) if line.endswith("\\\\")]
    rules = [lines[i + 1] for i in rows]
    assert all(re.fullmatch(r"\\hline|\\cline\{.*\}", rule) for rule in rules)  # one after each row


def test_the_action_table_has_a_row_per_fate_and_a_column_per_variant(
    evidence: paper_evidence.Evidence,
) -> None:
    lines = paper_build.table_actions(evidence).splitlines()
    rows = [line for line in lines if line.endswith("\\\\")]
    assert rows == [
        "Actions & V1 & V2 & V3 \\\\",
        "Proposed & 0 & 5 & 4 \\\\",
        "Kept & 0 & 2 & 1 \\\\",
        "Rolled back & 0 & 1 & 1 \\\\",
        "Rollback failed & 0 & 1 & 0 \\\\",
        "Still watched & 0 & 1 & 0 \\\\",
        "Rejected, not applied & 0 & 0 & 1 \\\\",
        "Awaiting an operator & 0 & 0 & 1 \\\\",
    ]


def test_building_writes_the_files_and_pdf_figures(
    evidence: paper_evidence.Evidence, tmp_path: Path
) -> None:
    written = paper_build.build_generated(evidence, tmp_path / "paper")
    tables = {"numbers.tex", "table_kpis.tex", "table_actions.tex", "table_rules.tex"}
    assert {p.name for p in written} == tables | set(paper_figures.FIGURES)
    for path in written:
        assert path.stat().st_size > 0
        if path.suffix == ".pdf":
            assert path.read_bytes().startswith(b"%PDF")


def test_files_that_differ_from_the_evaluation_are_reported(
    evidence: paper_evidence.Evidence, tmp_path: Path
) -> None:
    out = tmp_path / "paper"
    assert paper_build.out_of_date(evidence, out) == [
        "numbers.tex",
        "table_kpis.tex",
        "table_actions.tex",
        "table_rules.tex",
    ]
    paper_build.build_generated(evidence, out)
    assert paper_build.out_of_date(evidence, out) == []
    numbers = out / "generated" / "numbers.tex"
    numbers.write_text(numbers.read_text().replace("{8.6}", "{9.9}"))  # a hand-typed result
    assert paper_build.out_of_date(evidence, out) == ["numbers.tex"]


def test_a_stale_paper_fails_the_check(
    evidence: paper_evidence.Evidence, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(paper_build, "ROOT", tmp_path)
    monkeypatch.setattr(paper_build, "PAPER", tmp_path / "paper")
    loads: list[dict[str, bool]] = []

    def load(**options: bool) -> paper_evidence.Evidence:
        loads.append(options)
        return evidence

    monkeypatch.setattr(paper_build, "load_evidence", load)
    skip = dict.fromkeys(paper_figures.FIGURES, lambda ev, path: None)  # drawn in test_building_
    monkeypatch.setattr(paper_build, "FIGURES", skip)
    assert paper_build.main(["--check"]) == 1  # nothing generated yet
    assert paper_build.main(["--no-pdf"]) == 0
    assert paper_build.main(["--check"]) == 0
    # the check compares text only, so it skips the figures' telemetry (most of the loading)
    assert loads == [{"series": False}, {"series": True}, {"series": False}]


def test_a_missing_evaluation_file_is_named(tree: Path) -> None:
    (tree / "models" / "twin" / "v1" / "validation.json").unlink()
    with pytest.raises(FileNotFoundError, match=r"validation\.json"):
        paper_evidence.load_evidence(tree)


def test_values_are_escaped_for_latex() -> None:
    text = paper_build.render_numbers({"Verdict": "not_met", "Share": "5%", "Mix": "a&b"})
    assert "\\newcommand{\\Verdict}{not\\_met}" in text
    assert "\\newcommand{\\Share}{5\\%}" in text
    assert "\\newcommand{\\Mix}{a\\&b}" in text


def test_a_missing_evaluation_file_stops_the_build_with_its_name(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def missing(**_: bool) -> paper_evidence.Evidence:
        raise FileNotFoundError("models/twin/v1/validation.json")

    monkeypatch.setattr(paper_build, "load_evidence", missing)
    assert paper_build.main(["--check"]) == 1
    assert "validation.json" in caplog.text


def _kpis(
    thr: float = 0.5, lat: float = 12.0, loss: float = 20.0, jain: float = 0.5
) -> dict[str, float]:
    return {"throughput_mbps": thr, "latency_ms": lat, "loss_pct": loss, "jain": jain}


# CASES[0..5]: (status, twin accepted, predicted KPIs, KPIs the watch measured), baseline _kpis()
CASES = [
    ("kept", True, _kpis(thr=0.55), _kpis(thr=0.6)),  # throughput +10%
    (
        "rolled_back",
        True,
        _kpis(thr=0.55, loss=26.0),
        _kpis(thr=0.55),
    ),  # +10% throughput, loss 30% worse
    ("rolled_back", True, _kpis(), None),  # no change predicted
    ("rollback_failed", False, _kpis(0.45, 13.2, 22.0), None),  # everything 10% worse
    ("kept", False, _kpis(loss=22.0), None),  # loss 10% worse
    ("applied", True, _kpis(), None),  # still watched when the run ended: not resolved
]


def _verdict_ledger(path: Path, cases: Sequence[tuple[Any, ...]] = CASES) -> list[ActionRecord]:
    db = Ledger(path)
    for i, (status, accepted, predicted, measured) in enumerate(cases):
        action = ACTION_ADAPTER.validate_python(STEER | {"action_id": f"act_case_{i}"})
        verdict = Verdict.model_validate(
            {
                "action_id": action.action_id,
                "accepted": accepted,
                "predicted": predicted,
                "baseline": _kpis(),
                "violations": [] if accepted else ["worse"],
                "impact": "medium",
                "needs_approval": False,
                "sim_mode": "analytical",
                "sim_time_ms": 0.5,
            }
        )
        db.add([action], [verdict], T0)
        db.update(action.action_id, status, T0, applied_at=T0)
        if measured is not None:
            db.set_measured(action.action_id, KPIValues.model_validate(measured))
    return read_records(path)


@pytest.fixture
def judged(evidence: paper_evidence.Evidence, tmp_path: Path) -> paper_evidence.Evidence:
    """The fixture evaluation with V2's ledger replaced by the five judged actions above, and V3's
    by one action the twin accepted that turned out harmful (V3 only applies accepted actions)."""
    v2 = _verdict_ledger(tmp_path / "judged" / "actions.db")
    v3_cases = [
        ("rolled_back", True, _kpis(jain=0.6), None)
    ]  # only fairness +20%: the rule accepts
    v3 = _verdict_ledger(tmp_path / "judged-v3" / "actions.db", v3_cases)
    ledgers = {"V1": {}, "V2": {"ap_failure-v2-s42": v2}, "V3": {"ap_failure-v3-s42": v3}}
    return dataclasses.replace(evidence, ledgers=ledgers)


def test_harmful_actions_are_counted_by_what_the_twin_said_of_them(
    judged: paper_evidence.Evidence,
) -> None:
    n = paper_build.numbers(judged)
    # harmful = rolled back or rollback failed: CASES[1], [2] (twin accepted) and [3] (rejected);
    # the still-watched action is not resolved, so it is neither harmful nor kept
    # V2 only: V3 applies accepted actions alone, so counting its harmful ones among those the
    # twin "missed" would bias the rejection rate against the twin; they are given apart
    assert (n["HarmAll"], n["HarmRejected"], n["HarmAccepted"]) == ("3", "1", "2")
    assert n["KeptAll"] == "2"
    assert n["HarmVthree"] == "1"  # the one V3 action in the fixture, accepted and harmful


def test_the_counts_of_the_calls_that_were_valid_the_first_time_come_from_the_logs(
    evidence: paper_evidence.Evidence,
) -> None:
    n = paper_build.numbers(evidence)
    # calls: attempt 1 valid, attempt 1 invalid, attempt 2 (no 'valid' field), local attempt 1
    assert (n["IntCalls"], n["IntRepairs"], n["IntFirstValid"]) == ("4", "1", "1")


def test_a_measurement_of_zero_has_no_relative_error_and_is_left_out_and_counted(
    tmp_path: Path,
) -> None:
    cases = [
        ("kept", True, _kpis(loss=5.0), _kpis(loss=0.0)),  # loss measured at 0%: no relative error
        ("kept", True, _kpis(loss=5.0), _kpis(loss=10.0)),  # |5 - 10| / 10 = 50%
    ]
    records = _verdict_ledger(tmp_path / "zero" / "actions.db", cases)
    live = paper_build._live_error_numbers(records)
    assert (live["LiveN"], live["LiveLossN"], live["LiveThrN"]) == ("2", "1", "2")
    assert live["LiveLossErr"] == "50.0"


def test_v2s_harm_rate_is_given_for_actions_the_twin_rejected_and_accepted(
    judged: paper_evidence.Evidence,
) -> None:
    n = paper_build.numbers(judged)
    # V2 applies whatever the verdict. Resolved: the twin rejected CASES[3] (harmful) and
    # CASES[4] (kept); it accepted CASES[0] (kept), [1] and [2] (harmful)
    assert (n["VtwoRejHarm"], n["VtwoRejTotal"]) == ("1", "2")
    assert (n["VtwoAccHarm"], n["VtwoAccTotal"]) == ("2", "3")


def test_stricter_verifier_rules_are_tried_on_the_recorded_actions(
    judged: paper_evidence.Evidence,
) -> None:
    n = paper_build.numbers(judged)
    # as written (no KPI >5% worse, or one >5% better): rejects only CASES[3] of the harmful
    # and CASES[4] of the kept; the recorded verdicts agree with it on all six resolved actions
    # (V2's five and the one V3 action)
    assert (n["RuleWrittenHarm"], n["RuleWrittenKept"]) == ("1", "1")
    assert (n["RuleAgree"], n["RuleTotal"]) == ("6", "6")
    # no KPI more than 5% worse: also rejects CASES[1] (loss 30% worse)
    assert (n["RuleNoRegHarm"], n["RuleNoRegKept"]) == ("2", "1")
    # and one KPI more than 5% better: also rejects CASES[2] (no improvement predicted)
    assert (n["RuleConjHarm"], n["RuleConjKept"]) == ("3", "1")
    # as written but over throughput and Jain's index only: CASES[3] (throughput 10% worse, no
    # gain) is the one harmful action rejected; the kept ones are accepted (loss is not looked at)
    assert (n["RuleThrJainHarm"], n["RuleThrJainKept"]) == ("1", "0")
    # as written, but a gain in Jain's index alone does not pass the "one better" clause: no
    # V2 action of the fixture was accepted on Jain's index alone, so the same as written
    assert (n["RuleNoJainHarm"], n["RuleNoJainKept"]) == ("1", "1")


def test_a_gain_in_jains_index_alone_does_not_pass_the_rule_without_it(tmp_path: Path) -> None:
    cases = [
        ("kept", True, _kpis(loss=22.0, jain=0.6), None),  # loss 10% worse, Jain's index +20%
        ("kept", True, _kpis(thr=0.55, loss=22.0), None),  # loss 10% worse, throughput +10%
    ]
    records = _verdict_ledger(tmp_path / "jain" / "actions.db", cases)
    assert [paper_build.RULES["Written"](r) for r in records] == [True, True]
    assert [paper_build.RULES["NoJain"](r) for r in records] == [False, True]


def test_the_rules_are_also_scored_on_the_actions_the_disruption_did_not_overlap(
    judged: paper_evidence.Evidence,
) -> None:
    # the fixture's actions are applied 230 s into an ap_failure run, 10 s before its disruption:
    # all judged across it, so none is clear of it
    n = paper_build.numbers(judged)
    assert (n["HarmClearVtwo"], n["KeptClearVtwo"]) == ("0", "0")
    assert (n["RuleWrittenHarmClear"], n["RuleWrittenKeptClear"]) == ("0", "0")
    assert "1 of 3 (0 of 0)" in paper_build.table_rules(judged)
    # 100 s earlier (130 s into the run) the watch and its baseline window end before 240 s
    early = paper_build.numbers(_started(judged, 100.0))
    assert (early["HarmClearVtwo"], early["KeptClearVtwo"]) == ("3", "2")
    assert (early["RuleNoRegHarmClear"], early["RuleNoRegKeptClear"]) == ("2", "1")


def test_the_closed_loop_error_is_also_given_per_variant(judged: paper_evidence.Evidence) -> None:
    n = paper_build.numbers(judged)
    # V2's measured actions are CASES[0] and [1]; V3's one action has no measurement
    assert (n["LiveVtwoN"], n["LiveVtwoThrErr"], n["LiveVtwoThrBase"]) == ("2", "4.2", "12.9")
    assert (n["LiveVthreeN"], n["LiveVthreeThrErr"]) == ("0", "n/a")


def test_the_predicted_regressions_of_the_harmful_actions_are_counted(
    judged: paper_evidence.Evidence,
) -> None:
    n = paper_build.numbers(judged)
    # V2's harmful actions are CASES[1] (loss 30% worse), [2] (no change) and [3] (all 10% worse):
    # two had a predicted regression of some size, one had none at all
    assert n["HarmAnyRegress"] == "2"
    # accepted only because Jain's index (client counts) was predicted to improve: V3's action
    assert n["HarmJainOnly"] == "1"


def _started(ev: paper_evidence.Evidence, seconds: float) -> paper_evidence.Evidence:
    """`ev` with every run started `seconds` later (its actions are then that much earlier)."""
    moved = {
        mode: {run: start + timedelta(seconds=seconds) for run, start in runs.items()}
        for mode, runs in ev.run_starts.items()
    }
    return dataclasses.replace(ev, run_starts=moved)


def test_harmful_actions_judged_across_the_scheduled_disruption_are_counted(
    judged: paper_evidence.Evidence,
) -> None:
    # every action of the fixture is applied 230 s into an ap_failure run (disruption at 240 s,
    # watch and baseline window 30 s each): the four harmful ones (V2's three, V3's one) are
    # judged over it, and V2's twin rejected one of the three
    n = paper_build.numbers(judged)
    assert (n["HarmStraddle"], n["HarmStraddleVtwo"], n["HarmClearVtwo"]) == ("4", "3", "0")


def test_the_disruption_taints_a_verdict_before_and_after_the_action(
    judged: paper_evidence.Evidence,
) -> None:
    # 15 s later in the run (245 s): the disruption is 5 s *before* the action, in the baseline
    after = paper_build.numbers(_started(judged, -15))
    assert (after["HarmStraddle"], after["HarmClearVtwo"]) == ("4", "0")
    # 100 s earlier in the run (130 s): the watch ends at 160 s, before the disruption
    early = paper_build.numbers(_started(judged, 100))
    assert (early["HarmStraddle"], early["HarmClearVtwo"]) == ("0", "3")
    assert early["HarmClearRejected"] == "1"  # the one the twin rejected, now clear of the fault
    # 100 s later in the run (330 s): the baseline window (300 to 330 s) is clear of it too
    late = paper_build.numbers(_started(judged, -100))
    assert late["HarmStraddle"] == "0"


def test_the_closed_loop_error_is_also_given_for_the_actions_the_disruption_did_not_taint(
    judged: paper_evidence.Evidence,
) -> None:
    # all actions are judged across the disruption: none is clear of it
    assert paper_build.numbers(judged)["LiveClearN"] == "0"
    # 100 s earlier in the run they are all clear, so the error is the one over all of them
    n = paper_build.numbers(_started(judged, 100))
    assert n["LiveClearN"] == n["LiveN"] == "2"
    assert (n["LiveClearThrErr"], n["LiveClearThrBase"]) == (n["LiveThrErr"], n["LiveThrBase"])


def test_kept_actions_judged_across_the_disruption_are_counted(
    judged: paper_evidence.Evidence,
) -> None:
    assert paper_build.numbers(judged)["KeptStraddleVtwo"] == "2"  # V2's two kept actions


def test_the_action_table_says_how_many_rejections_v2_ignored(
    judged: paper_evidence.Evidence,
) -> None:
    rows = paper_build.table_actions(judged).splitlines()
    rejected = next(r for r in rows if r.startswith("Rejected, not applied"))
    assert rejected == "Rejected, not applied & 0 & 0 (2 ignored) & 0 \\\\"


def test_actions_applied_in_one_tick_are_counted_as_a_group(
    judged: paper_evidence.Evidence,
) -> None:
    # V2's ledger applies five actions at one instant (one tick); V3's single action is alone
    assert paper_build.numbers(judged)["TickMulti"] == "1"


def test_the_intents_are_split_into_single_clause_and_compound_ones(
    evidence: paper_evidence.Evidence,
) -> None:
    n = paper_build.numbers(evidence)
    assert (n["IntSimple"], n["IntCompound"]) == ("17", "13")  # i12 to i24 have a second clause
    # the fixture's local model missed i01 (simple) and i12 (compound)
    assert (n["IntLocalSimpleOk"], n["IntLocalCompoundOk"]) == ("16", "12")


def test_ap1_and_ap4_start_with_the_capacity_their_shared_channel_leaves(
    evidence: paper_evidence.Evidence,
) -> None:
    # 50 m apart on channel 1: w = (60 - 50) / (60 - 30) = 1/3, so 4.6 / (1 + 1/3) = 3.45
    assert paper_build.numbers(evidence)["CfgSharedCapacity"] == "3.45"


def test_h1_is_decided_on_the_capped_recovery_times(judged: paper_evidence.Evidence) -> None:
    assert paper_build.numbers(judged)["HoneCapped"] == "not met"  # 7.86% in every scenario


def test_h1_is_met_only_if_every_scenario_reaches_the_target(
    evidence: paper_evidence.Evidence,
) -> None:
    def with_speedups(*speedups: float) -> paper_evidence.Evidence:
        h1 = {
            s: {"faster_pct": pct, "verdict": "x", "v1_s": 1.0, "v3_s": 1.0}
            for s, pct in zip(SCENARIOS, speedups, strict=True)
        }
        return dataclasses.replace(evidence, results=evidence.results | {"h1": h1})

    assert paper_build.numbers(with_speedups(30.0, 45.0, 90.0))["HoneCapped"] == "met"
    assert paper_build.numbers(with_speedups(30.0, 45.0, 29.9))["HoneCapped"] == "not met"


def test_a_cell_without_any_value_has_no_range(evidence: paper_evidence.Evidence) -> None:
    runs = {k: [{**r, "loss_pct": None} for r in v] for k, v in evidence.results["runs"].items()}
    empty = dataclasses.replace(evidence, results=evidence.results | {"runs": runs})
    with pytest.raises(ValueError, match="no run of V1/"):
        paper_evidence.kpi_range(empty, "V1", SCENARIOS[0], "loss_pct")


def test_every_mean_of_the_recorded_evaluation_lies_in_its_range_over_the_seeds() -> None:
    ev = paper_evidence.load_evidence()
    for (mode, scenario, kpi), cell in paper_evidence.kpi_cells(ev).items():
        low, high = paper_evidence.kpi_range(ev, mode, scenario, kpi)
        assert low - 1e-9 <= cell["mean"] <= high + 1e-9, (mode, scenario, kpi)


def test_the_kpi_table_gives_the_range_over_the_seeds_not_an_interval(
    evidence: paper_evidence.Evidence,
) -> None:
    body = paper_build.table_kpis(evidence)
    assert "9.2 [1.0--3.0]" in body  # loss of the three runs of a cell: 1, 2 and 3
    assert "\\pm" not in body


def test_the_range_of_a_cell_counts_a_run_that_never_recovered_at_its_run_end(
    evidence: paper_evidence.Evidence,
) -> None:
    assert paper_evidence.kpi_range(evidence, "V2", SCENARIOS[0], "ttr_s") == (100.0, 390.0)
    assert paper_evidence.kpi_range(evidence, "V1", SCENARIOS[0], "ttr_s") == (390.0, 390.0)


def test_the_twins_prediction_is_compared_with_what_the_watch_measured(
    judged: paper_evidence.Evidence,
) -> None:
    n = paper_build.numbers(judged)
    assert n["LiveN"] == "2"  # two resolved actions have a measurement
    # throughput: predicted 0.55 against measured 0.6 and 0.55: errors 8.33% and 0%, median 4.2;
    # the baseline 0.5 against the same: 16.67% and 9.09%, median 12.9
    assert (n["LiveThrErr"], n["LiveThrBase"]) == ("4.2", "12.9")
    # latency: predicted and baseline 12 against measured 12 and 12: both errors 0
    assert n["LiveLatErr"] == n["LiveLatBase"] == "0.0"
    # loss: predicted 20 and 26 against measured 20 and 20 -> 0% and 30%, median 15.0; baseline 0.0
    assert (n["LiveLossErr"], n["LiveLossBase"]) == ("15.0", "0.0")
    assert (n["LiveJainErr"], n["LiveJainBase"]) == ("0.0", "0.0")


def test_fisher_exact_test_matches_the_textbook_tea_tasting_example() -> None:
    assert paper_build.fisher_one_sided(3, 1, 1, 3) == pytest.approx(17 / 70)  # Fisher 1935
    assert paper_build.fisher_one_sided(4, 0, 0, 4) == pytest.approx(1 / 70)
    assert paper_build.fisher_one_sided(0, 4, 4, 0) == pytest.approx(1.0)


def test_runs_are_summarised_per_seed_and_by_how_many_recovered(
    evidence: paper_evidence.Evidence,
) -> None:
    n = paper_build.numbers(evidence)
    assert n["PerSeedLossApFailVtwo"] == "1.0, 2.0, 3.0"
    assert n["PerSeedLatApFailVthree"] == "10, 20, 30"
    assert (n["RecovVone"], n["RecovVtwo"], n["RecovVthree"]) == ("0", "6", "6")  # of nine


def test_intent_retries_and_the_latency_cap_come_from_the_logs_and_the_config(
    evidence: paper_evidence.Evidence,
) -> None:
    n = paper_build.numbers(evidence)
    assert (n["IntCalls"], n["IntRepairs"]) == ("4", "1")  # one call needed a second attempt
    assert (n["CfgBaseLoss"], n["CfgFetch"], n["CfgBulk"]) == ("0.2", "0.8", "0.394")
    assert n["CfgLatCap"] == "15.8"  # 0.8 + 2.5 x 6: the most the model can predict


def test_the_rules_table_shows_what_each_rule_would_have_blocked(
    judged: paper_evidence.Evidence,
) -> None:
    # in brackets, the actions the disruption did not taint: here, applied 130 s into the run,
    # all of them (the fixture's own 230 s puts every one inside the disruption's window)
    table = paper_build.table_rules(_started(judged, 100.0))
    rows = [line for line in table.splitlines() if line.endswith("\\\\")]
    assert rows == [
        "Acceptance rule & Harmful rejected & Kept rejected \\\\",
        "As written (no KPI $>$5\\% worse, or one $>$5\\% better)"
        " & 1 of 3 (1 of 3) & 1 of 2 (1 of 2) \\\\",
        "No KPI more than 5\\% worse & 2 of 3 (2 of 3) & 1 of 2 (1 of 2) \\\\",
        "No KPI more than 5\\% worse and one more than 5\\% better"
        " & 3 of 3 (3 of 3) & 1 of 2 (1 of 2) \\\\",
        "As written, on throughput and Jain's index only & 1 of 3 (1 of 3) & 0 of 2 (0 of 2) \\\\",
        "As written, but Jain's index alone cannot make it pass"
        " & 1 of 3 (1 of 3) & 1 of 2 (1 of 2) \\\\",
    ]
    assert "table_rules.tex" in paper_build.texts(judged)


def test_the_check_reads_no_telemetry(monkeypatch: pytest.MonkeyPatch) -> None:
    asked: dict[str, bool] = {}

    def load(*, series: bool) -> paper_evidence.Evidence:
        asked["series"] = series
        raise FileNotFoundError("stop here")  # what was asked for is all this test needs

    monkeypatch.setattr(paper_build, "load_evidence", load)
    assert paper_build.main(["--check"]) == 1
    assert asked == {"series": False}  # the generated text never reads it: the check stays fast


def test_the_starting_stations_and_each_scenarios_video_come_from_the_configuration(
    evidence: paper_evidence.Evidence,
) -> None:
    n = paper_build.numbers(evidence)
    # config/campus_v1.yaml stations.initial, in the order of the APs (ap1 to ap4, one per zone)
    assert n["CfgStartClients"] == "3, 5, 7 and 5"
    # experiments/scenarios/*.yaml: the rate of the video every scenario adds to the web traffic
    video = (n["ScenVideoFlash"], n["ScenVideoApFail"], n["ScenVideoCochan"])
    assert video == ("0.4", "0.6", "0.4")


def test_the_flash_crowds_false_alarms_before_the_onset_come_from_the_detection_metrics(
    evidence: paper_evidence.Evidence,
) -> None:
    # models/anomaly/v1/metrics.json test_detection, the flash crowd's test run (fixture: 12)
    assert paper_build.numbers(evidence)["AnoFalseFlash"] == "12"


def test_a_scenario_whose_video_items_differ_in_rate_has_no_one_rate_to_quote(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flash = load_scenario("lecture_flash_crowd")
    video = next(t for t in flash.traffic if t.profile == "video")
    for other in (0.9, None):  # a second, different rate; or one left to the profile
        mixed = flash.model_copy(
            update={"traffic": [*flash.traffic, video.model_copy(update={"rate_mbps": other})]}
        )
        monkeypatch.setattr(paper_build, "load_scenario", lambda _, s=mixed: s)
        with pytest.raises(ValueError, match="one stated video rate"):
            paper_build.video_rate("lecture_flash_crowd")


def _noted(ev: paper_evidence.Evidence, notes: Sequence[str]) -> paper_evidence.Evidence:
    """`ev` with its harmful actions (V2's, then V3's) given these rollback notes, in order."""
    queue = list(notes)
    ledgers = {
        mode: {
            run: [
                dataclasses.replace(r, note=queue.pop(0))
                if r.status in paper_evidence.HARMFUL
                else r
                for r in records
            ]
            for run, records in runs.items()
        }
        for mode, runs in ev.ledgers.items()
    }
    return dataclasses.replace(ev, ledgers=ledgers)


def test_the_kpis_that_triggered_each_rollback_come_from_the_executors_notes(
    judged: paper_evidence.Evidence,
) -> None:
    # the judged fixture's harmful actions: V2's CASES[1], [2], [3], then V3's one
    ev = _noted(
        judged,
        [
            "throughput_mbps 1.0 -> 0.8 (worse by more than 10%)",
            "throughput_mbps 1.0 -> 0.8 (worse by more than 10%); loss_pct 1 -> 2 (worse ...)",
            "latency_ms 12 -> 24 (worse by more than 10%)",
            "loss_pct 1 -> 3 (worse by more than 10%); jain 0.9 -> 0.7 (worse ...)",
        ],
    )
    n = paper_build.numbers(ev)
    assert n["RbTrigN"] == "4"
    assert (n["RbTrigThr"], n["RbTrigLat"], n["RbTrigLoss"], n["RbTrigJain"]) == (
        "2",
        "1",
        "2",
        "1",
    )


def test_harmful_actions_are_also_counted_by_start_up_and_by_the_gain_that_passed_them(
    judged: paper_evidence.Evidence,
) -> None:
    # the fixture's actions are applied 230 s into the run: no start-up action; V2's harmful
    # actions passed by "no KPI more than 5% worse" are CASES[2] (no change predicted: no gain)
    n = paper_build.numbers(judged)
    assert n["HarmStartupVtwo"] == "0"
    assert (n["HarmNoRegN"], n["HarmNoRegLatGain"]) == ("1", "0")
    early = paper_build.numbers(_started(judged, 200.0))  # 30 s into the run
    assert early["HarmStartupVtwo"] == "3"
    assert early["KeptStraddleVthree"] == "0"  # V3's one action is harmful, not kept


def test_ap_failure_channel_changes_are_counted_by_what_each_variant_did_with_them(
    judged: paper_evidence.Evidence,
) -> None:
    change = ACTION_ADAPTER.validate_python(
        STEER
        | {"type": "set_ap_channel", "params": {"ap": "ap1", "channel": 6}}
        | {"action_id": "act_chan_1"}
    )
    record = dataclasses.replace(judged.ledgers["V2"]["ap_failure-v2-s42"][0], action=change)
    v2 = dataclasses.replace(record, status="kept")
    v3 = dataclasses.replace(record, status="verified")  # waiting for an operator
    ledgers = {"V1": {}, "V2": {"ap_failure-v2-s42": [v2]}, "V3": {"ap_failure-v3-s42": [v3]}}
    n = paper_build.numbers(dataclasses.replace(judged, ledgers=ledgers))
    assert (n["ChanApFailVtwoApplied"], n["ChanApFailVthreeWaiting"]) == ("1", "1")
