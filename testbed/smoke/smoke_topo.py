#!/usr/bin/env python3
"""P0.2 smoke test: 2 APs, 4 stations, remote Ryu (simple_switch_13), wmediumd interference.

Runs on the testbed VM (Python 3.8, ADR-003). Mininet-WiFi 2.7 issues a single `iw connect`
during build() and marks the station associated even if it failed (race with hostapd start-up).
testbed.wifi_utils.ensure_associated() checks the real kernel link state and retries
(docs/setup.md, Known problems #4). Run from the repo root: python3 -m testbed.smoke.smoke_topo
"""

from __future__ import annotations

import sys
import time

from mininet.log import info, setLogLevel
from mininet.node import RemoteController
from mn_wifi.link import wmediumd
from mn_wifi.net import Mininet_wifi
from mn_wifi.wmediumdConnector import interference

from testbed.wifi_utils import ensure_associated, link_signal

AP_SETTLE_S = 2.0


def main() -> int:
    """Build the topology, verify association and connectivity; return a process exit code."""
    net = Mininet_wifi(controller=RemoteController, link=wmediumd, wmediumd_mode=interference)
    c0 = net.addController("c0", controller=RemoteController, ip="127.0.0.1", port=6653)
    ap1 = net.addAccessPoint("ap1", ssid="ssid-ap1", mode="g", channel="1", position="30,50,0")
    ap2 = net.addAccessPoint("ap2", ssid="ssid-ap2", mode="g", channel="6", position="90,50,0")
    plan = [
        (net.addStation("sta1", ip="10.0.0.1/8", position="20,40,0"), ap1),
        (net.addStation("sta2", ip="10.0.0.2/8", position="35,60,0"), ap1),
        (net.addStation("sta3", ip="10.0.0.3/8", position="85,40,0"), ap2),
        (net.addStation("sta4", ip="10.0.0.4/8", position="100,60,0"), ap2),
    ]
    net.setPropagationModel(model="logDistance", exp=4)
    net.configureWifiNodes()
    net.addLink(ap1, ap2)
    for sta, ap in plan:
        net.addLink(sta, ap)
    net.build()
    c0.start()
    ap1.start([c0])
    ap2.start([c0])
    time.sleep(AP_SETTLE_S)

    assoc = {sta.name: ensure_associated(sta, ap) for sta, ap in plan}
    for sta, ap in plan:
        info(f"ASSOC {sta.name} -> {ap.name} ok={assoc[sta.name]} {link_signal(sta)}\n")

    net.pingAll(timeout="1")  # warm-up: lets the controller learn MACs
    loss = net.pingAll(timeout="1")
    net.stop()

    ok = all(assoc.values()) and loss == 0
    verdict = "PASS" if ok else "FAIL"
    print(f"SMOKE_RESULT assoc={sum(assoc.values())}/{len(assoc)} loss={loss}% -> {verdict}")
    return 0 if ok else 1


if __name__ == "__main__":
    setLogLevel("info")
    sys.exit(main())
