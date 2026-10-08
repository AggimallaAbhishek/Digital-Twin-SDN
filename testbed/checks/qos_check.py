#!/usr/bin/env python3
"""P4.4a QoS check, run ON THE VM (testbed/run_on_vm.sh, RYU_APP=controller.apps.twin_controller).

PHASE_PLAN P4.4a Done when: "A priority flow keeps its rate while best effort saturates the AP;
a rate limit holds within 10%". With the AP agent serving and the QoS hooks attached as in the
scenario runner:

1. ap1 saturated: one 2 Mbit/s video (the probe flow) + two 2.5 Mbit/s videos, 7 Mbit/s on a
   4.6 Mbit/s AP. The radio shares max-min fairly, so best effort gives the probe ~1.53 Mbit/s.
2. POST /flows/<probe>/queue {"queue_id": 1}: the probe flow keeps its 2 Mbit/s (within 10%).
3. On another AP, a 3 Mbit/s video with POST /flows/<f>/limit {"max_mbps": 1.5} holds 1.5
   Mbit/s within 10%.
4. Resetting the QoS restores the plain tree (no priority classes).
"""

from __future__ import annotations

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
from testbed.traffic.profiles import flow_id, load_traffic_config_file
from testbed.traffic.runner import TrafficProbe

SETTLE_S = 6  # a QoS change, then iperf3 / TCP-free UDP rates settle
MEASURE_S = 20
TOLERANCE = 0.10
PROBE_MBPS = 2.0  # above the max-min fair share (4.6 / 3 = 1.53), so best effort cuts it
LOAD_MBPS = 2.5  # per competing video: 2 + 2 x 2.5 = 7 Mbit/s on a 4.6 Mbit/s AP
LIMITED_MBPS = 3.0
LIMIT_MBPS = 1.5
LOADED = 2  # competing videos on ap1 (campus_v1 has 3 stations there)
LOG_DIR = Path.home() / "p44a"


def sample(fid: str, seconds: int) -> float:
    """Median throughput of `fid` from GET /kpi, sampled once a second."""
    values = []
    for _ in range(seconds):
        time.sleep(1)
        _, body = api("GET", "/kpi")
        values += [r["throughput_mbps"] for r in body.get("kpis", []) if r["flow_id"] == fid]
    return statistics.median(values) if values else float("nan")


def clients(ap: str) -> list[str]:
    _, body = api("GET", "/stations")
    names = [s["sta"] for s in body["stations"] if s["ap"] == ap]
    return sorted(names, key=lambda n: int(n[3:]))


def tc_classes(campus: Any, agent: ap_agent.ApAgent, ap: str) -> str:
    node = campus.aps[ap]
    with agent.lock:
        return str(node.cmd(f"tc class show dev {node.wintfs[0].name}"))


def check_priority(record: Recorder, campus: Any, agent: ap_agent.ApAgent, target: str) -> None:
    """Steps 1-2: the probe flow loses rate as best effort, keeps it in queue 1."""
    best_effort = sample(target, MEASURE_S)
    record(
        "saturated: best effort loses rate",
        best_effort < (1 - TOLERANCE) * PROBE_MBPS,
        f"{best_effort:.2f} Mbit/s",
    )
    status, body = api("POST", f"/flows/{target}/queue", {"queue_id": 1})
    record("POST queue", status == HTTPStatus.OK, str(body))
    record("priority classes installed", "class htb 1:10" in tc_classes(campus, agent, "ap1"))
    time.sleep(SETTLE_S)
    priority = sample(target, MEASURE_S)
    record(
        "priority flow keeps its rate",
        priority >= (1 - TOLERANCE) * PROBE_MBPS,
        f"{priority:.2f} Mbit/s (best effort {best_effort:.2f})",
    )


def check_limit(record: Recorder, limited: str) -> None:
    """Step 3: a 3 Mbit/s flow capped at 1.5 Mbit/s."""
    status, body = api("POST", f"/flows/{limited}/limit", {"max_mbps": LIMIT_MBPS})
    record("POST limit", status == HTTPStatus.OK, str(body))
    time.sleep(SETTLE_S)
    capped = sample(limited, MEASURE_S)
    record(
        "rate limit holds within 10%",
        abs(capped - LIMIT_MBPS) <= TOLERANCE * LIMIT_MBPS,
        f"{capped:.2f} Mbit/s (limit {LIMIT_MBPS})",
    )


def check_reset(
    record: Recorder, campus: Any, agent: ap_agent.ApAgent, target: str, limited: str
) -> None:
    """Step 4: GET /qos lists both flows; resetting them removes the priority classes."""
    status, qos = api("GET", "/qos")
    record("GET /qos", status == HTTPStatus.OK and set(qos["flows"]) == {target, limited}, str(qos))
    api("POST", f"/flows/{target}/queue", {"queue_id": 0})
    api("POST", f"/flows/{limited}/limit", {"max_mbps": None})
    _, qos = api("GET", "/qos")
    plain = "1:10" not in tc_classes(campus, agent, "ap1")
    record("QoS reset", qos["flows"] == {} and plain, str(qos))


def main() -> int:
    """Run the check; return a process exit code."""
    LOG_DIR.mkdir(exist_ok=True)
    layout = load_layout(DEFAULT_LAYOUT)
    campus = build_campus(layout, "127.0.0.1", 6653)
    record = Recorder()
    server, probe = None, None
    try:
        assoc = start_campus(campus)
        record("association", all(assoc.values()), f"{sum(assoc.values())}/{len(assoc)}")
        ping_matrix([*campus.servers.values(), *(sta for sta, _ in campus.stations)], count=1)
        agent = ap_agent.from_campus(campus)
        server = ap_agent.start_in_background(agent, host="127.0.0.1", port=ap_agent.DEFAULT_PORT)
        probe = TrafficProbe(campus, load_traffic_config_file(), LOG_DIR, lock=agent.lock)
        agent.kpi_source = probe.latest
        agent.flow_endpoints = probe.endpoints  # as testbed/run_scenario.py wires them
        probe.on_flows_started = agent.refresh_qos
        probe.start()
        on_ap1, on_ap4 = clients("ap1"), clients("ap4")
        enough = len(on_ap1) > LOADED and len(on_ap4) >= 1
        record("enough stations", enough, f"ap1={on_ap1} ap4={on_ap4}")
        target, limited = flow_id(on_ap1[0], "video"), flow_id(on_ap4[0], "video")
        items = [(on_ap1[0], "video", PROBE_MBPS), (on_ap4[0], "video", LIMITED_MBPS)]
        items += [(sta, "video", LOAD_MBPS) for sta in on_ap1[1 : LOADED + 1]]
        probe.start_flows(items)
        time.sleep(SETTLE_S)
        check_priority(record, campus, agent, target)
        check_limit(record, limited)
        check_reset(record, campus, agent, target, limited)
    finally:
        if probe is not None:
            probe.stop_all()
        if server is not None:
            server.shutdown()
        campus.net.stop()
    passed, total = record.verdict()
    verdict = "PASS" if passed == total else "FAIL"
    print(f"QOS_RESULT checks={passed}/{total} -> {verdict}")
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    setLogLevel("info")
    sys.exit(main())
