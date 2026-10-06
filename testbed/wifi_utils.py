"""Helpers for Mininet-WiFi nodes. Runs on the testbed VM (Python 3.8, ADR-003).

Mininet-WiFi 2.7 issues a single `iw connect` during build() and marks a station as associated
even when that failed (race with hostapd start-up). Every topology must call
ensure_associated() after the APs start (docs/setup.md, Known problems #4).
"""

from __future__ import annotations

import time
from typing import Any

ASSOC_RETRIES = 5
ASSOC_WAIT_S = 1.0


def is_connected(sta: Any) -> bool:
    """Return True if the kernel reports a link on the station's first wireless interface."""
    return "Connected to" in sta.cmd(f"iw dev {sta.wintfs[0].name} link")


def ensure_associated(
    sta: Any, ap: Any, retries: int = ASSOC_RETRIES, wait_s: float = ASSOC_WAIT_S
) -> bool:
    """Connect `sta` to `ap` until the kernel reports a link; return True on success."""
    intf, ap_intf = sta.wintfs[0], ap.wintfs[0]
    for _ in range(retries):
        if is_connected(sta):
            return True
        sta.cmd(f"iw dev {intf.name} disconnect")
        sta.cmd(f"iw dev {intf.name} connect {ap_intf.ssid} {ap_intf.mac}")
        time.sleep(wait_s)
    return is_connected(sta)


def link_signal(sta: Any) -> str:
    """Return the station's current 'signal: ... dBm' line, or '' if not connected."""
    link = sta.cmd(f"iw dev {sta.wintfs[0].name} link")
    return next((ln.strip() for ln in link.splitlines() if "signal" in ln), "")
