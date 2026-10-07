#!/usr/bin/env python3
"""P1.2 check (run ON THE VM via testbed/run_on_vm.sh with RYU_APP=controller.apps.twin_controller).

Builds the campus under the twin controller, then verifies the REST API end to end:
stats + topology endpoints, flow install that changes forwarding (drop sta1 -> srv1), delete
that restores it, error codes (400/404/409), and the QoS endpoint. Saves the REST responses as
fixtures for the Mac-side contract test (tests/contract/test_controller_fixtures.py).
Only talks to the controller over HTTP (testbed must not import controller, RULEBOOK §4).
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from http import HTTPStatus
from pathlib import Path
from typing import Any

from mininet.log import info, setLogLevel

from testbed.connectivity import ping_received
from testbed.layout import load_layout
from testbed.topologies.campus_v1 import DEFAULT_LAYOUT, build_campus, ping_matrix, start_campus

REST = os.environ.get("TWIN_REST", "http://127.0.0.1:8080")
# run_on_vm.sh passes LOG_DIR through sudo; Path.home() would be /root under sudo
FIXTURE_DIR = Path(os.environ.get("LOG_DIR", str(Path.home() / "p02"))) / "fixtures"
STATS_SETTLE_S = 4.0
FLOW_SETTLE_S = 1.5
EXPECTED_DATAPATHS = 6  # 4 APs + 2 switches (config/campus_v1.yaml)


def http(
    method: str, path: str, body: Any = None, base: str = REST, raw: bytes | None = None
) -> tuple[int, Any]:
    """Call a local REST API (controller by default); return (status, parsed JSON).

    `raw` sends those bytes as the body instead of JSON-encoding `body`.
    """
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(  # noqa: S310 - fixed local controller/agent URL
        base + path, data=data, method=method, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310 - as above
            return resp.status, json.loads(resp.read() or b"null")
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"null")


def reachable(src: Any, dst: Any) -> bool:
    """True if src gets at least one ping reply from dst (3 tries)."""
    return ping_received(src.cmd(f"ping -c3 -W1 {dst.IP()}"))


class Recorder:
    """Collects named check results and logs each one."""

    def __init__(self) -> None:
        self.results: list[tuple[str, bool]] = []

    def __call__(self, name: str, ok: bool, detail: str = "") -> None:
        self.results.append((name, ok))
        info(f"CHECK {'PASS' if ok else 'FAIL'} {name} {detail}\n")

    def verdict(self) -> tuple[int, int]:
        return sum(ok for _, ok in self.results), len(self.results)


def check_reads(record: Recorder) -> None:
    """GET endpoints respond, are populated, and are saved as fixtures."""
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    payloads = {}
    for name, path in (
        ("ports", "/stats/ports"),
        ("flows", "/stats/flows"),
        ("topology", "/topology"),
    ):
        status, payloads[name] = http("GET", path)
        (FIXTURE_DIR / f"ryu_{name}.json").write_text(json.dumps(payloads[name], indent=1))
        record(f"GET {path}", status == HTTPStatus.OK, f"HTTP {status}")
    topo = payloads["topology"]
    record(
        "topology datapaths",
        len(topo["switches"]) == EXPECTED_DATAPATHS,
        f"{len(topo['switches'])} switches, {len(topo['hosts'])} hosts learned",
    )
    busy = [p for p in payloads["ports"]["ports"] if p["rx_bytes"] > 0]
    record("port stats populated", len(busy) > 0, f"{len(busy)} ports with traffic")
    flows = payloads["flows"]["flows"]
    record("flow stats populated", len(flows) > 0, f"{len(flows)} flows")


def check_flow_control(record: Recorder, campus: Any) -> None:
    """A POSTed drop flow blocks sta1 -> srv1, is visible in OVS, and DELETE restores traffic."""
    s1, srv1 = campus.switches["s1"], campus.servers["srv1"]
    sta1, sta2 = campus.stations[0][0], campus.stations[1][0]
    record("baseline sta1 -> srv1 reachable", reachable(sta1, srv1))
    drop = {
        "flow_id": "check_block_sta1_srv1",
        "dpid": int(s1.dpid, 16),
        "priority": 200,
        "match": {"ipv4_src": sta1.IP(), "ipv4_dst": srv1.IP()},
        "actions": [{"drop": True}],
    }
    status, body = http("POST", "/flows", drop)
    record("POST /flows drop", status == HTTPStatus.CREATED, f"HTTP {status} {body}")
    time.sleep(FLOW_SETTLE_S)
    cookie = hex(body.get("cookie", 0)) if isinstance(body, dict) else "0x0"
    dump = s1.cmd("ovs-ofctl -O OpenFlow13 dump-flows s1")
    record("flow visible in ovs-ofctl", f"cookie={cookie}" in dump, cookie)
    record("drop flow blocks sta1 -> srv1", not reachable(sta1, srv1))
    record("other stations unaffected", reachable(sta2, srv1))

    status, _ = http("POST", "/flows", drop)
    record("duplicate flow_id -> 409", status == HTTPStatus.CONFLICT, f"HTTP {status}")
    status, err = http("POST", "/flows", {**drop, "flow_id": "x", "priority": 0})
    record("invalid body -> 400", status == HTTPStatus.BAD_REQUEST, f"HTTP {status} {err}")
    status, _ = http("POST", "/flows", {**drop, "flow_id": "y", "dpid": 999})
    record("unknown dpid -> 404", status == HTTPStatus.NOT_FOUND, f"HTTP {status}")

    status, _ = http("DELETE", "/flows/check_block_sta1_srv1")
    record("DELETE /flows", status == HTTPStatus.OK, f"HTTP {status}")
    time.sleep(FLOW_SETTLE_S)
    record("delete restores sta1 -> srv1", reachable(sta1, srv1))
    status, _ = http("DELETE", "/flows/check_block_sta1_srv1")
    record("delete unknown -> 404", status == HTTPStatus.NOT_FOUND, f"HTTP {status}")


def check_qos(record: Recorder, campus: Any) -> None:
    """POST /qos/queue installs a set_queue + output flow on s1."""
    s1, srv1 = campus.switches["s1"], campus.servers["srv1"]
    qos = {
        "flow_id": "check_qos_sta2",
        "dpid": int(s1.dpid, 16),
        "match": {"ipv4_src": campus.stations[1][0].IP()},
        "queue_id": 1,
        "out_port": s1.ports[s1.connectionsTo(srv1)[0][0]],
    }
    status, _ = http("POST", "/qos/queue", qos)
    time.sleep(FLOW_SETTLE_S)
    dump = s1.cmd("ovs-ofctl -O OpenFlow13 dump-flows s1")
    ok = status == HTTPStatus.CREATED and "set_queue:1" in dump
    record("POST /qos/queue", ok, f"HTTP {status}")
    http("DELETE", "/flows/check_qos_sta2")


def main() -> int:
    """Run all checks; return a process exit code."""
    campus = build_campus(load_layout(DEFAULT_LAYOUT), "127.0.0.1", 6653)
    record = Recorder()
    try:
        assoc = start_campus(campus)
        record("association", all(assoc.values()), f"{sum(assoc.values())}/{len(assoc)}")
        hosts = [*campus.servers.values(), *(sta for sta, _ in campus.stations)]
        ping_matrix(hosts, count=1)  # warm-up: MAC learning + traffic for the counters
        time.sleep(STATS_SETTLE_S)
        check_reads(record)
        check_flow_control(record, campus)
        check_qos(record, campus)
    finally:
        campus.net.stop()
    passed, total = record.verdict()
    verdict = "PASS" if passed == total else "FAIL"
    print(f"CONTROLLER_RESULT checks={passed}/{total} -> {verdict}")
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    setLogLevel("info")
    sys.exit(main())
