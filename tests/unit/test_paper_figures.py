"""The IEEE paper's figures (experiments/paper_figures.py): what each draws from the evaluation."""

from __future__ import annotations

import dataclasses
import math
import re
import statistics
from pathlib import Path

import pytest

from common.schemas import KPIValues
from experiments import paper_evidence, paper_figures
from tests.unit.test_paper_build import _kpis, _verdict_ledger

NAN = math.nan
STEP_S = 5.0  # config/loop.yaml period_s, as the figures average
MAIN_TEX = Path(paper_figures.__file__).resolve().parents[1] / "final_submission/paper/main.tex"


def _run(ev: paper_evidence.Evidence, scenario: str) -> paper_evidence.RunSeries:
    return ev.runs("V1", scenario)[0]


def _known(values: list[float]) -> set[float]:
    return {v for v in values if not math.isnan(v)}


def test_rows_are_reduced_per_control_period_and_a_window_without_rows_is_a_gap() -> None:
    rows: list[paper_evidence.Row] = [
        {"t_s": 0.0, "v": 1.0},
        {"t_s": 4.9, "v": 3.0},
        {"t_s": 12.0, "v": 5.0},
        {"t_s": 13.0, "v": None},  # no value: left out
        {"t_s": 99.0, "v": 7.0},  # after the end: left out
    ]
    out = paper_figures.windows(rows, lambda r: r["v"], statistics.fmean, end_s=15.0, step_s=5.0)
    assert len(out) == 3
    assert out[0] == 2.0
    assert math.isnan(out[1])
    assert out[2] == 5.0
    assert paper_figures.midpoints(len(out), 5.0) == [2.5, 7.5, 12.5]  # where each is drawn


def test_runs_are_summarised_per_window_by_their_mean_and_their_range() -> None:
    mean, low, high = paper_figures.across_runs([[1.0, NAN, NAN], [3.0, 2.0, NAN]])
    assert (mean[:2], low[:2], high[:2]) == ([2.0, 2.0], [1.0, 2.0], [3.0, 2.0])
    assert all(math.isnan(v[2]) for v in (mean, low, high))  # no run has a value


def test_the_video_latency_drawn_is_the_nearest_rank_p95_of_each_window() -> None:
    rows = [{"t_s": 1.0, "app_class": "video", "latency_ms": float(v)} for v in range(20, 0, -1)]
    rows.append({"t_s": 1.0, "app_class": "web", "latency_ms": 500.0})  # not video: left out
    run = paper_evidence.RunSeries(
        run_id="r",
        scenario="ap_failure",
        seed=42,
        onset_s=0.0,
        end_s=5.0,
        affected_ap="ap1",
        ap_stats=[],
        affected_kpis=rows,
        start_xy={},
        onset_xy={},
    )
    assert paper_figures.video_p95(run, STEP_S) == [19.0]  # ceil(0.95 * 20) = the 19th value


def test_the_distribution_steps_up_once_per_value() -> None:
    assert paper_figures.ecdf([3.0, 1.0, 2.0]) == ([1.0, 2.0, 3.0], [1 / 3, 2 / 3, 1.0])


def test_direct_labels_are_moved_apart_and_keep_their_order() -> None:
    assert paper_figures.dodge([5.0, 1.0, 1.2, 9.0], gap=1.0) == [5.0, 1.0, 2.0, 9.0]


def test_symmetric_log_limits_hold_every_value_and_have_a_default() -> None:
    assert paper_figures._symlog_limits([]) == (-11.0, 11.0)
    low, high = paper_figures._symlog_limits([-50.0, 3.0, 200.0])
    assert low < -50.0
    assert high > 200.0


def test_the_utilisation_drawn_is_that_of_each_runs_affected_ap(
    evidence: paper_evidence.Evidence,
) -> None:
    run = _run(evidence, "ap_failure")
    assert run.affected_ap == "ap1"  # the busiest after the onset (fixture: 0.9)
    assert _known(paper_figures.utilisation(run, STEP_S)) == {0.9}


def test_latency_and_loss_are_those_of_the_affected_flows_over_the_whole_run(
    evidence: paper_evidence.Evidence,
) -> None:
    run = _run(evidence, "ap_failure")  # affected: the stations of ap2, the AP that fails
    assert {r["flow_id"] for r in run.affected_kpis} == {"sta1-video"}
    assert min(r["t_s"] for r in run.affected_kpis) == 0.0  # before the onset too, for context
    assert _known(paper_figures.video_p95(run, STEP_S)) == {10.0}
    assert _known(paper_figures.mean_loss(run, STEP_S)) == {0.0}


def test_the_clients_of_an_ap_are_drawn_per_window(evidence: paper_evidence.Evidence) -> None:
    run = _run(evidence, "lecture_flash_crowd")
    counts = paper_figures.ap_series(run, "ap1", "n_clients", STEP_S)
    assert (counts[0], counts[-1]) == (1.0, 2.0)  # the fixture's ap1 gains a client at 200 s


