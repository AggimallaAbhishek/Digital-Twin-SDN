"""Traffic and KPI probe runner (P1.5): starts flows in Mininet-WiFi and measures them live.

Runs on the testbed VM (Python 3.8). Long-running tools start with node.popen() (their own
process in the node's namespace, not the node's shared shell), so the agent lock is held only
while each one launches. One reader thread per tool feeds testbed/traffic/parse.py; every
`window_s` the probe turns each flow's samples into one KPI record (KPIRecord fields without
scenario_id/run_id), keeps the latest per flow for the AP agent's GET /kpi and appends every
record to <log_dir>/kpi.jsonl.

    probe = TrafficProbe(campus, load_traffic_config_file(), log_dir, lock=agent.lock)
    agent.kpi_source = probe.latest
    probe.start()
    probe.start_flow("sta1", "video")          # P1.6 picks stations and start times
    ...
    probe.stop_all()
"""

from __future__ import annotations

import contextlib
import json
import random
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import IO, Any, Callable, ContextManager, Dict

from mininet.log import info

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
from testbed.traffic.profiles import (
    IperfProfile,
    TrafficConfig,
    WebProfile,
    flow_id,
    http_server_command,
    iperf_client_command,
    iperf_server_command,
    ping_command,
    web_fetch_command,
    web_object_name,
)

SERVER_NAME = "srv1"  # docs/scenario.md: endpoint for video, web and bulk traffic
SERVER_START_S = 0.5  # let an iperf3 / HTTP server bind before its client connects
STOP_TIMEOUT_S = 3.0
RUN_FOREVER_S = 86400  # iperf3 -t; flows run until stop_all()

Record = Dict[str, Any]  # runtime alias: typing.Dict for Python 3.8


@dataclass
class _Flow:
    """One running flow and the samples it collected since the last window."""

    flow_id: str
    sta: str
    app_class: str
    iperf: list[IperfSample] = field(default_factory=list)
    fetches: list[WebFetch] = field(default_factory=list)

    def take(self, ping: PingStats | None) -> WindowSamples:
        """This window's samples (latest iperf3 interval, all finished fetches); resets them."""
        samples = WindowSamples(ping, self.iperf[-1] if self.iperf else None, tuple(self.fetches))
        self.iperf, self.fetches = [], []
        return samples


