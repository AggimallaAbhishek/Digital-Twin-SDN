"""P2.1 telemetry collector: polls the testbed every second, writes valid records to InfluxDB.

    uv run python -m telemetry.collector.collector --scenario-id normal --run-id normal-1

Sources (config/telemetry.yaml): Ryu REST /stats/ports and /stats/flows, and the AP agent's
/aps/{ap}/stats, /stations and /kpi. Every response is validated against common/schemas.py on
arrival (records.py); invalid records are logged and dropped. All polls of one period run in
parallel and their records go to InfluxDB in one write (line protocol over HTTP, stdlib only).
Health (lag = write time - record ts, gap = time between successful polls of a source) is
checked against the P2.1 Done when limits and saved to logs/collector/<run_id>.json.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import logging
import os
import sys
import threading
import time
import typing
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from common.schemas import TelemetryRecord
from telemetry.collector.records import (
    Batch,
    Meta,
    from_ap_stats,
    from_kpis,
    from_ryu_flows,
    from_ryu_ports,
    from_stations,
    line_protocol,
    series_key,
)

log = logging.getLogger("telemetry.collector")
ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = ROOT / "config" / "telemetry.yaml"
LOG_DIR = ROOT / "logs" / "collector"
BACKOFF_S = 0.2
_NEVER = datetime.min.replace(tzinfo=UTC)  # older than any record

Fetch = Callable[[str, float], Any]
Write = Callable[[list[str]], None]


class FetchError(RuntimeError):
    """A testbed endpoint did not answer with JSON."""


class WriteError(RuntimeError):
    """InfluxDB refused or did not take a write after the bounded retries."""


@dataclass(frozen=True)
class CollectorConfig:
    """config/telemetry.yaml."""

    vm_host: str
    ryu_port: int
    agent_port: int
    period_s: float
    request_timeout_s: float
    write_timeout_s: float
    write_retries: int
    max_lag_s: float
    max_gap_s: float


def load_collector_config(path: Path = DEFAULT_CONFIG) -> CollectorConfig:
    """Load config/telemetry.yaml; ValueError names a missing or non-positive value."""
    raw = yaml.safe_load(path.read_text())
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: must be a mapping")
    values: dict[str, Any] = {}
    for name, kind in typing.get_type_hints(CollectorConfig).items():
        value = raw.get(name)
        if kind is str:
            ok = isinstance(value, str) and bool(value)
        else:  # int fields must be whole numbers; float fields take either
            accepted = int if kind is int else int | float
            ok = isinstance(value, accepted) and not isinstance(value, bool) and value > 0
        if not ok:
            raise ValueError(f"config/telemetry.yaml: {name} is missing or invalid ({value!r})")
        values[name] = value
    return CollectorConfig(**values)


@dataclass
class Health:
    """Lag and gaps against the P2.1 limits."""

    started_at: float = 0.0  # records stamped earlier are backlog: written, but not lag
    records: int = 0
    backlog_records: int = 0
    max_lag_by_measurement: dict[str, float] = field(default_factory=dict)
    failures: dict[str, int] = field(default_factory=dict)
    max_gap_s: dict[str, float] = field(default_factory=dict)
    _last_ok: dict[str, float] = field(default_factory=dict)

    def poll(self, source: str, t: float, ok: bool) -> None:
        """Record one poll of `source` at time `t`."""
        if not ok:
            self.failures[source] = self.failures.get(source, 0) + 1
            return
        gap = t - self._last_ok.get(source, t)
        self.max_gap_s[source] = max(self.max_gap_s.get(source, 0.0), gap)
        self._last_ok[source] = t

    def written(self, record_times: dict[str, list[float]], written_at: float) -> None:
        """Record a successful write; `record_times` maps measurement -> record ts (epoch s)."""
        for measurement, all_times in record_times.items():
            self.records += len(all_times)
            times = [t for t in all_times if t >= self.started_at]
            self.backlog_records += len(all_times) - len(times)
            if not times:
                continue
            lag = written_at - min(times)
            worst = self.max_lag_by_measurement.get(measurement, 0.0)
            self.max_lag_by_measurement[measurement] = max(worst, lag)

    @property
    def max_lag_s(self) -> float:
        """Worst lag over all measurements."""
        return max(self.max_lag_by_measurement.values(), default=0.0)

    def finish(self, at: float) -> None:
        """End of run: time since each source's last success counts as a gap too."""
        for source, last in self._last_ok.items():
            self.max_gap_s[source] = max(self.max_gap_s[source], at - last)

    def passed(self, max_lag_s: float, max_gap_s: float) -> bool:
        """Records were written, with lag and every source's gap within the limits."""
        gaps_ok = all(gap <= max_gap_s for gap in self.max_gap_s.values())
        return self.records > 0 and self.max_lag_s < max_lag_s and gaps_ok


