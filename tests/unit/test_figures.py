"""P6.6 figures (experiments/analysis/figures.py): drawn from the results table, no network."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from experiments.analysis.figures import kpi_figure
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
        }
    )  # a mode without samples: no point
    rows[0] = rows[0] | {"ci95": None, "n": 1}  # one run: no interval
    return rows


def test_a_scenario_figure_is_written_as_png(tmp_path: Path) -> None:
    path = tmp_path / "kpis_ap_failure.png"
    kpi_figure(_rows(), "ap_failure", path)
    assert path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
