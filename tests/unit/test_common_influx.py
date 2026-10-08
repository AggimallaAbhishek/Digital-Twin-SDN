"""common/influx.py: Flux query building, CSV parsing and the HTTP query (real InfluxDB CSV)."""

from __future__ import annotations

import contextlib
import io
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from common.influx import (
    InfluxConnection,
    is_http_url,
    parse_flux_csv,
    query_csv,
    rows_query,
)
from common.schemas import APStats, KPIRecord

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "influx"
KPI_CSV = (FIXTURES / "kpi_pivot.csv").read_text()
AP_CSV = (FIXTURES / "ap_stats_pivot.csv").read_text()
T0 = datetime(2026, 10, 8, 7, 0, tzinfo=UTC)
T1 = datetime(2026, 10, 8, 7, 10, tzinfo=UTC)
CONN = InfluxConnection("http://127.0.0.1:8086/", "org one", "telemetry", "secret-token")


# ------------------------------------------------------------------ parsing
def test_kpi_csv_parses_into_typed_rows() -> None:
    rows = parse_flux_csv(KPI_CSV, KPIRecord)
    assert len(rows) == 13  # header + 13 rows (verified with csv.reader)
    assert rows[0] == {
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


def test_a_row_before_any_header_is_an_error() -> None:
    with pytest.raises(ValueError, match="header"):
        parse_flux_csv(",_result,0,2026-10-08T07:32:40Z\n", KPIRecord)


# ------------------------------------------------------------------ queries
def test_query_selects_one_run_of_one_measurement() -> None:
    query = rows_query("telemetry", "kpi", T0, T1, run_id="ap_failure-s43")
    assert 'r._measurement == "kpi" and r.run_id == "ap_failure-s43"' in query
    assert "range(start: 2026-10-08T07:00:00+00:00, stop: 2026-10-08T07:10:00+00:00)" in query


def test_query_without_a_run_takes_every_run() -> None:
    assert "run_id" not in rows_query("telemetry", "ap_stats", T0, T1)


@pytest.mark.parametrize(
    ("bucket", "measurement", "run_id"),
    [
        ("telemetry", "kpi", 'x" or true or "'),
        ("telemetry", "kpi\n|> drop()", None),
        ("a b", "kpi", None),
    ],
)
def test_unsafe_names_are_refused(bucket: str, measurement: str, run_id: str | None) -> None:
    with pytest.raises(ValueError, match="identifier"):
        rows_query(bucket, measurement, T0, T1, run_id=run_id)


# ------------------------------------------------------------------ http
class FakeOpener:
    def __init__(self) -> None:
        self.request: urllib.request.Request | None = None

    def __call__(self, request: urllib.request.Request, timeout: float) -> Any:
        self.request = request
        return contextlib.closing(io.BytesIO(b",result,table\n"))


def test_query_posts_flux_with_the_token() -> None:
    opener = FakeOpener()
    assert query_csv(CONN, 'from(bucket: "telemetry")', timeout_s=5, opener=opener) == (
        ",result,table\n"
    )
    assert opener.request is not None
    assert opener.request.full_url == "http://127.0.0.1:8086/api/v2/query?org=org+one"
    assert opener.request.get_header("Authorization") == "Token secret-token"
    assert opener.request.data == b'from(bucket: "telemetry")'


def test_only_http_urls_are_queried() -> None:
    conn = InfluxConnection("file:///etc/passwd", "o", "b", "t")
    with pytest.raises(ValueError, match="http"):
        query_csv(conn, "x", timeout_s=5, opener=FakeOpener())
    assert is_http_url("https://influx:8086")


def test_connection_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INFLUXDB_URL", "http://localhost:8086")
    monkeypatch.setenv("INFLUXDB_ORG", "lab")
    monkeypatch.setenv("INFLUXDB_TOKEN", "secret-token")
    monkeypatch.delenv("INFLUXDB_BUCKET", raising=False)
    conn = InfluxConnection.from_env()
    assert (conn.url, conn.org, conn.bucket) == ("http://localhost:8086", "lab", "telemetry")
    assert "secret-token" not in repr(conn)


def test_missing_settings_are_named(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("INFLUXDB_TOKEN", raising=False)
    monkeypatch.setenv("INFLUXDB_URL", "http://localhost:8086")
    monkeypatch.setenv("INFLUXDB_ORG", "lab")
    with pytest.raises(ValueError, match="INFLUXDB_TOKEN"):
        InfluxConnection.from_env()
