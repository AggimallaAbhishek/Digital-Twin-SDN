"""Helpers for Mininet-WiFi nodes. Runs on the testbed VM (Python 3.8, ADR-003).

Mininet-WiFi 2.7 issues a single `iw connect` during build() and marks a station as associated
even when that failed (race with hostapd start-up). Every topology must call
ensure_associated() after the APs start (docs/setup.md, Known problems #4).
"""

from __future__ import annotations

import contextlib
import time
from typing import Any, ContextManager

ASSOC_RETRIES = 5
ASSOC_WAIT_S = 1.0
STEER_ATTEMPTS = 2
STEER_WAIT_S = 4.0  # P1.3 probe: disconnect + connect to another AP took ~4 s
STEER_POLL_S = 0.5


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


def connected_to(sta: Any, ap: Any) -> bool:
    """True if the station's link is to this AP's BSSID (not just to any AP)."""
    return f"Connected to {ap.wintfs[0].mac}" in sta.cmd(f"iw dev {sta.wintfs[0].name} link")


def steer(
    sta: Any,
    ap: Any,
    attempts: int = STEER_ATTEMPTS,
    wait_s: float = STEER_WAIT_S,
    lock: ContextManager[Any] | None = None,
) -> bool:
    """Move `sta` to `ap` (disconnect, then connect to that BSSID); True once linked to it.

    Unlike ensure_associated(), which accepts a link to any AP, this checks the target BSSID.
    `lock` (the AP agent's) is held only around each shell command, not while waiting for the
    link, so a ~4 s steer does not block other node commands (stats polling, other walkers).
    """
    guard = lock if lock is not None else contextlib.nullcontext()
    intf, ap_intf = sta.wintfs[0], ap.wintfs[0]

    def linked() -> bool:
        with guard:
            return connected_to(sta, ap)

    for _ in range(attempts):
        if linked():
            return True
        with guard:
            sta.cmd(f"iw dev {intf.name} disconnect")
            sta.cmd(f"iw dev {intf.name} connect {ap_intf.ssid} {ap_intf.mac}")
        deadline = time.monotonic() + wait_s
        while time.monotonic() < deadline:
            time.sleep(STEER_POLL_S)
            if linked():
                return True
    return linked()


def link_signal(sta: Any) -> str:
    """Return the station's current 'signal: ... dBm' line, or '' if not connected."""
    link = sta.cmd(f"iw dev {sta.wintfs[0].name} link")
    return next((ln.strip() for ln in link.splitlines() if "signal" in ln), "")
