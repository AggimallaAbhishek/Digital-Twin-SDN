"""P2.1 collector loop (telemetry/collector/collector.py) with fake VM endpoints and writer."""

from __future__ import annotations

import contextlib
import json
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pytest

from common.influx import InfluxConnection
from telemetry.collector.collector import (
    Collector,
    CollectorConfig,
    FetchError,
    Health,
    InfluxWriter,
    WriteError,
    http_fetch,
    load_collector_config,
)
from telemetry.collector.records import Meta

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures"
CONFIG = load_collector_config(ROOT / "config" / "telemetry.yaml")
META = Meta("lecture_flash_crowd", "run-1")


def _fixture(path: str) -> Any:
    return json.loads((FIXTURES / path).read_text())


AP_STATS = {r["ap"]: r for r in _fixture("ap_agent/ap_agent_ap_stats.json")["aps"]}
RESPONSES = {
    "http://192.168.64.2:8080/stats/ports": _fixture("ryu/ryu_ports.json"),
    "http://192.168.64.2:8080/stats/flows": _fixture("ryu/ryu_flows.json"),
    "http://192.168.64.2:8081/aps": _fixture("ap_agent/ap_agent_aps.json"),
    "http://192.168.64.2:8081/stations": _fixture("ap_agent/ap_agent_stations.json"),
    "http://192.168.64.2:8081/kpi": _fixture("traffic/kpi_response.json"),
    **{f"http://192.168.64.2:8081/aps/{ap}/stats": r for ap, r in AP_STATS.items()},
}


class FakeVM:
    """Serves the recorded responses; URLs in `down` fail like an unreachable endpoint."""

    def __init__(self) -> None:
        self.down: set[str] = set()
        self.calls: list[str] = []

    def __call__(self, url: str, timeout_s: float) -> Any:
        self.calls.append(url)
        if url in self.down or url not in RESPONSES:
            raise FetchError(f"{url}: connection refused")
        return RESPONSES[url]


class FakeWriter:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def __call__(self, lines: list[str]) -> None:
        self.lines.extend(lines)


def _collector(vm: FakeVM, writer: FakeWriter) -> Collector:
    return Collector(CONFIG, META, fetch=vm, write=writer)


def test_config_loads() -> None:
    assert (
        CollectorConfig(
            vm_host="192.168.64.2",
            ryu_port=8080,
            agent_port=8081,
            period_s=1.0,
            request_timeout_s=1.5,
            write_timeout_s=3.0,
            write_retries=2,
            max_lag_s=2.0,
            max_gap_s=5.0,
        )
        == CONFIG
    )


def test_bad_config_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "telemetry.yaml"
    raw = (ROOT / "config" / "telemetry.yaml").read_text()
    path.write_text(raw.replace("period_s: 1.0", "period_s: 0"))
    with pytest.raises(ValueError, match="period_s"):
        load_collector_config(path)


def test_one_poll_writes_every_measurement() -> None:
    vm, writer = FakeVM(), FakeWriter()
    report = _collector(vm, writer).poll_once(now=0.0)
    measurements = {line.split(",", 1)[0] for line in writer.lines}
    assert measurements == {"port_stats", "flow_stats", "ap_stats", "sta_stats", "kpi"}
    assert report.invalid == []
    assert report.failed_sources == []
    expected = (
        len(RESPONSES["http://192.168.64.2:8080/stats/ports"]["ports"])
        + len(RESPONSES["http://192.168.64.2:8080/stats/flows"]["flows"])
        + len(AP_STATS)
        + len(RESPONSES["http://192.168.64.2:8081/stations"]["stations"])
        + len(RESPONSES["http://192.168.64.2:8081/kpi"]["kpis"])
    )
    assert len(writer.lines) == report.records == expected


def test_records_already_written_are_not_written_again() -> None:
    vm, writer = FakeVM(), FakeWriter()
    collector = _collector(vm, writer)
    first = collector.poll_once(now=0.0)
    second = collector.poll_once(now=1.0)  # the fake VM answers with the same records
    assert first.records > 0
    assert second.records == 0
    assert len(writer.lines) == first.records


def test_ap_list_is_fetched_once() -> None:
    vm, writer = FakeVM(), FakeWriter()
    collector = _collector(vm, writer)
    collector.poll_once(now=0.0)
    collector.poll_once(now=1.0)
    assert vm.calls.count("http://192.168.64.2:8081/aps") == 1


def test_an_unreachable_source_is_reported_and_the_rest_still_written() -> None:
    vm, writer = FakeVM(), FakeWriter()
    vm.down.add("http://192.168.64.2:8081/kpi")
    report = _collector(vm, writer).poll_once(now=0.0)
    assert report.failed_sources == ["kpi"]
    assert not any(line.startswith("kpi,") for line in writer.lines)
    assert any(line.startswith("sta_stats,") for line in writer.lines)


def test_ap_list_is_retried_until_the_agent_answers() -> None:
    vm, writer = FakeVM(), FakeWriter()
    vm.down.add("http://192.168.64.2:8081/aps")
    collector = _collector(vm, writer)
    assert "ap_stats" in collector.poll_once(now=0.0).failed_sources
    vm.down.clear()
    collector.poll_once(now=1.0)
    assert any(line.startswith("ap_stats,") for line in writer.lines)


