"""KPI probe parsing (P1.5): tool output lines -> samples -> one KPI record per flow per window.

Pure Python (no Mininet import), unit-tested on the Mac and run on the VM (Python 3.8, ADR-003).
Tools: iperf3 3.7 text output with `--forceflush` (3.7 cannot stream JSON), `ping -O` (replies
plus `no answer yet` lines) and one `curl -w` result line per web fetch (format:
testbed/traffic/profiles.py CURL_FORMAT).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Sequence

_UNIT_TO_MBPS = {"": 1e-6, "K": 1e-3, "M": 1.0, "G": 1e3}
_IPERF_INTERVAL = re.compile(
    r"^\[\s*\d+\]\s+[\d.]+-[\d.]+\s+sec\s+[\d.]+\s+\w*Bytes\s+"
    r"(?P<rate>[\d.]+)\s+(?P<unit>[KMG]?)bits/sec"
    r"(?:\s+(?P<jitter>[\d.]+)\s+ms\s+(?P<lost>\d+)/(?P<total>\d+)\s+\([^)]*\))?\s*$"
)
_CURL_RESULT = re.compile(r"^CURL (?P<code>\d{3}) (?P<bytes>\d+) (?P<time>[\d.]+)$")
_HTTP_OK = 200
_PING_REPLY = re.compile(r"^\d+ bytes from \S+ icmp_seq=(?P<seq>\d+) .*time=(?P<rtt>[\d.]+) ms$")
_PING_UNANSWERED = re.compile(r"^no answer yet for icmp_seq=(?P<seq>\d+)$")


@dataclass(frozen=True)
class IperfSample:
    """One iperf3 per-second interval. Jitter and loss exist only for UDP (None for TCP)."""

    throughput_mbps: float
    jitter_ms: float | None
    loss_pct: float | None  # None also when no datagrams were counted in the interval


@dataclass(frozen=True)
class WebFetch:
    """One web fetch: success (HTTP 200 with a body), bytes received and total time."""

    ok: bool
    size_bytes: int
    time_s: float


def parse_iperf_interval(line: str) -> IperfSample | None:
    """Parse an iperf3 interval line; None for headers, summaries (sender/receiver) and errors."""
    m = _IPERF_INTERVAL.match(line)
    if m is None:
        return None
    mbps = float(m["rate"]) * _UNIT_TO_MBPS[m["unit"]]
    if m["jitter"] is None:
        return IperfSample(mbps, None, None)
    total = int(m["total"])
    loss = 100.0 * int(m["lost"]) / total if total else None
    return IperfSample(mbps, float(m["jitter"]), loss)


def parse_ping_reply(line: str) -> tuple[int, float] | None:
    """Parse a ping echo reply into (icmp_seq, rtt_ms); None for duplicates, errors, banners."""
    m = _PING_REPLY.match(line.strip())
    return (int(m["seq"]), float(m["rtt"])) if m else None


def parse_ping_unanswered(line: str) -> int | None:
    """Parse `ping -O`'s `no answer yet for icmp_seq=N` (printed when ping sends N + 1)."""
    m = _PING_UNANSWERED.match(line.strip())
    return int(m["seq"]) if m else None


def parse_curl(line: str) -> WebFetch | None:
    """Parse a `curl -w` result line (CURL <http_code> <size_download> <time_total>)."""
    m = _CURL_RESULT.match(line.strip())
    if m is None:
        return None
    size, time_s = int(m["bytes"]), float(m["time"])
    ok = int(m["code"]) == _HTTP_OK and size > 0 and time_s > 0
    return WebFetch(ok, size, time_s)


@dataclass(frozen=True)
class PingStats:
    """Pings finalised in one window: how many were sent and answered, and the answers' RTTs."""

    sent: int
    received: int
    rtts_ms: tuple[float, ...]

    @property
    def loss_pct(self) -> float:
        return 100.0 * (self.sent - self.received) / self.sent

    @property
    def mean_rtt_ms(self) -> float | None:
        return sum(self.rtts_ms) / len(self.rtts_ms) if self.rtts_ms else None

    @property
    def jitter_ms(self) -> float | None:
        """Mean absolute difference of consecutive RTTs (IP delay variation, RFC 3393)."""
        if not self.rtts_ms:
            return None
        diffs = [abs(b - a) for a, b in zip(self.rtts_ms, self.rtts_ms[1:])]
        return sum(diffs) / len(diffs) if diffs else 0.0