@dataclass
class PollReport:
    """What one poll did."""

    records: int = 0
    failed_sources: list[str] = field(default_factory=list)
    invalid: list[str] = field(default_factory=list)
    write_failed: bool = False


class Collector:
    """Polls every source once per period and writes the valid records."""

    def __init__(
        self,
        config: CollectorConfig,
        meta: Meta,
        fetch: Fetch,
        write: Write,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.config, self.meta, self.health = config, meta, Health(started_at=clock())
        self._fetch, self._write, self._clock = fetch, write, clock
        self._ryu = f"http://{config.vm_host}:{config.ryu_port}"
        self._agent = f"http://{config.vm_host}:{config.agent_port}"
        self._aps: list[str] | None = None
        # newest ts written per series: /kpi returns each flow's *latest* record every poll
        self._written: dict[tuple[Any, ...], datetime] = {}
        self._pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="collector")

    def poll_once(self, now: float) -> PollReport:
        """Poll every source in parallel, write what is valid, update health."""
        report = PollReport()
        jobs = {name: self._pool.submit(job) for name, job in self._jobs().items()}
        batches: list[Batch] = []
        fetched: list[str] = []
        for name, future in jobs.items():
            try:
                batches.append(future.result())
                fetched.append(name)
            except FetchError as exc:
                report.failed_sources.append(name)
                self.health.poll(name, now, ok=False)
                log.warning("poll of %s failed: %s", name, exc)
        keyed = [(series_key(r), r) for b in batches for r in b.records]
        new = [(key, r) for key, r in keyed if r.ts > self._written.get(key, _NEVER)]
        report.invalid = [e for b in batches for e in b.errors]
        for error in report.invalid:
            log.warning("invalid record dropped: %s", error)
        stored = self._store(new)
        for name in fetched:  # a source counts as polled only once its data is stored
            self.health.poll(name, now, ok=stored)
        report.write_failed = not stored
        report.records = len(new) if stored else 0
        return report

    def _store(self, new: list[tuple[tuple[Any, ...], TelemetryRecord]]) -> bool:
        """Write new records; remember the newest ts per series. False if the write failed."""
        if not new:
            return True
        try:
            self._write([line_protocol(r) for _, r in new])
        except WriteError as exc:
            log.error("write failed: %s", exc)
            return False
        times: dict[str, list[float]] = {}
        for key, record in new:
            times.setdefault(key[0], []).append(record.ts.timestamp())  # key[0] = measurement
        self.health.written(times, self._clock())
        for key, record in new:
            self._written[key] = record.ts
        return True

    def run(self, duration_s: float | None, stop: threading.Event | None = None) -> None:
        """poll_once() every period until `duration_s` (forever if None), `stop`, or Ctrl-C."""
        start = self._clock()
        next_poll = start
        while (duration_s is None or self._clock() - start < duration_s) and not (
            stop is not None and stop.is_set()
        ):
            started = self._clock()
            self.poll_once(started)
            took = self._clock() - started
            if took > self.config.period_s:
                log.warning("poll took %.2f s (period %.1f s)", took, self.config.period_s)
            next_poll += self.config.period_s
            time.sleep(max(0.0, next_poll - self._clock()))

    def _jobs(self) -> dict[str, Callable[[], Batch]]:
        get = self._get
        return {
            "ports": lambda: from_ryu_ports(get(f"{self._ryu}/stats/ports"), self.meta),
            "flows": lambda: from_ryu_flows(get(f"{self._ryu}/stats/flows"), self.meta),
            "ap_stats": self._ap_stats,
            "stations": lambda: from_stations(get(f"{self._agent}/stations"), self.meta),
            "kpi": lambda: from_kpis(get(f"{self._agent}/kpi"), self.meta),
        }

    def _ap_stats(self) -> Batch:
        if self._aps is None:  # once: the campus has a fixed set of APs
            self._aps = _ap_names(self._get(f"{self._agent}/aps"))
        batch = Batch()
        for ap in self._aps:
            one = from_ap_stats(self._get(f"{self._agent}/aps/{ap}/stats"), self.meta)
            batch.records += one.records
            batch.errors += one.errors
        return batch

    def _get(self, url: str) -> Any:
        return self._fetch(url, self.config.request_timeout_s)


def _ap_names(body: Any) -> list[str]:
    """AP names from GET /aps; FetchError if the body is not the documented shape."""
    aps = body.get("aps") if isinstance(body, dict) else None
    if not isinstance(aps, list) or not all(
        isinstance(ap, dict) and isinstance(ap.get("ap"), str) for ap in aps
    ):
        raise FetchError(f"/aps: unexpected response {str(body)[:80]!r}")
    return [ap["ap"] for ap in aps]


