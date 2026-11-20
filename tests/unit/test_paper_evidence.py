"""The definitions the IEEE paper's numbers and figures share (experiments/paper_evidence.py)."""

from __future__ import annotations

from pathlib import Path

import pytest

from experiments import paper_evidence
from twin.radio import load_radio_params

# the fixture tree carries the real, tracked config/: its campus is the paper's


def test_the_campus_has_one_same_channel_pair_ap1_and_ap4_50_m_apart(
    evidence: paper_evidence.Evidence,
) -> None:
    [(a, b, distance_m)] = paper_evidence.cochannel_pairs(evidence.config["campus_v1"])
    assert (a, b) == ("ap1", "ap4")
    assert distance_m == pytest.approx(50.0)  # (20, 50) to (60, 20): a 3-4-5 triangle


@pytest.mark.parametrize(
    ("distances_m", "mbps"),
    [
        ([], 4.6),  # no neighbour: the nominal capacity
        ([50.0], 3.45),  # a third of a share between 30 m and 60 m: 4.6 / (1 + 1/3)
        ([20.0, 20.0], 1.53),  # two full shares: 4.6 / 3
    ],
)
def test_capacity_follows_eq_1_for_the_worked_examples(
    evidence: paper_evidence.Evidence, distances_m: list[float], mbps: float
) -> None:
    radio = load_radio_params(evidence.config["campus_v1"])
    assert paper_evidence.capacity_mbps(distances_m, radio) == pytest.approx(mbps, abs=0.005)


def test_resolved_actions_are_the_applied_ones_the_watch_decided(
    evidence: paper_evidence.Evidence,
) -> None:
    # the fixture's passed runs: V2 kept, kept, rolled back, still watched, rollback failed;
    # V3 kept, rolled back, rejected, awaiting an operator; V1 proposes nothing
    statuses = [r.status for r in paper_evidence.resolved_actions(evidence)]
    assert statuses == ["kept", "kept", "rolled_back", "rollback_failed", "kept", "rolled_back"]


def test_prediction_times_are_those_of_every_verdict_of_the_passed_runs(
    evidence: paper_evidence.Evidence,
) -> None:
    # rejected and waiting actions have a verdict too; the failed run's ledger (0.1) is left out
    assert paper_evidence.prediction_times(evidence) == [0.1, 0.3, 0.2, 0.2, 0.2] + [0.5] * 4


def test_the_runs_of_a_variant_and_scenario_are_its_campaign_runs_only(
    evidence: paper_evidence.Evidence,
) -> None:
    [run] = evidence.runs("V2", "ap_failure")
    assert (run.run_id, run.scenario, run.seed) == ("ap_failure-v2-s42", "ap_failure", 42)
    assert evidence.runs("V2", "normal") == []


def test_evidence_loaded_without_series_has_no_telemetry_but_the_same_ledgers(
    tree: Path, evidence: paper_evidence.Evidence
) -> None:
    text_only = paper_evidence.load_evidence(tree, series=False)
    assert text_only.series == {mode: [] for mode in evidence.series}
    assert text_only.ledgers == evidence.ledgers