def test_invalid_records_are_dropped_and_reported() -> None:
    vm, writer = FakeVM(), FakeWriter()
    good = RESPONSES["http://192.168.64.2:8081/kpi"]
    bad = {"ts": good["ts"], "kpis": [{**good["kpis"][0], "loss_pct": -1.0}]}
    RESPONSES["http://192.168.64.2:8081/kpi"] = bad
    try:
        report = _collector(vm, writer).poll_once(now=0.0)
    finally:
        RESPONSES["http://192.168.64.2:8081/kpi"] = good
    assert len(report.invalid) == 1
    assert "loss_pct" in report.invalid[0]
    assert not any(line.startswith("kpi,") for line in writer.lines)


# ------------------------------------------------------------------ health
def test_gap_is_the_longest_time_between_successful_polls() -> None:
    health = Health()
    for t, ok in [(0.0, True), (1.0, True), (2.0, False), (3.0, False), (4.5, True), (5.5, True)]:
        health.poll("kpi", t, ok)
    assert health.max_gap_s == {"kpi": 3.5}


def test_gap_counts_from_the_first_success_only() -> None:
    health = Health()
    for t, ok in [(0.0, False), (10.0, False), (12.0, True), (13.0, True)]:
        health.poll("ports", t, ok)
    assert health.max_gap_s == {"ports": 1.0}


def test_a_source_that_never_answered_has_no_gap() -> None:
    health = Health()
    health.poll("kpi", 0.0, False)
    assert health.max_gap_s == {}
    assert health.failures == {"kpi": 1}


def test_lag_is_write_time_minus_record_time() -> None:
    health = Health()
    health.written({"kpi": [10.0, 10.4], "port_stats": [9.7]}, written_at=11.0)
    health.written({"kpi": [11.2]}, written_at=12.0)
    assert health.max_lag_s == pytest.approx(1.3)
    assert health.max_lag_by_measurement == pytest.approx({"kpi": 1.0, "port_stats": 1.3})
    assert health.records == 4


def test_verdict_against_the_done_when_limits() -> None:
    health = Health()
    health.poll("kpi", 0.0, True)
    health.poll("kpi", 1.0, True)
    health.written({"kpi": [0.5]}, written_at=1.0)
    assert health.passed(max_lag_s=2.0, max_gap_s=5.0)
    health.poll("kpi", 7.0, True)
    assert not health.passed(max_lag_s=2.0, max_gap_s=5.0)


def test_nothing_written_is_not_a_pass() -> None:
    assert not Health().passed(max_lag_s=2.0, max_gap_s=5.0)


# ------------------------------------------------------------------ InfluxDB writer
TARGET = InfluxConnection("http://127.0.0.1:8086/", "org one", "telemetry", "secret-token")


class FakeOpener:
    """Stands in for urllib.request.urlopen: fails `failures` times, then succeeds."""

    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.requests: list[urllib.request.Request] = []

    def __call__(self, request: urllib.request.Request, timeout: float) -> Any:
        self.requests.append(request)
        if len(self.requests) <= self.failures:
            raise urllib.error.URLError("connection refused")
        return contextlib.nullcontext()


def test_writer_posts_line_protocol_with_the_token(monkeypatch: pytest.MonkeyPatch) -> None:
    opener = FakeOpener(failures=0)
    InfluxWriter(TARGET, timeout_s=3.0, retries=2, opener=opener)(["a x=1i 1", "b y=2.0 2"])
    (request,) = opener.requests
    assert request.full_url == (
        "http://127.0.0.1:8086/api/v2/write?org=org+one&bucket=telemetry&precision=ns"
    )
    assert request.get_method() == "POST"
    assert request.data == b"a x=1i 1\nb y=2.0 2"
    assert request.get_header("Authorization") == "Token secret-token"


def test_writer_retries_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(time, "sleep", lambda _s: None)
    opener = FakeOpener(failures=2)
    InfluxWriter(TARGET, timeout_s=3.0, retries=2, opener=opener)(["a x=1i 1"])
    assert len(opener.requests) == 3


def test_writer_gives_up_after_the_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(time, "sleep", lambda _s: None)
    opener = FakeOpener(failures=5)
    with pytest.raises(WriteError, match="connection refused"):
        InfluxWriter(TARGET, timeout_s=3.0, retries=2, opener=opener)(["a x=1i 1"])
    assert len(opener.requests) == 3


def test_token_is_not_in_the_target_repr() -> None:
    assert "secret-token" not in repr(TARGET)


# ------------------------------------------------------------------ run loop
class FakeClock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += seconds


