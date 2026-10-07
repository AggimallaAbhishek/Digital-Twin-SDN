"""P1.5 KPI probe parsing (testbed/traffic/parse.py). Sample lines are real VM output."""

from __future__ import annotations

from typing import Any

import pytest

from testbed.traffic.parse import (
    IperfSample,
    PingStats,
    PingWindow,
    WebFetch,
    WindowSamples,
    kpi_record,
    parse_curl,
    parse_iperf_interval,
    parse_ping_reply,
    parse_ping_unanswered,
)

UDP_LINE = "[  5]   1.00-2.00   sec   364 KBytes  2.99 Mbits/sec  2.541 ms  0/311 (0%)  "
TCP_LINE = "[  5]   1.00-2.00   sec   560 KBytes  4.59 Mbits/sec                  "


def test_udp_interval_gives_throughput_jitter_and_loss() -> None:
    assert parse_iperf_interval(UDP_LINE) == IperfSample(2.99, 2.541, 0.0)


def test_tcp_interval_gives_throughput_only() -> None:
    assert parse_iperf_interval(TCP_LINE) == IperfSample(4.59, None, None)


@pytest.mark.parametrize(
    ("line", "mbps"),
    [
        ("[  5]   3.00-4.00   sec  0.00 Bytes  0.00 bits/sec  0.000 ms  0/0 (0%)  ", 0.0),
        ("[  5]   3.00-4.00   sec  60.0 KBytes   492 Kbits/sec                  ", 0.492),
        ("[  5]   3.00-4.00   sec   125 MBytes  1.05 Gbits/sec                  ", 1050.0),
    ],
)
def test_bitrate_units_are_converted_to_mbps(line: str, mbps: float) -> None:
    sample = parse_iperf_interval(line)
    assert sample is not None
    assert sample.throughput_mbps == pytest.approx(mbps)


def test_udp_loss_is_lost_over_total_datagrams() -> None:
    line = "[  5]   2.00-3.00   sec   300 KBytes  2.46 Mbits/sec  4.100 ms  52/312 (17%)  "
    sample = parse_iperf_interval(line)
    assert sample is not None
    assert sample.loss_pct == pytest.approx(100 * 52 / 312)


@pytest.mark.parametrize(
    "line",
    [
        "[  5]   0.00-4.01   sec  1.43 MBytes  3.00 Mbits/sec  0.000 ms  0/1253 (0%)  sender",
        "[  5]   0.00-5.00   sec  2.72 MBytes  4.57 Mbits/sec                  receiver",
        "[ ID] Interval           Transfer     Bitrate         Jitter    Lost/Total Datagrams",
        "Connecting to host 10.0.1.1, port 5201",
        "- - - - - - - - - - - - - - - - - - - - - - - - -",
        "iperf3: error - unable to connect to server: Connection refused",
        "",
    ],
)
def test_summary_header_and_other_lines_are_ignored(line: str) -> None:
    assert parse_iperf_interval(line) is None


def test_udp_interval_with_no_datagrams_has_unknown_loss() -> None:
    line = "[  5]   3.00-4.00   sec  0.00 Bytes  0.00 bits/sec  0.000 ms  0/0 (0%)  "
    assert parse_iperf_interval(line) == IperfSample(0.0, 0.0, None)


@pytest.mark.parametrize(
    ("line", "reply"),
    [
        ("64 bytes from 10.0.1.1: icmp_seq=12 ttl=64 time=2.31 ms", (12, 2.31)),
        ("64 bytes from 10.0.1.1: icmp_seq=7 ttl=64 time=153 ms", (7, 153.0)),
    ],
)
def test_ping_reply_gives_sequence_and_rtt(line: str, reply: tuple[int, float]) -> None:
    assert parse_ping_reply(line) == reply


@pytest.mark.parametrize(
    "line",
    [
        "64 bytes from 10.0.1.1: icmp_seq=12 ttl=64 time=2.31 ms (DUP!)",
        "From 10.0.0.5 icmp_seq=3 Destination Host Unreachable",
        "PING 10.0.1.1 (10.0.1.1) 56(84) bytes of data.",
        "--- 10.0.1.1 ping statistics ---",
        "",
    ],
)
def test_duplicates_errors_and_banners_are_not_replies(line: str) -> None:
    assert parse_ping_reply(line) is None