class TrafficProbe:
    """Runs traffic profiles from srv1 to stations of a started campus and measures KPIs.

    `lock` is the AP agent's lock when the agent is serving (node shells are shared).
    """

    def __init__(
        self,
        campus: Any,
        config: TrafficConfig,
        log_dir: Path,
        lock: ContextManager[Any] | None = None,
        seed: int = 0,
    ) -> None:
        self._config = config
        self._server = campus.servers[SERVER_NAME]
        self._server_ip = self._server.IP()
        self._stations = {sta.name: sta for sta, _ in campus.stations}
        self._lock = lock if lock is not None else contextlib.nullcontext()
        self._log_dir = log_dir
        self._rng = random.Random(seed)  # noqa: S311 - web think times, not security
        self._data = threading.Lock()  # guards flows, pings, latest (reader threads write)
        self._stop = threading.Event()
        self._flows: dict[str, _Flow] = {}
        self._pings: dict[str, PingWindow] = {}
        self._latest: dict[str, Record] = {}
        self._procs: list[subprocess.Popen[str]] = []
        self._threads: list[threading.Thread] = []
        self._next_port = config.iperf_base_port
        self._http_started = False

    # ------------------------------------------------------------------ control
    def start(self) -> None:
        """Start the window clock (one KPI record per flow per window)."""
        self._spawn(self._tick_loop, "kpi-tick")

    def start_flow(self, sta: str, app_class: str, rate_mbps: float | None = None) -> str:
        """Start `app_class` traffic from srv1 to `sta`; return its flow ID."""
        fid = flow_id(sta, app_class)
        if fid in self._flows:
            raise ValueError(f"flow {fid} is already running")
        if sta not in self._stations:
            raise ValueError(f"unknown station {sta!r}")
        profile = self._config.profiles[app_class]
        self._ensure_ping(sta)
        flow = _Flow(fid, sta, app_class)
        if isinstance(profile, IperfProfile):
            self._start_iperf(flow, profile, rate_mbps)
        else:
            self._start_web(flow, profile)
        with self._data:
            self._flows[fid] = flow
        info(f"TRAFFIC_FLOW_STARTED {fid}\n")
        return fid

    def latest(self) -> list[Record]:
        """The most recent KPI record of every flow (for the AP agent's GET /kpi)."""
        with self._data:
            return [self._latest[f] for f in sorted(self._latest)]

    def stop_all(self) -> None:
        """Stop every flow, probe and server; wait for the reader threads."""
        self._stop.set()
        for proc in self._procs:
            if proc.poll() is None:
                proc.terminate()
        for proc in self._procs:
            try:
                proc.wait(timeout=STOP_TIMEOUT_S)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        for thread in self._threads:
            thread.join(timeout=STOP_TIMEOUT_S)

    def running_processes(self) -> int:
        """How many tool processes are still alive (0 after stop_all)."""
        return sum(proc.poll() is None for proc in self._procs)

    # ------------------------------------------------------------------ tools
    def _ensure_ping(self, sta: str) -> None:
        if sta in self._pings:
            return
        window = PingWindow(self._config.ping_interval_s, self._config.ping_timeout_s)
        self._pings[sta] = window
        proc = self._popen(self._stations[sta], ping_command(self._config, self._server_ip))
        self._spawn(lambda: self._read_ping(proc, window), f"ping-{sta}")

    def _start_iperf(self, flow: _Flow, profile: IperfProfile, rate_mbps: float | None) -> None:
        port, self._next_port = self._next_port, self._next_port + 1
        self._popen(self._server, iperf_server_command(port))
        time.sleep(SERVER_START_S)
        command = iperf_client_command(profile, self._server_ip, port, RUN_FOREVER_S, rate_mbps)
        proc = self._popen(self._stations[flow.sta], command)
        self._spawn(lambda: self._read_iperf(proc, flow), f"iperf-{flow.flow_id}")

    def _start_web(self, flow: _Flow, profile: WebProfile) -> None:
        if not self._http_started:
            www = self._log_dir / "www"
            www.mkdir(parents=True, exist_ok=True)
            (www / web_object_name(profile)).write_bytes(b"\0" * profile.object_kb * 1000)
            port = self._config.http_port
            self._popen(self._server, http_server_command(str(www), self._server_ip, port))
            self._http_started = True
            time.sleep(SERVER_START_S)
        self._spawn(lambda: self._web_loop(flow, profile), f"web-{flow.flow_id}")

    def _web_loop(self, flow: _Flow, profile: WebProfile) -> None:
        command = web_fetch_command(profile, self._server_ip, self._config.http_port)
        while not self._stop.is_set():
            proc = self._popen(self._stations[flow.sta], command)
            out, _ = proc.communicate()
            for line in out.splitlines():
                fetch = parse_curl(line)
                if fetch is not None:
                    with self._data:
                        flow.fetches.append(fetch)
            self._stop.wait(self._rng.expovariate(1.0 / profile.think_mean_s))

    # ------------------------------------------------------------------ readers
    def _read_ping(self, proc: subprocess.Popen[str], window: PingWindow) -> None:
        for line in _lines(proc):
            reply = parse_ping_reply(line)
            unanswered = parse_ping_unanswered(line)
            with self._data:
                if reply is not None:
                    window.add_reply(*reply)
                elif unanswered is not None:
                    window.add_unanswered(unanswered)

    def _read_iperf(self, proc: subprocess.Popen[str], flow: _Flow) -> None:
        for line in _lines(proc):
            sample = parse_iperf_interval(line)
            if sample is not None:
                with self._data:
                    flow.iperf.append(sample)
            elif "error" in line:
                info(f"TRAFFIC_TOOL_ERROR {flow.flow_id} {line.strip()}\n")

    # ------------------------------------------------------------------ windows
    def _tick_loop(self) -> None:
        kpi_log = self._log_dir / "kpi.jsonl"
        with kpi_log.open("a") as out:
            while not self._stop.wait(self._config.window_s):
                for record in self._close_window():
                    out.write(json.dumps(record) + "\n")
                out.flush()

    def _close_window(self) -> list[Record]:
        ts = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        records = []
        with self._data:
            pings = {sta: window.close() for sta, window in self._pings.items()}
            for flow in self._flows.values():
                record = kpi_record(
                    flow.flow_id,
                    flow.app_class,
                    ts,
                    flow.take(pings[flow.sta]),
                    lost_latency_ms=self._config.ping_timeout_s * 1000,
                )
                if record is not None:
                    self._latest[flow.flow_id] = record
                    records.append(record)
        return records

    # ------------------------------------------------------------------ helpers
    def _popen(self, node: Any, command: list[str]) -> subprocess.Popen[str]:
        with self._lock:
            proc: subprocess.Popen[str] = node.popen(
                command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True
            )
        self._procs.append(proc)
        return proc

    def _spawn(self, target: Callable[[], None], name: str) -> None:
        thread = threading.Thread(target=target, name=name, daemon=True)
        thread.start()
        self._threads.append(thread)


def _lines(proc: subprocess.Popen[str]) -> IO[str]:
    if proc.stdout is None:
        raise RuntimeError("tool started without stdout=PIPE")
    return proc.stdout
