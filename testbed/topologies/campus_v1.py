#!/usr/bin/env python3
"""P1.1 campus topology: 4 APs, 2 switches, 1 server, 20 stations, built from config/campus_v1.yaml.

Runs on the testbed VM (Python 3.8). Usage, from the repo root on the VM (needs a controller
on 127.0.0.1:6653, e.g. via testbed/run_on_vm.sh):

    sudo python3 -m testbed.topologies.campus_v1 --check  # build, verify, stop; exit code = result
    sudo python3 -m testbed.topologies.campus_v1 --cli    # build and open the Mininet-WiFi CLI
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mininet.link import TCLink
from mininet.log import info, setLogLevel
from mininet.node import RemoteController
from mn_wifi.cli import CLI
from mn_wifi.link import wmediumd
from mn_wifi.net import Mininet_wifi
from mn_wifi.wmediumdConnector import interference

from testbed.connectivity import Pair, evaluate, ping_received
from testbed.layout import CampusLayout, load_layout, place_stations
from testbed.wifi_utils import ensure_associated, link_signal

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LAYOUT = REPO_ROOT / "config" / "campus_v1.yaml"
AP_SETTLE_S = 2.0


@dataclass
class Campus:
    """A built campus network and handles to its nodes."""

    net: Any
    controller: Any
    aps: dict[str, Any]
    switches: dict[str, Any]
    servers: dict[str, Any]
    stations: list[tuple[Any, Any]]  # (station node, AP node it should start on)


def build_campus(layout: CampusLayout, controller_ip: str, controller_port: int) -> Campus:
    """Create (but do not start) the Mininet-WiFi network described by `layout`."""
    wm = {"link": wmediumd, "wmediumd_mode": interference}
    if layout.wmediumd_mode != "interference":
        wm = {}
    net = Mininet_wifi(controller=RemoteController, **wm)
    controller = net.addController(
        "c0", controller=RemoteController, ip=controller_ip, port=controller_port
    )

    aps = {
        ap.name: net.addAccessPoint(
            ap.name,
            ssid=f"campus-{ap.name}",
            mode=ap.mode,
            channel=str(ap.channel),
            position=f"{ap.position[0]},{ap.position[1]},0",
        )
        for ap in layout.aps
    }
    switches = {name: net.addSwitch(name, protocols="OpenFlow13") for name in layout.switches}
    servers = {s.name: net.addHost(s.name, ip=s.ip) for s in layout.servers}
    stations = [
        (
            net.addStation(
                spec.name, ip=spec.ip, position=f"{spec.position[0]},{spec.position[1]},0"
            ),
            aps[spec.ap],
        )
        for spec in place_stations(layout)
    ]

    net.setPropagationModel(model=layout.propagation_model, exp=layout.propagation_exp)
    net.configureWifiNodes()

    nodes = {**aps, **switches, **servers}
    for a, b, bw in layout.wired_links:
        net.addLink(nodes[a], nodes[b], cls=TCLink, bw=bw)
    for s in layout.servers:
        net.addLink(servers[s.name], switches[s.switch], cls=TCLink, bw=s.bw_mbps)
    for sta, ap in stations:
        net.addLink(sta, ap)
    return Campus(net, controller, aps, switches, servers, stations)


def start_campus(campus: Campus) -> dict[str, bool]:
    """Start controller, switches and APs, then make sure every station is associated."""
    campus.net.build()
    campus.controller.start()
    for node in [*campus.aps.values(), *campus.switches.values()]:
        node.start([campus.controller])
    time.sleep(AP_SETTLE_S)
    return {sta.name: ensure_associated(sta, ap) for sta, ap in campus.stations}


def ping_matrix(hosts: list[Any], count: int, pairs: list[Pair] | None = None) -> dict[Pair, bool]:
    """Ping every ordered (src, dst) pair, or only `pairs`; return pair -> any reply received."""
    by_name = {h.name: h for h in hosts}
    todo = pairs or [(a.name, b.name) for a in hosts for b in hosts if a is not b]
    return {
        (src, dst): ping_received(by_name[src].cmd(f"ping -c{count} -W 1 {by_name[dst].IP()}"))
        for src, dst in todo
    }


def check(campus: Campus, assoc: dict[str, bool], layout: CampusLayout) -> bool:
    """Association + reachability + loss-budget check (testbed/connectivity.py)."""
    for sta, ap in campus.stations:
        info(f"ASSOC {sta.name} -> {ap.name} ok={assoc[sta.name]} {link_signal(sta)}\n")
    hosts = [*campus.servers.values(), *(sta for sta, _ in campus.stations)]
    ping_matrix(hosts, count=1)  # warm-up: ARP + controller MAC learning
    first = ping_matrix(hosts, count=1)
    failed = [pair for pair, ok in first.items() if not ok]
    retry = ping_matrix(hosts, count=layout.reach_ping_count, pairs=failed) if failed else {}
    report = evaluate(first, retry, layout.max_ping_loss_pct)
    for pair in report.first_try_failures:
        info(f"FIRST_TRY_LOSS {pair[0]} -> {pair[1]} recovered={pair not in report.unreachable}\n")
    print(report.summary("CAMPUS_RESULT", sum(assoc.values()), len(assoc)))
    return report.passed and all(assoc.values())


def main(argv: list[str] | None = None) -> int:
    """CLI entry point; returns a process exit code."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--layout", default=str(DEFAULT_LAYOUT))
    parser.add_argument("--controller-ip", default="127.0.0.1")
    parser.add_argument("--controller-port", type=int, default=6653)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="check association, reachability, loss")
    mode.add_argument("--cli", action="store_true", help="open the Mininet-WiFi CLI")
    args = parser.parse_args(argv)

    layout = load_layout(args.layout)
    campus = build_campus(layout, args.controller_ip, args.controller_port)
    try:
        assoc = start_campus(campus)
        if args.cli:
            CLI(campus.net)
            return 0
        return 0 if check(campus, assoc, layout) else 1
    finally:
        campus.net.stop()


if __name__ == "__main__":
    setLogLevel("info")
    sys.exit(main())
