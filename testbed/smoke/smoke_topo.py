#!/usr/bin/env python3
"""P0.2 smoke test: 2 APs, 4 stations, remote Ryu (simple_switch_13), wmediumd interference.

Mininet-WiFi 2.7 issues a single `iw connect` during build() and marks the station
associated even if it failed (race with hostapd start-up). ensure_associated() checks the
real kernel link state and retries, so the topology does not depend on that timing.
"""
import sys
import time

from mininet.log import info, setLogLevel
from mininet.node import RemoteController
from mn_wifi.link import wmediumd
from mn_wifi.net import Mininet_wifi
from mn_wifi.wmediumdConnector import interference


def ensure_associated(sta, ap, retries=5, wait_s=1.0):
    """Connect sta to ap until the kernel reports a link; return True on success."""
    intf = sta.wintfs[0]
    for _ in range(retries):
        if "Connected to" in sta.cmd("iw dev %s link" % intf.name):
            return True
        sta.cmd("iw dev %s disconnect" % intf.name)
        sta.cmd("iw dev %s connect %s %s" % (intf.name, ap.wintfs[0].ssid, ap.wintfs[0].mac))
        time.sleep(wait_s)
    return "Connected to" in sta.cmd("iw dev %s link" % intf.name)


def main():
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
    time.sleep(2)

    assoc = {sta.name: ensure_associated(sta, ap) for sta, ap in plan}
    for sta, ap in plan:
        link = sta.cmd("iw dev %s-wlan0 link" % sta.name)
        sig = [l.strip() for l in link.splitlines() if "signal" in l]
        info("ASSOC %s -> %s ok=%s %s\n" % (sta.name, ap.name, assoc[sta.name], sig[0] if sig else ""))

    net.pingAll(timeout="1")              # warm-up: lets the controller learn MACs
    loss = net.pingAll(timeout="1")
    net.stop()
    ok = all(assoc.values()) and loss == 0
    print("SMOKE_RESULT assoc=%d/%d loss=%s%% -> %s" % (sum(assoc.values()), len(assoc), loss, "PASS" if ok else "FAIL"))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    setLogLevel("info")
    main()
