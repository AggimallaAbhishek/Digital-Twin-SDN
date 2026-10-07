#!/usr/bin/env python3
"""P1.3 check (run ON THE VM via testbed/run_on_vm.sh with RYU_APP=controller.apps.twin_controller).

Builds the campus, starts the AP agent in-process, and verifies its REST API end to end over HTTP:
reads (4 APs, 20 associated stations, airtime after traffic), a channel switch that clients follow,
a tx-power change, steering sta2 to ap2, and error codes (422/404). Every change is confirmed
with `iw` independently of the agent. Saves the GET responses as fixtures for the Mac-side
contract test (tests/contract/test_ap_agent_fixtures.py).
"""

from __future__ import annotations

import json
import sys
import time
from http import HTTPStatus
from typing import Any

from mininet.log import setLogLevel

from testbed import ap_agent, ap_logic
from testbed.checks.controller_check import FIXTURE_DIR, Recorder, http, reachable
from testbed.layout import load_layout
from testbed.topologies.campus_v1 import DEFAULT_LAYOUT, build_campus, ping_matrix, start_campus

PORT = ap_agent.DEFAULT_PORT
AGENT = f"http://127.0.0.1:{PORT}"
EXPECTED_APS = {"ap1": 1, "ap2": 6, "ap3": 11, "ap4": 1}  # config/campus_v1.yaml channels
EXPECTED_STATIONS = 20
NEW_CHANNEL = 6
NEW_TX_POWER_DBM = 10


def api(method: str, path: str, body: Any = None, raw: bytes | None = None) -> tuple[int, Any]:
    return http(method, path, body, base=AGENT, raw=raw)


def iw_info(agent: ap_agent.ApAgent, ap: Any) -> ap_logic.IwInfo:
    with agent.lock:  # node shells are shared with the agent's HTTP thread
        return ap_logic.parse_iw_info(ap.cmd(f"iw dev {ap.wintfs[0].name} info"))


def bssid_of(agent: ap_agent.ApAgent, sta: Any) -> str | None:
    with agent.lock:
        return ap_logic.parse_link(sta.cmd(f"iw dev {sta.wintfs[0].name} link")).bssid


def check_reads(record: Recorder, agent: ap_agent.ApAgent, campus: Any) -> None:
    """GET endpoints: 4 APs on their configured channels, 20 associated stations, airtime."""
    status, aps = api("GET", "/aps")
    record("GET /aps", status == HTTPStatus.OK, f"HTTP {status}")
    channels = {a["ap"]: a["channel"] for a in aps["aps"]}
    record("APs on configured channels", channels == EXPECTED_APS, str(channels))

    status, stations = api("GET", "/stations")
    record("GET /stations", status == HTTPStatus.OK, f"HTTP {status}")
    associated = [s for s in stations["stations"] if s["ap"]]
    record(
        "all stations associated",
        len(associated) == EXPECTED_STATIONS,
        f"{len(associated)}/{len(stations['stations'])}",
    )

    sta1, srv1 = campus.stations[0][0], campus.servers["srv1"]
    api("GET", "/aps/ap1/stats")  # baseline for the airtime estimate
    with agent.lock:
        sta1.cmd(f"ping -c 40 -i 0.05 -s 1400 -W 1 {srv1.IP()}")
    stats = {}
    for name in sorted(EXPECTED_APS):
        status, stats[name] = api("GET", f"/aps/{name}/stats")
        record(f"GET /aps/{name}/stats", status == HTTPStatus.OK, f"HTTP {status}")
    util = stats["ap1"]["channel_util"]
    record("ap1 airtime > 0 after traffic", util > 0, f"channel_util={util:.4f}")

    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    for name, payload in (
        ("aps", aps),
        ("ap_stats", {"aps": list(stats.values())}),
        ("stations", stations),
    ):
        (FIXTURE_DIR / f"ap_agent_{name}.json").write_text(json.dumps(payload, indent=1))


