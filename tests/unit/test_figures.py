"""P6.6 figures (experiments/analysis/figures.py): drawn from the results table, no network."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from experiments.analysis.figures import error_bar, kpi_figure, value_label
from experiments.analysis.results import KPIS


def _rows() -> list[dict[str, Any]]:
    rows = []
    for mode, scale in (("V1", 1.0), ("V2", 0.8), ("V3", 0.5)):
        for kpi in KPIS:
            rows.append(
                {
                    "mode": mode,
                    "scenario": "ap_failure",
                    "kpi": kpi,
                    "mean": 10.0 * scale,
                    "ci95": 2.0,
                    "n": 3,
                    "never": 1 if (mode, kpi) == ("V1", "ttr_s") else 0,
                    "high": 12.0 if kpi == "ttr_s" else None,
                }
            )
    rows.append(
        {
            "mode": "V2",
            "scenario": "ap_failure",
            "kpi": "jain",
            "mean": None,
            "ci95": None,
            "n": 0,
            "never": 0,
            "high": None,
        }
    )  # a mode without samples: no point
    rows[0] = rows[0] | {"ci95": None, "n": 1}  # one run: no interval
    return rows


def test_a_scenario_figure_is_written_as_png(tmp_path: Path) -> None:
    path = tmp_path / "kpis_ap_failure.png"
    kpi_figure(_rows(), "ap_failure", path)
    assert path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_a_censored_label_stacks_its_never_count_under_the_value() -> None:
    # regression (campaign figures 2026-10-12): "≥374 (2 never)" on one line ran into the next
    # mode's interval, a panel is ~1 inch per mode
    assert value_label(374.33, 2) == "≥374\n2 never"
    assert value_label(0.531, 0) == "0.53"
    assert value_label(146.0, 0) == "146"


def test_an_interval_is_clipped_to_what_the_kpi_can_be() -> None:
    # regression (code review 2026-10-12): the AP-failure V2 time to recover was drawn up to
    # ~610 s, past the 360 s at which a run that never recovers is counted
    ttr = {"mean": 142.0, "ci95": 470.0, "high": 360.0}
    assert error_bar("ttr_s", ttr) == (142.0, 218.0)
    assert error_bar("loss_pct", {"mean": 10.0, "ci95": 32.5, "high": None}) == (10.0, 32.5)
    assert error_bar("jain", {"mean": 0.9, "ci95": None, "high": None}) == (0.0, 0.0)
