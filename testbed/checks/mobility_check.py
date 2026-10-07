#!/usr/bin/env python3
"""P1.4 check (run ON THE VM via testbed/run_on_vm.sh with RYU_APP=controller.apps.twin_controller).

Plays a shortened flash crowd (6 corridor + 4 library stations walk to the lecture hall, leaving
over 20 s from t=5 s) with the AP agent serving, and verifies: sampled positions lie on the
planned paths, every walker ends inside the lecture hall on ap1 with a usable signal and
reaches srv1, the other stations do not move, and the agent's stats stay responsive throughout.
"""

from __future__ import annotations

import math
import sys
import threading
import time
from http import HTTPStatus
from typing import Any

from mininet.log import setLogLevel

from testbed import ap_agent
from testbed.checks.ap_agent_check import api
from testbed.checks.controller_check import Recorder, reachable
from testbed.layout import CampusLayout, load_layout, place_stations
from testbed.mobility.crowd import Walk, parse_groups, plan_crowd
from testbed.mobility.runner import CrowdRunner
from testbed.topologies.campus_v1 import DEFAULT_LAYOUT, build_campus, ping_matrix, start_campus

GROUPS = [
    {"stations": 6, "from": "corridor", "to": "lecture_hall", "start_s": 5, "spread_s": 20},
    {"stations": 4, "from": "library", "to": "lecture_hall", "start_s": 5, "spread_s": 20},
]
SEED = 1
TARGET_ZONE, TARGET_AP = "lecture_hall", "ap1"
MIN_RSSI_DBM = -75.0  # steering bound (PROJECT_PLAN §7.3)
ON_PATH_TOLERANCE_M = 1.5  # one tick of walking (1.2 m) plus rounding
MAX_STATS_LATENCY_S = 2.0
POLL_S = 1.0
STEER_ALLOWANCE_S = 15.0  # last arrival + re-association


def _stations_now() -> dict[str, dict[str, Any]]:
    _, body = api("GET", "/stations")
    return {s["sta"]: s for s in body["stations"]}


def _off_path_m(
    point: tuple[float, float], a: tuple[float, float], b: tuple[float, float]
) -> float:
    """Distance from `point` to the segment a-b."""
    (px, py), (ax, ay), (bx, by) = point, a, b
    length2 = (bx - ax) ** 2 + (by - ay) ** 2
    f = (
        0.0
        if length2 == 0
        else max(0.0, min(1.0, ((px - ax) * (bx - ax) + (py - ay) * (by - ay)) / length2))
    )
    return math.dist(point, (ax + f * (bx - ax), ay + f * (by - ay)))


def play(record: Recorder, runner: CrowdRunner, walks: list[Walk]) -> None:
    """Run the crowd while polling the agent: path samples, stats latency, schedule, arrivals."""
    walkers = {w.sta: w for w in walks}
    thread = threading.Thread(target=runner.run, daemon=True)
    started = time.monotonic()
    thread.start()
    latencies, worst_off_path, mid_walk_samples = [], 0.0, 0
    while thread.is_alive():
        t0 = time.monotonic()
        status, _ = api("GET", f"/aps/{TARGET_AP}/stats")
        latencies.append(time.monotonic() - t0 if status == HTTPStatus.OK else math.inf)
        t = time.monotonic() - started
        for name, sta in _stations_now().items():
            walk = walkers.get(name)
            if walk and walk.start_s + 1 < t < walk.end_s - 1:
                mid_walk_samples += 1
                off = _off_path_m((sta["x"], sta["y"]), walk.src, walk.dst)
                worst_off_path = max(worst_off_path, off)
        time.sleep(POLL_S)
    thread.join()
    elapsed = time.monotonic() - started
    last_end = max(w.end_s for w in walks)

    record("walkers sampled mid-walk", mid_walk_samples > 0, f"{mid_walk_samples} samples")
    record(
        "positions follow the planned paths",
        worst_off_path <= ON_PATH_TOLERANCE_M,
        f"worst {worst_off_path:.2f} m off path",
    )
    record(
        "stats stay responsive while walking",
        max(latencies) < MAX_STATS_LATENCY_S,
        f"max {max(latencies):.2f} s over {len(latencies)} polls",
    )
    record(
        "crowd finishes on schedule",
        elapsed <= last_end + STEER_ALLOWANCE_S,
        f"{elapsed:.0f} s (last walk ends at {last_end:.0f} s)",
    )
    failed = [a.sta for a in runner.arrivals if not (a.associated and a.ap == TARGET_AP)]
    record(
        f"all walkers re-associated to {TARGET_AP}",
        len(runner.arrivals) == len(walks) and not failed,
        f"{len(runner.arrivals)} arrivals, failed={failed}",
    )