def test_successful_fetch_gives_bytes_and_time() -> None:
    assert parse_curl("CURL 200 512000 0.412345") == WebFetch(True, 512000, 0.412345)


@pytest.mark.parametrize(
    "line",
    ["CURL 000 0 10.001234", "CURL 404 335 0.003", "CURL 200 0 0.000000"],
)
def test_timeouts_errors_and_empty_fetches_are_failures(line: str) -> None:
    fetch = parse_curl(line)
    assert fetch is not None
    assert not fetch.ok


@pytest.mark.parametrize("line", ["curl: (7) Failed to connect", "CURL 200 lots 0.4", ""])
def test_non_result_lines_are_ignored(line: str) -> None:
    assert parse_curl(line) is None


# ping -O -i 0.2 with a 1 s timeout: a ping is final once 5 newer ones have been sent.
def _window() -> PingWindow:
    return PingWindow(interval_s=0.2, timeout_s=1.0)


def _sent_up_to(window: PingWindow, seq: int) -> None:
    window.add_unanswered(seq)  # `no answer yet for icmp_seq=<seq>`: ping got this far


def test_window_closes_only_pings_older_than_the_timeout() -> None:
    window = _window()
    for seq, rtt in [(1, 2.0), (2, 4.0), (3, 3.0), (4, 5.0), (5, 6.0), (6, 1.0)]:
        window.add_reply(seq, rtt)
    _sent_up_to(window, 10)
    stats = window.close()  # seqs 1-5 are final, 6-10 may still be answered
    assert stats == PingStats(sent=5, received=5, rtts_ms=(2.0, 4.0, 3.0, 5.0, 6.0))
    assert stats.loss_pct == 0.0
    assert stats.mean_rtt_ms == pytest.approx(4.0)
    assert stats.jitter_ms == pytest.approx((2 + 1 + 2 + 1) / 4)  # mean |consecutive diff|


def test_unanswered_pings_count_as_lost() -> None:
    window = _window()
    window.add_reply(1, 2.0)
    window.add_reply(3, 2.0)
    _sent_up_to(window, 10)
    stats = window.close()
    assert stats is not None
    assert (stats.sent, stats.received, stats.loss_pct) == (5, 2, 60.0)


def test_late_reply_within_the_timeout_counts() -> None:
    window = _window()
    window.add_unanswered(1)
    window.add_reply(1, 450.0)  # answered after the next ping went out
    _sent_up_to(window, 6)
    assert window.close() == PingStats(sent=1, received=1, rtts_ms=(450.0,))


def test_replies_also_show_progress() -> None:
    window = _window()
    for seq in range(1, 7):
        window.add_reply(seq, 2.0)
    assert window.close() == PingStats(sent=1, received=1, rtts_ms=(2.0,))


def test_each_ping_is_counted_in_one_window_only() -> None:
    window = _window()
    for seq in range(1, 11):
        window.add_reply(seq, 2.0)
    first = window.close()
    _sent_up_to(window, 15)
    second = window.close()
    assert first is not None
    assert second is not None
    assert (first.sent, second.sent) == (5, 5)


def test_replies_after_their_window_closed_stay_lost() -> None:
    window = _window()
    _sent_up_to(window, 10)
    window.close()
    window.add_reply(2, 900.0)
    window.add_reply(6, 2.0)
    _sent_up_to(window, 11)
    assert window.close() == PingStats(sent=1, received=1, rtts_ms=(2.0,))


def test_dead_link_reads_as_total_loss_without_rtt() -> None:
    window = _window()
    _sent_up_to(window, 10)
    stats = window.close()
    assert stats is not None
    assert stats.loss_pct == 100.0
    assert stats.mean_rtt_ms is None
    assert stats.jitter_ms is None


def test_nothing_to_close_before_the_first_timeout() -> None:
    window = _window()
    _sent_up_to(window, 5)
    assert window.close() is None


