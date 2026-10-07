#!/usr/bin/env python3
"""P1.5 check (run ON THE VM via testbed/run_on_vm.sh with RYU_APP=controller.apps.twin_controller).

Runs one flow per profile from srv1 (video on sta1/ap1, bulk on sta4/ap2, web on sta9/ap3, and a
1.5 Mbit/s video on sta16/ap4 to test the scenario rate override) for RUN_S seconds with the AP
agent serving, and verifies: every flow produces KPI records with the KPIRecord fields in range,
GET /kpi returns the latest record of every flow, the measured values are plausible for an idle
campus, and stop_all() leaves no tool running. Artefacts for the contract test (P1.5): the full
record log <LOG_DIR>/kpi.jsonl and the /kpi response <LOG_DIR>/kpi_response.json.
"""

from __future__ import annotations

import json
import os
import statistics
import sys
import time
from http import HTTPStatus
from pathlib import Path
from typing import Any

from mininet.log import setLogLevel

from testbed import ap_agent
from testbed.checks.ap_agent_check import api
from testbed.checks.controller_check import Recorder
from testbed.layout import load_layout
from testbed.topologies.campus_v1 import DEFAULT_LAYOUT, build_campus, ping_matrix, start_campus
from testbed.traffic.profiles import (
    APP_CLASSES,
    IperfProfile,
    TrafficConfig,
    flow_id,
    load_traffic_config_file,
)
from testbed.traffic.runner import TrafficProbe

FLOWS = [("sta1", "video", None), ("sta4", "bulk", None), ("sta9", "web", None)]
OVERRIDE_FLOW = ("sta16", "video", 1.5)  # scenario rate_mbps overrides the profile's 3 Mbit/s
CLASS_OF = {flow_id(sta, cls): cls for sta, cls, _ in [*FLOWS, OVERRIDE_FLOW]}
RUN_S = 30
SETTLE_S = 3  # iperf3 windows skipped: iperf3 connecting, pings not yet past their timeout
SEED = 1
RATE_TOLERANCE = 0.10  # median video throughput within 10% of the configured rate
MAX_IDLE_LOSS_PCT = 5.0  # wmediumd drops ~1-3% of frames on an idle campus (setup.md #8)
MAX_IDLE_LATENCY_MS = 100.0
MIN_BULK_MBPS = 1.0
MAX_PERCENT = 100.0
MIN_WEB_RECORDS = 5  # one fetch every ~2-3 s (500 KB + 2 s mean think time)
FIELDS = {
    "ts",
    "flow_id",
    "app_class",
    "throughput_mbps",
    "latency_ms",
    "jitter_ms",
    "loss_pct",
}


def record_ok(record: dict[str, Any]) -> bool:
    """KPIRecord fields (minus scenario_id/run_id, added by the collector) with valid values."""
    if set(record) != FIELDS or record["app_class"] not in APP_CLASSES:
        return False
    numbers = [record[k] for k in ("throughput_mbps", "latency_ms", "jitter_ms", "loss_pct")]
    if not all(isinstance(v, (int, float)) and v >= 0 for v in numbers):
        return False
    return bool(record["loss_pct"] <= MAX_PERCENT)


def median(records: list[dict[str, Any]], key: str) -> float:
    """Median of `key` over the records (NaN when there are none, which fails every bound)."""
    return statistics.median(r[key] for r in records) if records else float("nan")