class PingWindow:
    """Tracks one `ping -O -i interval_s` by sequence number and finalises it per window.

    Every reply and every `no answer yet` line shows how far ping has got. A ping is final
    once ping has sent `timeout_s / interval_s` newer ones: answered by then, or lost. Sequence
    numbers, not wall time, because ping's real interval drifts (~0.207 s for -i 0.2 on the VM).
    Each ping is counted in exactly one window, so a dead link shows 100% loss, not no data.
    """

    def __init__(self, interval_s: float, timeout_s: float) -> None:
        self._lag = math.ceil(timeout_s / interval_s)
        self._closed_seq = 0
        self._sent_seq = 0
        self._replies: dict[int, float] = {}

    def add_reply(self, seq: int, rtt_ms: float) -> None:
        """Record a reply; replies to pings already finalised (as lost) are ignored."""
        self._sent_seq = max(self._sent_seq, seq)
        if seq > self._closed_seq:
            self._replies[seq] = rtt_ms

    def add_unanswered(self, seq: int) -> None:
        """Record that ping sent `seq` (it may still be answered before its timeout)."""
        self._sent_seq = max(self._sent_seq, seq)

    def close(self) -> PingStats | None:
        """Finalise every ping older than the timeout; None if there are none yet."""
        last = self._sent_seq - self._lag
        if last <= self._closed_seq:
            return None
        seqs = range(self._closed_seq + 1, last + 1)
        rtts = tuple(self._replies.pop(s) for s in seqs if s in self._replies)
        self._closed_seq = last
        return PingStats(sent=len(seqs), received=len(rtts), rtts_ms=rtts)


@dataclass(frozen=True)
class WindowSamples:
    """What one flow measured in one window: its station's pings plus iperf3 or web fetches."""

    ping: PingStats | None
    iperf: IperfSample | None = None
    fetches: Sequence[WebFetch] = ()


def kpi_record(
    flow_id: str, app_class: str, ts: str, samples: WindowSamples, *, lost_latency_ms: float
) -> dict[str, Any] | None:
    """One flow's KPIs for one window (KPIRecord fields minus scenario_id/run_id).

    Throughput comes from iperf3 (video, bulk) or the mean goodput of finished fetches (web).
    Latency is the mean ping RTT to the server; `lost_latency_ms` (the ping timeout) when every
    ping was lost. Video takes jitter and loss from iperf3's UDP counters (ping loss when iperf3
    counted no datagrams); bulk and web take them from ping, and web loss also counts failed
    fetches. None when the window has no throughput sample or no finalised pings.
    """
    ping, iperf, fetches = samples.ping, samples.iperf, samples.fetches
    if ping is None:
        return None
    jitter, loss = ping.jitter_ms or 0.0, ping.loss_pct
    if app_class == "web":
        if not fetches:
            return None
        good = [f.size_bytes * 8 / f.time_s / 1e6 for f in fetches if f.ok]
        throughput = sum(good) / len(good) if good else 0.0
        loss = max(loss, 100.0 * (len(fetches) - len(good)) / len(fetches))
    else:
        if iperf is None:
            return None
        throughput = iperf.throughput_mbps
        if iperf.jitter_ms is not None:
            jitter = iperf.jitter_ms
            loss = iperf.loss_pct if iperf.loss_pct is not None else loss
    latency = ping.mean_rtt_ms
    return {
        "ts": ts,
        "flow_id": flow_id,
        "app_class": app_class,
        "throughput_mbps": round(throughput, 3),
        "latency_ms": round(lost_latency_ms if latency is None else latency, 3),
        "jitter_ms": round(jitter, 3),
        "loss_pct": round(loss, 3),
    }
