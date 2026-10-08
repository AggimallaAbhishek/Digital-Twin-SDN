"""P2.3 dataset export logic (experiments/dataset.py). CSV fixtures are real InfluxDB output."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa
import pytest
import yaml

from common.schemas import APStats, KPIRecord, Scenario
from experiments.batch import load_scenario
from experiments.dataset import (
    Disruption,
    RunInfo,
    disruption,
    label_rows,
    parse_flux_csv,
    to_table,
)

ROOT = Path(__file__).resolve().parents[2]
KPI_CSV = (ROOT / "tests/fixtures/influx/kpi_pivot.csv").read_text()
AP_CSV = (ROOT / "tests/fixtures/influx/ap_stats_pivot.csv").read_text()


# ------------------------------------------------------------------ parsing
def test_kpi_csv_parses_into_typed_rows() -> None:
    rows = parse_flux_csv(KPI_CSV, KPIRecord)
    assert len(rows) == 13  # header + 13 rows (verified with csv.reader)
    first = rows[0]
    assert first == {
        "ts": datetime(2026, 10, 8, 7, 32, 40, 812000, tzinfo=UTC),
        "app_class": "bulk",
        "flow_id": "sta16-bulk",
        "run_id": "smoke-util",
        "scenario_id": "smoke",
        "jitter_ms": 0.258,
        "latency_ms": 0.464,
        "loss_pct": 0.0,
        "throughput_mbps": 0.594,
    }


def test_integer_fields_stay_integers_and_tags_stay_strings() -> None:
    row = parse_flux_csv(AP_CSV, APStats)[0]
    assert (row["n_clients"], row["channel"], row["noise_dbm"]) == (3, "1", -92.0)


def test_empty_result_has_no_rows() -> None:
    assert parse_flux_csv("", KPIRecord) == []
    assert parse_flux_csv("\r\n", KPIRecord) == []


# ------------------------------------------------------------------ disruption (stress onset)
@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("normal", None),
        ("lecture_flash_crowd", Disruption(210.0, "flash_crowd")),
        ("ap_failure", Disruption(240.0, "ap_down")),
        ("cochannel_interference", Disruption(180.0, "force_channel")),
    ],
)
def test_each_scenario_has_its_disruption(name: str, expected: Disruption | None) -> None:
    assert disruption(load_scenario(name)) == expected


# ------------------------------------------------------------------ labels
RUN = RunInfo("lecture_flash_crowd-s43", "lecture_flash_crowd", 43, "val")
T0 = datetime(2026, 10, 8, 7, 0, 0, tzinfo=UTC)


def test_rows_get_run_labels_time_and_phase() -> None:
    rows = [
        {"ts": datetime(2026, 10, 8, 7, 3, 29, 500000, tzinfo=UTC), "x": 1.0},
        {"ts": datetime(2026, 10, 8, 7, 3, 30, tzinfo=UTC), "x": 2.0},
    ]
    labelled = label_rows(rows, RUN, T0, Disruption(210.0, "flash_crowd"))
    assert labelled == [
        {
            "ts": rows[0]["ts"],
            "x": 1.0,
            "seed": 43,
            "split": "val",
            "t_s": 209.5,
            "phase": "normal",
            "event": "flash_crowd",
        },
        {
            "ts": rows[1]["ts"],
            "x": 2.0,
            "seed": 43,
            "split": "val",
            "t_s": 210.0,
            "phase": "stress",
            "event": "flash_crowd",
        },
    ]


def test_a_run_without_disruption_is_normal_throughout() -> None:
    row = {"ts": datetime(2026, 10, 8, 7, 9, 0, tzinfo=UTC)}
    (labelled,) = label_rows([row], RunInfo("normal-s42", "normal", 42, "train"), T0, None)
    assert (labelled["phase"], labelled["event"], labelled["t_s"]) == ("normal", None, 540.0)


def test_label_rows_does_not_change_its_input() -> None:
    row = {"ts": T0}
    label_rows([row], RUN, T0, None)
    assert row == {"ts": T0}


# ------------------------------------------------------------------ parquet table
def test_table_has_typed_columns_in_a_stable_order() -> None:
    rows = label_rows(
        parse_flux_csv(KPI_CSV, KPIRecord),
        RunInfo("smoke-util", "smoke", 7, "test"),
        datetime(2026, 10, 8, 7, 32, 0, tzinfo=UTC),
        Disruption(45.0, "flash_crowd"),
    )
    table = to_table(rows, KPIRecord)
    assert table.num_rows == 13
    assert table.column_names[:8] == [
        "ts", "run_id", "scenario_id", "seed", "split", "t_s", "phase", "event"
    ]  # fmt: skip
    assert table.schema.field("ts").type == pa.timestamp("ms", tz="UTC")
    assert table.schema.field("seed").type == pa.int64()
    assert table.schema.field("throughput_mbps").type == pa.float64()
    assert set(table.column("phase").to_pylist()) == {"normal"}


def test_empty_table_keeps_its_schema() -> None:
    table = to_table([], APStats)
    assert table.num_rows == 0
    assert "n_clients" in table.column_names


def test_a_row_before_any_header_is_an_error() -> None:
    with pytest.raises(ValueError, match="header"):
        parse_flux_csv(",_result,0,2026-10-08T07:32:40Z\n", KPIRecord)


def test_a_crowd_without_later_traffic_is_disrupted_when_it_moves() -> None:
    raw = yaml.safe_load((ROOT / "experiments/scenarios/lecture_flash_crowd.yaml").read_text())
    raw["traffic"] = [t for t in raw["traffic"] if t["start_s"] < 120]  # only the 0 s web traffic
    assert disruption(Scenario.model_validate(raw)) == Disruption(120.0, "crowd_move")
