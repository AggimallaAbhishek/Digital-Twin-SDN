"""P2.3 export: the Flux query builder only accepts safe identifiers."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from experiments.export_dataset import run_query

T0 = datetime(2026, 10, 8, 7, 0, tzinfo=UTC)
T1 = datetime(2026, 10, 8, 7, 10, tzinfo=UTC)


def test_query_selects_one_run_of_one_measurement() -> None:
    query = run_query("kpi", "ap_failure-s43", T0, T1)
    assert 'r._measurement == "kpi" and r.run_id == "ap_failure-s43"' in query
    assert "range(start: 2026-10-08T07:00:00+00:00, stop: 2026-10-08T07:10:00+00:00)" in query


@pytest.mark.parametrize(
    ("measurement", "run_id"), [("kpi", 'x" or true or "'), ("kpi\n|> drop()", "run-1")]
)
def test_unsafe_names_are_refused(measurement: str, run_id: str) -> None:
    with pytest.raises(ValueError, match="identifier"):
        run_query(measurement, run_id, T0, T1)