def check_end_state(
    record: Recorder, layout: CampusLayout, walkers: set[str], before: dict[str, dict[str, Any]]
) -> None:
    """Walkers in the lecture hall on ap1 with a usable signal; everyone else untouched."""
    after = _stations_now()
    hall = layout.zones[TARGET_ZONE]
    outside = [n for n in walkers if not hall.contains(after[n]["x"], after[n]["y"])]
    record(f"walkers inside {TARGET_ZONE}", not outside, f"outside={outside}")
    wrong_ap = {n: after[n]["ap"] for n in walkers if after[n]["ap"] != TARGET_AP}
    record(f"agent reports walkers on {TARGET_AP}", not wrong_ap, str(wrong_ap))
    weak = {
        n: after[n]["rssi_dbm"]
        for n in walkers
        if after[n]["rssi_dbm"] is None or after[n]["rssi_dbm"] < MIN_RSSI_DBM
    }
    record(f"walkers' signal >= {MIN_RSSI_DBM} dBm", not weak, str(weak))
    moved = [
        n
        for n in after
        if n not in walkers
        and (after[n]["x"], after[n]["y"], after[n]["ap"])
        != (before[n]["x"], before[n]["y"], before[n]["ap"])
    ]
    record("other stations unchanged", not moved, f"changed={moved}")
    _, stats = api("GET", f"/aps/{TARGET_AP}/stats")
    expected = sum(1 for s in before.values() if s["ap"] == TARGET_AP) + len(walkers)
    record(
        f"{TARGET_AP} client count",
        stats["n_clients"] == expected,
        f"{stats['n_clients']} (expected {expected})",
    )


def main() -> int:
    """Run the check; return a process exit code."""
    layout = load_layout(DEFAULT_LAYOUT)
    walks = plan_crowd(parse_groups(GROUPS), layout, place_stations(layout), seed=SEED)
    walkers = {w.sta for w in walks}
    campus = build_campus(layout, "127.0.0.1", 6653)
    record = Recorder()
    server = None
    try:
        assoc = start_campus(campus)
        record("association", all(assoc.values()), f"{sum(assoc.values())}/{len(assoc)}")
        hosts = [*campus.servers.values(), *(sta for sta, _ in campus.stations)]
        ping_matrix(hosts, count=1)  # warm-up: ARP + controller MAC learning
        agent = ap_agent.from_campus(campus)
        server = ap_agent.start_in_background(agent, host="127.0.0.1", port=ap_agent.DEFAULT_PORT)
        time.sleep(0.5)
        before = _stations_now()
        play(record, CrowdRunner(walks, layout, campus, lock=agent.lock), walks)
        check_end_state(record, layout, walkers, before)
        srv1, nodes = campus.servers["srv1"], {sta.name: sta for sta, _ in campus.stations}
        with agent.lock:
            unreachable = [n for n in sorted(walkers) if not reachable(nodes[n], srv1)]
        record("walkers reach srv1", not unreachable, f"unreachable={unreachable}")
    finally:
        if server is not None:
            server.shutdown()
        campus.net.stop()
    passed, total = record.verdict()
    verdict = "PASS" if passed == total else "FAIL"
    print(f"MOBILITY_RESULT checks={passed}/{total} -> {verdict}")
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    setLogLevel("info")
    sys.exit(main())
