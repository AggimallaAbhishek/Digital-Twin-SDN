"""P3.6 /metrics backend (api/metrics.py): telemetry rows -> one entity's series."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from api.metrics import measurement_for, series

TS = datetime(2026, 10, 8, 10, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("entity", "expected"),
    [
        ("ap3", ("ap_stats", "ap")),
        ("sta12", ("sta_stats", "sta")),
        ("sta12-video", ("kpi", "flow_id")),
    ],
)
def test_the_entity_name_picks_the_measurement(entity: str, expected: tuple[str, str]) -> None:
    assert measurement_for(entity) == expected


def test_an_unknown_entity_is_an_error() -> None:
    with pytest.raises(ValueError, match="entity"):
        measurement_for("s1")


def test_series_keeps_one_entity_and_one_metric_in_time_order() -> None:
    rows = [
        {"ts": TS.replace(second=2), "ap": "ap1", "channel_util": 0.5},
        {"ts": TS, "ap": "ap1", "channel_util": 0.25},
        {"ts": TS, "ap": "ap2", "channel_util": 0.9},
    ]
    assert series(rows, "ap", "ap1", "channel_util") == [
        {"ts": "2026-10-08T10:00:00+00:00", "value": 0.25},
        {"ts": "2026-10-08T10:00:02+00:00", "value": 0.5},
    ]


def test_an_unknown_metric_is_an_error() -> None:
    rows = [{"ts": TS, "ap": "ap1", "channel_util": 0.5}]
    with pytest.raises(ValueError, match="metric"):
        series(rows, "ap", "ap1", "colour")