def check_writes(record: Recorder, agent: ap_agent.ApAgent, campus: Any) -> None:
    """Channel switch (clients follow), tx power, steering; each confirmed with iw."""
    ap1, ap2, srv1 = campus.aps["ap1"], campus.aps["ap2"], campus.servers["srv1"]
    on_ap1 = [sta for sta, ap in campus.stations if ap is ap1]
    sta2 = on_ap1[1]

    status, body = api("POST", "/aps/ap1/channel", {"channel": NEW_CHANNEL})
    record(f"POST channel ap1 -> {NEW_CHANNEL}", status == HTTPStatus.OK, f"HTTP {status} {body}")
    record(f"iw shows ap1 on channel {NEW_CHANNEL}", iw_info(agent, ap1).channel == NEW_CHANNEL)
    followed = [s.name for s in on_ap1 if bssid_of(agent, s) == ap1.wintfs[0].mac]
    record("ap1 clients follow the switch", len(followed) == len(on_ap1), str(followed))
    with agent.lock:
        record("sta1 -> srv1 after switch", reachable(on_ap1[0], srv1))

    status, body = api("POST", "/aps/ap1/txpower", {"dbm": NEW_TX_POWER_DBM})
    ok = status == HTTPStatus.OK
    record(f"POST txpower ap1 -> {NEW_TX_POWER_DBM}", ok, f"HTTP {status} {body}")
    applied = iw_info(agent, ap1).tx_power_dbm
    record(f"iw shows ap1 at {NEW_TX_POWER_DBM} dBm", applied == NEW_TX_POWER_DBM, str(applied))

    status, body = api("POST", f"/stations/{sta2.name}/associate", {"ap": "ap2"})
    record(f"POST associate {sta2.name} -> ap2", status == HTTPStatus.OK, f"HTTP {status} {body}")
    record(f"iw shows {sta2.name} on ap2", bssid_of(agent, sta2) == ap2.wintfs[0].mac)
    _, stations = api("GET", "/stations")
    now_on = {s["sta"]: s["ap"] for s in stations["stations"]}[sta2.name]
    record(f"GET /stations shows {sta2.name} on ap2", now_on == "ap2", str(now_on))
    with agent.lock:
        record(f"{sta2.name} -> srv1 after steering", reachable(sta2, srv1))


def check_errors(record: Recorder) -> None:
    """Invalid input -> 422 (nothing applied), unknown names/paths -> 404."""
    cases = [
        ("off-plan channel", "POST", "/aps/ap1/channel", {"channel": 3}, None, 422),
        ("tx power above max", "POST", "/aps/ap1/txpower", {"dbm": 25}, None, 422),
        ("invalid JSON", "POST", "/aps/ap1/channel", None, b"{nope", 422),
        ("associate to a non-AP", "POST", "/stations/sta1/associate", {"ap": "s1"}, None, 422),
        ("unknown AP stats", "GET", "/aps/ap9/stats", None, None, 404),
        ("unknown AP channel", "POST", "/aps/ap9/channel", {"channel": 6}, None, 404),
        ("unknown station", "POST", "/stations/sta99/associate", {"ap": "ap2"}, None, 404),
        ("associate to unknown AP", "POST", "/stations/sta1/associate", {"ap": "ap9"}, None, 404),
        ("unknown path", "GET", "/nope", None, None, 404),
    ]
    for name, method, path, body, raw, expected in cases:
        status, err = api(method, path, body, raw=raw)
        record(f"{name} -> {expected}", status == expected, f"HTTP {status} {err}")


def main() -> int:
    """Run all checks; return a process exit code."""
    campus = build_campus(load_layout(DEFAULT_LAYOUT), "127.0.0.1", 6653)
    record = Recorder()
    server = None
    try:
        assoc = start_campus(campus)
        record("association", all(assoc.values()), f"{sum(assoc.values())}/{len(assoc)}")
        hosts = [*campus.servers.values(), *(sta for sta, _ in campus.stations)]
        ping_matrix(hosts, count=1)  # warm-up: ARP + controller MAC learning
        agent = ap_agent.from_campus(campus)
        server = ap_agent.start_in_background(agent, host="127.0.0.1", port=PORT)
        time.sleep(0.5)
        check_reads(record, agent, campus)
        check_writes(record, agent, campus)
        check_errors(record)
    finally:
        if server is not None:
            server.shutdown()
        campus.net.stop()
    passed, total = record.verdict()
    verdict = "PASS" if passed == total else "FAIL"
    print(f"AP_AGENT_RESULT checks={passed}/{total} -> {verdict}")
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    setLogLevel("info")
    sys.exit(main())
