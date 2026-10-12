"""P6.6 results (experiments/analysis/results.py): tables per mode and scenario, and H1."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from experiments.analysis import results
from experiments.analysis.campaign import RunKpis, StressWindow
from experiments.analysis.results import h1, kpi_table, markdown, stress_window
from experiments.batch import load_scenario


def _run(ttr: float | None, throughput: float = 1.0) -> RunKpis:
    return RunKpis("ap1", ttr, 300.0, throughput, 20.0, 1.0, 0.8)


def test_the_table_has_one_row_per_mode_scenario_and_kpi_with_never_recovered_counted() -> None:
    runs = {("V1", "ap_failure"): [_run(None), _run(200.0), _run(100.0)]}
    rows = {r["kpi"]: r for r in kpi_table(runs)}
    assert list(rows) == ["ttr_s", "throughput_mbps", "latency_p95_ms", "loss_pct", "jain"]
    ttr = rows["ttr_s"]
    assert (ttr["mode"], ttr["scenario"], ttr["n"], ttr["never"]) == ("V1", "ap_failure", 3, 1)
    assert ttr["mean"] == pytest.approx(200.0)  # a run that never recovered counts as its end
    assert rows["throughput_mbps"]["never"] == 0


@pytest.mark.parametrize(
    ("scenario", "expected"),
    [
        ("lecture_flash_crowd", StressWindow(210.0, 600.0, None)),  # the crowd's video starts
        ("ap_failure", StressWindow(240.0, 600.0, "ap2")),
        ("cochannel_interference", StressWindow(180.0, 600.0, "ap3")),
    ],
)
def test_each_scenario_has_its_stress_window(scenario: str, expected: StressWindow) -> None:
    assert stress_window(load_scenario(scenario)) == expected


def test_a_scenario_without_a_disruption_has_no_stress_window() -> None:
    with pytest.raises(ValueError, match="normal"):
        stress_window(load_scenario("normal"))


def test_flash_crowd_fairness_is_checked_against_its_target_per_mode() -> None:
    # §5.1: Jain >= 0.8 during the flash crowd
    runs = {
        ("V1", "lecture_flash_crowd"): [_run(None)],  # jain 0.8 in _run
        ("V3", "lecture_flash_crowd"): [RunKpis("ap1", 100.0, 300.0, 1.0, 20.0, 1.0, 0.9)],
        ("V3", "ap_failure"): [RunKpis("ap1", 100.0, 300.0, 1.0, 20.0, 1.0, 0.1)],  # not judged
    }
    assert results.fairness(kpi_table(runs)) == {
        "V1": {"jain": pytest.approx(0.8), "target_met": True},
        "V3": {"jain": pytest.approx(0.9), "target_met": True},
    }


def test_twin_mape_is_the_held_out_test_split_in_percent(tmp_path: Path) -> None:
    validation = {"after_calibration": {"test": {"all": {"mape": 0.0449, "n": 586}}}}
    (tmp_path / "validation.json").write_text(json.dumps(validation))
    assert results.twin_mape(tmp_path / "validation.json") == {"mape_pct": 4.49, "n": 586}
    assert results.twin_mape(tmp_path / "missing.json") is None


def test_the_report_has_genai_twin_and_fairness_sections() -> None:
    report = {
        "table": [],
        "h1": {},
        "safety": {},
        "fairness": {"V3": {"jain": 0.78, "target_met": False}},
        "twin": {"mape_pct": 4.49, "n": 586},
        "genai": {
            "intents": {
                "accuracy": 29 / 30,
                "correct": 29,
                "cases": 30,
                "schema_valid": 30,
                "latency": {"p95_s": 2.5, "under_10_s": 1.0},
                "calls": {"cloud": {"calls": 31, "valid_first_try": 0.97, "invalid_caught": 1}},
            }
        },
    }
    text = markdown(report)
    assert "| V3 | 0.78 | not met |" in text
    assert "4.49% over 586 predictions" in text
    assert "| intents | 29/30 (96.7%) | 30/30 | 2.50 | 100% | 1 |" in text


def test_only_runs_that_passed_count_towards_h2_with_the_harmful_share(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # the KPI tables use the exported (passed) runs only; H2 must count the same runs
    for run_id in ("ap_failure-v2-s42", "ap_failure-v2-s43"):
        (tmp_path / run_id).mkdir()
        (tmp_path / run_id / "actions.db").touch()
    runs = [
        {"run_id": "ap_failure-v2-s42", "passed": True, "scenario_ok": True},
        {"run_id": "ap_failure-v2-s43", "passed": False, "scenario_ok": True},
    ]
    (tmp_path / "batch.json").write_text(json.dumps({"runs": runs}))
    monkeypatch.setattr(results, "read_records", lambda db: [db.parent.name])
    monkeypatch.setattr(
        results, "audit", lambda records: {"applied": 4, "harmful_twin_rejected": 1}
    )
    counts = results.ledger_counts(tmp_path)
    assert counts == {"runs": 1, "applied": 4, "harmful_twin_rejected": 1, "harmful_pct": 25.0}


def test_the_safety_table_names_every_count_even_when_a_mode_has_no_ledgers() -> None:
    # a mode whose runs had no loop (no actions.db) sums to nothing: it still gets a row
    counts = {"recorded": 4, "applied": 3, "harmful_twin_rejected": 1}
    text = markdown({"table": [], "h1": {}, "safety": {"V1": {}, "V2": counts}})
    assert "| Mode | recorded | applied | harmful_twin_rejected |" in text
    assert "| V1 | 0 | 0 | 0 |" in text
    assert "| V2 | 4 | 3 | 1 |" in text


def test_h1_is_the_share_by_which_v3_recovers_faster_than_v1_per_scenario() -> None:
    runs = {
        ("V1", "lecture_flash_crowd"): [_run(300.0), _run(300.0), _run(None)],  # 300 = run end
        ("V3", "lecture_flash_crowd"): [_run(150.0), _run(150.0), _run(150.0)],
        ("V1", "ap_failure"): [_run(100.0)],  # no V3 run yet: no verdict
    }
    result = h1(kpi_table(runs))
    assert list(result) == ["lecture_flash_crowd"]
    flash = result["lecture_flash_crowd"]
    assert flash["faster_pct"] == pytest.approx(50.0)
    # >= 30% (problem statement §5.1); V1's censored run only makes the true speed-up larger
    assert flash["verdict"] == "met"
    assert (flash["v1_never"], flash["v3_never"]) == (1, 0)


@pytest.mark.parametrize(
    ("v1", "v3", "verdict"),
    [
        ([200.0, 200.0], [180.0, 180.0], "not met"),  # 10%, nothing censored
        ([200.0, None], [180.0, 180.0], "inconclusive"),  # 10%, but V1 may be far slower
        ([400.0, 400.0], [100.0, None], "inconclusive"),  # 50% is only an upper bound here
        ([200.0, 200.0], [180.0, None], "not met"),  # upper bound already below 30%
        ([0.0, 0.0], [0.0, 0.0], "inconclusive"),  # V1 recovers at once: no speed-up to measure
    ],
)
def test_h1_is_firm_only_where_never_recovered_runs_cannot_change_it(
    v1: list[float | None], v3: list[float | None], verdict: str
) -> None:
    runs = {
        ("V1", "ap_failure"): [_run(t) for t in v1],
        ("V3", "ap_failure"): [_run(t) for t in v3],
    }
    assert h1(kpi_table(runs))["ap_failure"]["verdict"] == verdict