@pytest.mark.parametrize(
    ("line", "seq"),
    [
        ("no answer yet for icmp_seq=7", 7),
        ("64 bytes from 10.0.1.1: icmp_seq=12 ttl=64 time=2.31 ms", None),
        ("", None),
    ],
)
def test_unanswered_line_gives_the_sequence(line: str, seq: int | None) -> None:
    assert parse_ping_unanswered(line) == seq


def test_single_reply_has_zero_jitter() -> None:
    assert PingStats(sent=1, received=1, rtts_ms=(3.0,)).jitter_ms == 0.0


TS = "2026-10-07T10:00:01Z"
PING = PingStats(sent=5, received=4, rtts_ms=(2.0, 4.0, 3.0, 5.0))  # 20% loss, mean 3.5 ms
LOST_MS = 1000.0


def _record(app_class: str, **samples: Any) -> dict[str, Any] | None:
    return kpi_record(
        f"sta5-{app_class}", app_class, TS, WindowSamples(**samples), lost_latency_ms=LOST_MS
    )


def test_video_record_takes_jitter_and_loss_from_iperf_and_latency_from_ping() -> None:
    record = _record("video", ping=PING, iperf=IperfSample(2.99, 2.5, 1.0))
    assert record == {
        "ts": TS,
        "flow_id": "sta5-video",
        "app_class": "video",
        "throughput_mbps": 2.99,
        "latency_ms": 3.5,
        "jitter_ms": 2.5,
        "loss_pct": 1.0,
    }


def test_video_loss_falls_back_to_ping_when_iperf_counted_nothing() -> None:
    record = _record("video", ping=PING, iperf=IperfSample(0.0, 0.0, None))
    assert record is not None
    assert record["loss_pct"] == 20.0


def test_bulk_record_takes_jitter_and_loss_from_ping() -> None:
    record = _record("bulk", ping=PING, iperf=IperfSample(4.59, None, None))
    assert record is not None
    assert (record["throughput_mbps"], record["jitter_ms"], record["loss_pct"]) == (
        4.59,
        1.667,  # mean of |4-2|, |3-4|, |5-3| = 5/3, rounded to 3 decimals
        20.0,
    )


def test_web_throughput_is_mean_goodput_of_fetches() -> None:
    fetches = [WebFetch(True, 500_000, 0.5), WebFetch(True, 500_000, 1.0)]  # 8 and 4 Mbit/s
    record = _record("web", ping=PING, fetches=fetches)
    assert record is not None
    assert record["throughput_mbps"] == pytest.approx(6.0)
    assert record["loss_pct"] == 20.0


def test_failed_web_fetches_raise_loss() -> None:
    fetches = [WebFetch(True, 500_000, 0.5), WebFetch(False, 0, 10.0)]
    record = _record("web", ping=PING, fetches=fetches)
    assert record is not None
    assert (record["throughput_mbps"], record["loss_pct"]) == (pytest.approx(8.0), 50.0)


def test_web_with_only_failed_fetches_has_zero_throughput() -> None:
    record = _record("web", ping=PING, fetches=[WebFetch(False, 0, 10.0)])
    assert record is not None
    assert (record["throughput_mbps"], record["loss_pct"]) == (0.0, 100.0)


def test_dead_link_reports_the_ping_timeout_as_latency() -> None:
    dead = PingStats(sent=5, received=0, rtts_ms=())
    record = _record("bulk", ping=dead, iperf=IperfSample(0.0, None, None))
    assert record is not None
    assert (record["latency_ms"], record["jitter_ms"], record["loss_pct"]) == (LOST_MS, 0.0, 100.0)


@pytest.mark.parametrize(
    ("app_class", "samples"),
    [
        ("video", {"ping": PING}),  # no iperf interval in this window
        ("bulk", {"ping": None, "iperf": IperfSample(4.0, None, None)}),  # no ping finalised yet
        ("web", {"ping": PING, "fetches": []}),  # thinking: no fetch finished
    ],
)
def test_no_record_without_a_throughput_sample_and_ping_stats(
    app_class: str, samples: dict[str, Any]
) -> None:
    assert _record(app_class, **samples) is None