def check_records(
    record: Recorder, by_flow: dict[str, list[dict[str, Any]]], config: TrafficConfig
) -> None:
    """Every flow measured, every record valid, values plausible for an idle campus."""
    every = [r for rs in by_flow.values() for r in rs]
    bad = [r for r in every if not record_ok(r)]
    record(
        "records have the KPIRecord fields in range",
        not bad,
        f"{len(every)} records, bad={bad[:2]}",
    )
    expected_iperf = RUN_S - SETTLE_S - 2
    for fid, records in sorted(by_flow.items()):
        need = MIN_WEB_RECORDS if CLASS_OF[fid] == "web" else expected_iperf
        record(f"{fid} records", len(records) >= need, f"{len(records)} (need >= {need})")
        latency = median(records, "latency_ms")
        record(f"{fid} median latency", latency < MAX_IDLE_LATENCY_MS, f"{latency:.1f} ms")
        loss = median(records, "loss_pct")
        record(f"{fid} median loss", loss <= MAX_IDLE_LOSS_PCT, f"{loss:.1f}%")
    video = config.profiles["video"]
    video_mbps = video.rate_mbps if isinstance(video, IperfProfile) else None
    for sta, cls, rate in [*FLOWS, OVERRIDE_FLOW]:
        fid = flow_id(sta, cls)
        records = by_flow.get(fid, [])
        mbps = median(records, "throughput_mbps")
        if cls == "video":
            target = rate or video_mbps or 0.0
            ok = abs(mbps - target) <= RATE_TOLERANCE * target
            record(f"{fid} median throughput ~{target:g} Mbit/s", ok, f"{mbps:.2f}")
        elif cls == "bulk":
            record(f"{fid} median throughput", mbps >= MIN_BULK_MBPS, f"{mbps:.2f} Mbit/s")
        else:
            record(f"{fid} fetches succeed", mbps > 0, f"median goodput {mbps:.2f} Mbit/s")


def main() -> int:
    """Run the check; return a process exit code."""
    log_dir = Path(os.environ.get("LOG_DIR", str(Path.home() / "p02")))
    kpi_log = log_dir / "kpi.jsonl"
    kpi_log.unlink(missing_ok=True)  # this run's records only
    layout = load_layout(DEFAULT_LAYOUT)
    campus = build_campus(layout, "127.0.0.1", 6653)
    record = Recorder()
    server, probe = None, None
    try:
        assoc = start_campus(campus)
        record("association", all(assoc.values()), f"{sum(assoc.values())}/{len(assoc)}")
        hosts = [*campus.servers.values(), *(sta for sta, _ in campus.stations)]
        ping_matrix(hosts, count=1)  # warm-up: ARP + controller MAC learning
        agent = ap_agent.from_campus(campus)
        server = ap_agent.start_in_background(agent, host="127.0.0.1", port=ap_agent.DEFAULT_PORT)
        config = load_traffic_config_file()
        probe = TrafficProbe(campus, config, log_dir, lock=agent.lock, seed=SEED)
        agent.kpi_source = probe.latest
        status, empty = api("GET", "/kpi")
        record(
            "GET /kpi before traffic", status == HTTPStatus.OK and empty["kpis"] == [], str(empty)
        )
        probe.start()
        flow_ids = [probe.start_flow(sta, cls, rate) for sta, cls, rate in [*FLOWS, OVERRIDE_FLOW]]
        time.sleep(RUN_S)
        status, body = api("GET", "/kpi")
        latest = {r["flow_id"]: r for r in body.get("kpis", [])}
        record(
            "GET /kpi returns every flow",
            status == HTTPStatus.OK and sorted(latest) == sorted(flow_ids),
            f"{sorted(latest)}",
        )
        (log_dir / "kpi_response.json").write_text(json.dumps(body, indent=1))
        probe.stop_all()
        record("stop_all stops every tool", probe.running_processes() == 0, "")
        by_flow: dict[str, list[dict[str, Any]]] = {fid: [] for fid in flow_ids}
        for line in kpi_log.read_text().splitlines():
            r = json.loads(line)
            by_flow.setdefault(r["flow_id"], []).append(r)
        settled = {f: rs if CLASS_OF[f] == "web" else rs[SETTLE_S:] for f, rs in by_flow.items()}
        check_records(record, settled, config)
    finally:
        if probe is not None:
            probe.stop_all()
        if server is not None:
            server.shutdown()
        campus.net.stop()
    passed, total = record.verdict()
    verdict = "PASS" if passed == total else "FAIL"
    print(f"TRAFFIC_RESULT checks={passed}/{total} -> {verdict}")
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    setLogLevel("info")
    sys.exit(main())