def is_http_url(url: str) -> bool:
    """Only http(s) URLs are ever opened (no file:// or custom schemes; bandit B310)."""
    return urllib.parse.urlsplit(url).scheme in ("http", "https")


def http_fetch(url: str, timeout_s: float) -> Any:
    """GET `url` and parse JSON; FetchError on any network, HTTP or JSON problem."""
    if not is_http_url(url):
        raise FetchError(f"{url}: only http(s) URLs are fetched")
    try:
        with urllib.request.urlopen(url, timeout=timeout_s) as response:  # noqa: S310  # nosec B310 - scheme checked above
            return json.loads(response.read())
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        raise FetchError(f"{url}: {exc}") from exc


@dataclass(frozen=True)
class InfluxTarget:
    """Where to write: InfluxDB URL, org, bucket and API token (from the environment)."""

    url: str
    org: str
    bucket: str
    token: str = field(repr=False)  # never printed


class InfluxWriter:
    """Writes line protocol to InfluxDB 2.x (/api/v2/write), with bounded retries."""

    def __init__(
        self,
        target: InfluxTarget,
        timeout_s: float,
        retries: int,
        *,
        opener: Callable[..., Any] = urllib.request.urlopen,
    ) -> None:
        if not is_http_url(target.url):
            raise ValueError(f"INFLUXDB_URL must be an http(s) URL, got {target.url!r}")
        query = urllib.parse.urlencode(
            {"org": target.org, "bucket": target.bucket, "precision": "ns"}
        )
        self.endpoint = f"{target.url.rstrip('/')}/api/v2/write?{query}"
        self._headers = {
            "Authorization": f"Token {target.token}",
            "Content-Type": "text/plain; charset=utf-8",
        }
        self._timeout_s, self._retries, self._open = timeout_s, retries, opener

    @classmethod
    def from_env(cls, config: CollectorConfig) -> InfluxWriter:
        """Build from INFLUXDB_URL/ORG/BUCKET/TOKEN (the token is never logged)."""
        missing = [
            k for k in ("INFLUXDB_URL", "INFLUXDB_ORG", "INFLUXDB_TOKEN") if not os.getenv(k)
        ]
        if missing:
            raise SystemExit(f"collector: set {', '.join(missing)} (run via `make collect`)")
        target = InfluxTarget(
            os.environ["INFLUXDB_URL"],
            os.environ["INFLUXDB_ORG"],
            os.getenv("INFLUXDB_BUCKET", "telemetry"),
            os.environ["INFLUXDB_TOKEN"],
        )
        return cls(target, config.write_timeout_s, config.write_retries)

    def __call__(self, lines: list[str]) -> None:
        """POST the lines; retry up to `retries` times with backoff, then WriteError."""
        request = urllib.request.Request(  # noqa: S310 - URL from INFLUXDB_URL
            self.endpoint, data="\n".join(lines).encode(), headers=self._headers, method="POST"
        )
        for attempt in range(self._retries + 1):
            try:
                with self._open(request, timeout=self._timeout_s):
                    return
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                if attempt == self._retries:
                    raise WriteError(f"InfluxDB write failed: {exc}") from exc
                time.sleep(BACKOFF_S * 2**attempt)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point; returns 0 if the run met the P2.1 lag and gap limits."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--scenario-id", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--duration-s", type=float, default=None)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    config = load_collector_config(args.config)
    collector = Collector(
        config, Meta(args.scenario_id, args.run_id), http_fetch, InfluxWriter.from_env(config)
    )
    with contextlib.suppress(KeyboardInterrupt):  # Ctrl-C ends the run and still reports
        collector.run(args.duration_s)
    health = collector.health
    health.finish(at=time.time())
    ok = health.passed(config.max_lag_s, config.max_gap_s)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    summary = {"scenario_id": args.scenario_id, "run_id": args.run_id, "passed": ok}
    summary |= {k: v for k, v in asdict(health).items() if not k.startswith("_")}
    summary["max_lag_s"] = health.max_lag_s
    (LOG_DIR / f"{args.run_id}.json").write_text(json.dumps(summary, indent=1))
    worst_gap = max(health.max_gap_s.values(), default=0.0)
    print(
        f"COLLECTOR_RESULT run_id={args.run_id} records={health.records} "
        f"max_lag={health.max_lag_s:.2f}s max_gap={worst_gap:.2f}s "
        f"failures={health.failures} -> {'PASS' if ok else 'FAIL'}"
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