def test_run_polls_once_per_period_until_the_duration(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = FakeClock()
    monkeypatch.setattr(time, "sleep", clock.sleep)
    vm, writer = FakeVM(), FakeWriter()
    Collector(CONFIG, META, fetch=vm, write=writer, clock=clock).run(duration_s=5.0)
    assert vm.calls.count("http://192.168.64.2:8081/kpi") == 5


def test_run_keeps_going_when_a_write_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = FakeClock()
    monkeypatch.setattr(time, "sleep", clock.sleep)
    calls: list[int] = []

    def failing_write(lines: list[str]) -> None:
        calls.append(len(lines))
        raise WriteError("InfluxDB down")

    Collector(CONFIG, META, fetch=FakeVM(), write=failing_write, clock=clock).run(duration_s=3.0)
    assert len(calls) == 3


def test_writer_needs_the_influx_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("INFLUXDB_URL", "INFLUXDB_ORG", "INFLUXDB_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(SystemExit, match="INFLUXDB_URL"):
        InfluxWriter.from_env(CONFIG)


# ------------------------------------------------------------------ review fixes (2026-10-08)
@pytest.mark.parametrize("body", [{"aps": "none"}, {"oops": []}, [], {"aps": [{"name": "ap1"}]}])
def test_a_malformed_ap_list_fails_that_source_only(body: Any) -> None:
    vm, writer = FakeVM(), FakeWriter()
    url = "http://192.168.64.2:8081/aps"
    good = RESPONSES[url]
    RESPONSES[url] = body
    try:
        report = _collector(vm, writer).poll_once(now=0.0)
    finally:
        RESPONSES[url] = good
    assert report.failed_sources == ["ap_stats"]
    assert any(line.startswith("kpi,") for line in writer.lines)


class FreshVM(FakeVM):
    """Like FakeVM, but every /kpi answer carries new timestamps (as live data does)."""

    def __call__(self, url: str, timeout_s: float) -> Any:
        body = super().__call__(url, timeout_s)
        if not url.endswith("/kpi"):
            return body
        stamp = f"2026-10-08T10:00:{len(self.calls):02d}.000+00:00"
        return {"ts": stamp, "kpis": [{**k, "ts": stamp} for k in body["kpis"]]}


def test_a_failed_write_counts_as_a_gap_for_every_source() -> None:
    clock = FakeClock()
    fail = {"now": False}

    def write(lines: list[str]) -> None:
        if fail["now"]:
            raise WriteError("InfluxDB down")

    collector = Collector(CONFIG, META, fetch=FreshVM(), write=write, clock=clock)
    collector.poll_once(now=0.0)
    fail["now"] = True
    report = collector.poll_once(now=3.0)
    fail["now"] = False
    collector.poll_once(now=7.0)
    assert report.write_failed
    assert collector.health.max_gap_s["kpi"] == 7.0


def test_an_outage_at_the_end_of_the_run_is_a_gap() -> None:
    health = Health()
    health.poll("kpi", 0.0, True)
    health.poll("kpi", 1.0, True)
    health.finish(at=9.0)
    assert health.max_gap_s == {"kpi": 8.0}


@pytest.mark.parametrize(
    ("old", "new", "field"),
    [
        ("ryu_port: 8080", "ryu_port: 8080.5", "ryu_port"),
        ("write_retries: 2 ", "write_retries: 2.5 ", "write_retries"),
    ],
)
def test_ports_and_retries_must_be_integers(tmp_path: Path, old: str, new: str, field: str) -> None:
    raw = (ROOT / "config" / "telemetry.yaml").read_text()
    assert old in raw
    path = tmp_path / "telemetry.yaml"
    path.write_text(raw.replace(old, new))
    with pytest.raises(ValueError, match=field):
        load_collector_config(path)


def test_config_must_be_a_mapping(tmp_path: Path) -> None:
    path = tmp_path / "telemetry.yaml"
    path.write_text("- just\n- a list\n")
    with pytest.raises(ValueError, match="mapping"):
        load_collector_config(path)


def test_backlog_from_before_the_collector_started_is_written_but_not_lag() -> None:
    health = Health(started_at=10.0)
    health.written({"kpi": [7.0, 10.5]}, written_at=11.0)  # 7.0: produced before we started
    assert health.records == 2
    assert health.max_lag_s == pytest.approx(0.5)
    assert health.backlog_records == 1


def test_collector_lag_starts_at_its_own_start(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = FakeClock()
    collector = Collector(CONFIG, META, fetch=FakeVM(), write=FakeWriter(), clock=clock)
    assert collector.health.started_at == clock.t


def test_run_stops_when_told(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = FakeClock()
    stop = threading.Event()
    vm = FakeVM()

    def sleep(seconds: float) -> None:
        clock.sleep(seconds)
        if clock.t >= 1003.0:  # the scenario ended after 3 polls
            stop.set()

    monkeypatch.setattr(time, "sleep", sleep)
    Collector(CONFIG, META, fetch=vm, write=FakeWriter(), clock=clock).run(None, stop=stop)
    assert vm.calls.count("http://192.168.64.2:8081/kpi") == 3


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://192.168.64.2/aps", "aps"])
def test_only_http_urls_are_fetched(url: str) -> None:
    with pytest.raises(FetchError, match="http"):
        http_fetch(url, timeout_s=1.0)


def test_influx_writer_needs_an_http_url() -> None:
    with pytest.raises(ValueError, match="http"):
        InfluxWriter(InfluxConnection("file:///tmp/x", "o", "b", "t"), timeout_s=1.0, retries=0)