def test_fairness_is_jains_index_of_the_client_counts_per_window(
    evidence: paper_evidence.Evidence,
) -> None:
    jain = paper_figures.fairness(_run(evidence, "lecture_flash_crowd"), STEP_S)
    assert len(jain) == 120  # 600 s in 5 s windows
    assert jain[0] == pytest.approx(1.0)  # one client on each of the four APs: even
    assert jain[-1] == pytest.approx(25 / 28)  # ap1 has two: (1+1+1+2)^2 / (4 * (1+1+1+4))


def test_the_walkers_are_the_stations_that_moved_before_the_onset(
    evidence: paper_evidence.Evidence,
) -> None:
    assert paper_figures.walkers(_run(evidence, "lecture_flash_crowd")) == {
        "sta4": ((10.0, 15.0), (40.0, 15.0))
    }


def test_each_action_is_placed_at_the_time_it_was_proposed_with_its_fate(
    evidence: paper_evidence.Evidence,
) -> None:
    times = paper_figures.action_times(evidence, "V3")
    assert list(times) == ["ap_failure-v3-s42"]  # the passed run only
    statuses = ["kept", "rolled_back", "rejected", "verified"]
    assert times["ap_failure-v3-s42"] == [(230.0, s) for s in statuses]


def _measured_from(ev: paper_evidence.Evidence, path: Path, *thr: float) -> paper_evidence.Evidence:
    """V2 runs the actions of CASES, the watch having seen these throughputs before CASES[0],
    [1], ... (Mbit/s) and 0.4 before the rest."""
    records = _verdict_ledger(path)
    seen = [*thr, *[0.4] * (len(records) - len(thr))]
    records = [
        dataclasses.replace(r, baseline=KPIValues.model_validate(_kpis(thr=t)))
        for r, t in zip(records, seen, strict=True)
    ]
    return dataclasses.replace(ev, ledgers={"V1": {}, "V2": {"run": records}, "V3": {}})


def test_predicted_and_measured_changes_are_those_of_resolved_actions_with_a_measurement(
    evidence: paper_evidence.Evidence, tmp_path: Path
) -> None:
    changes = paper_figures.throughput_changes(_measured_from(evidence, tmp_path / "a.db"))
    # CASES[0]: predicted 0.5 -> 0.55 (+10%), measured 0.4 -> 0.6 (+50%), kept
    # CASES[1]: predicted +10%, measured 0.4 -> 0.55 (+37.5%), rolled back; the rest unmeasured
    assert [s for _, _, s in changes] == ["kept", "rolled_back"]
    assert [v for x, y, _ in changes for v in (x, y)] == pytest.approx([10.0, 50.0, 10.0, 37.5])


def test_an_action_measured_from_a_throughput_of_zero_has_no_change_to_draw(
    evidence: paper_evidence.Evidence, tmp_path: Path
) -> None:
    # before CASES[0] (kept) the flows carried nothing; before CASES[1] (rolled back), 0.4
    ev = _measured_from(evidence, tmp_path / "a.db", 0.0)
    assert [s for _, _, s in paper_figures.throughput_changes(ev)] == ["rolled_back"]


def test_intents_are_scored_per_model_and_kind_with_their_times(
    evidence: paper_evidence.Evidence,
) -> None:
    # the fixture's local model missed i01 (single-clause) and i12 (compound)
    assert paper_figures.intent_results(evidence) == {
        "cloud-model": ({"single-clause": (17, 17), "compound": (13, 13)}, [1.0, 2.0, 3.0]),
        "local-model": ({"single-clause": (16, 17), "compound": (12, 13)}, [2.0, 4.0]),
    }


def test_first_alerts_are_keyed_by_scenario_and_two_test_runs_of_one_are_refused(
    evidence: paper_evidence.Evidence,
) -> None:
    assert paper_figures.detections(evidence)["lecture_flash_crowd"]["false_alarms_before"] == 12
    twice = dict(evidence.anomaly["test_detection"]) | {"ap_failure-s45": {"delay_s": 1.0}}
    doubled = dataclasses.replace(evidence, anomaly={"test_detection": twice})
    with pytest.raises(ValueError, match="two test runs of ap_failure"):
        paper_figures.detections(doubled)


def test_a_test_run_outside_the_campaign_scenarios_has_no_first_alert_to_draw(
    evidence: paper_evidence.Evidence,
) -> None:
    normal = dict(evidence.anomaly["test_detection"]) | {"normal-s44": {"delay_s": 1.0}}
    ev = dataclasses.replace(evidence, anomaly={"test_detection": normal})
    assert set(paper_figures.detections(ev)) == set(paper_evidence.SCENARIOS)


def test_the_paper_includes_every_generated_figure_and_no_other() -> None:
    included = set(re.findall(r"\\includegraphics\{figures/([\w.]+)\}", MAIN_TEX.read_text()))
    assert included == set(paper_figures.FIGURES)


@pytest.mark.parametrize("name", list(paper_figures.FIGURES))
def test_every_figure_is_a_pdf_that_a_rebuild_reproduces_byte_for_byte(
    evidence: paper_evidence.Evidence, tmp_path: Path, name: str
) -> None:
    first, second = tmp_path / "first.pdf", tmp_path / "second.pdf"
    paper_figures.FIGURES[name](evidence, first)
    paper_figures.FIGURES[name](evidence, second)
    assert first.read_bytes().startswith(b"%PDF")
    assert first.read_bytes() == second.read_bytes()  # no creation date: no noise in git
