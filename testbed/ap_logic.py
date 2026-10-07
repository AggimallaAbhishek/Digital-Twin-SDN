"""Pure logic for the AP agent (P1.3): request validation, `iw` output parsing, airtime.

No Mininet import, so it is unit-tested on the Mac. It runs on the testbed VM, so it must stay
Python 3.8-compatible (ADR-003). REST bodies are validated here before anything reaches a radio
(RULEBOOK C-2, N-5).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Tuple

# Static action bounds: must match common/schemas.py (tests/unit/test_ap_logic.py checks this).
CHANNELS = (1, 6, 11)
TX_POWER_DBM_MIN, TX_POWER_DBM_MAX = 5.0, 20.0

NOISE_FLOOR_DBM = -92.0  # mac80211_hwsim reports a fixed noise floor; APs give no survey data
FREQ_MHZ = {1: 2412, 6: 2437, 11: 2462}
CSA_BEACONS = 5  # channel switch announced this many beacons ahead; clients follow the AP

Counters = Dict[str, Tuple[int, int]]  # mac -> (rx_bytes, tx_bytes); typing.Dict for Python 3.8

_AP_NAME = re.compile(r"^ap[0-9]+$")
_MAC = r"([0-9a-f]{2}(?::[0-9a-f]{2}){5})"
_IW_ADDR = re.compile(r"^\s*addr " + _MAC, re.M)
_IW_CHANNEL = re.compile(r"^\s*channel (\d+) ", re.M)
_IW_TXPOWER = re.compile(r"^\s*txpower ([\d.]+) dBm", re.M)
_LINK_BSSID = re.compile(r"^Connected to " + _MAC, re.M)
_SIGNAL = re.compile(r"^\s*signal:\s+(-?[\d.]+) dBm", re.M)
_TX_BITRATE = re.compile(r"^\s*tx bitrate:\s+([\d.]+) MBit/s", re.M)
_RX_BITRATE = re.compile(r"^\s*rx bitrate:\s+([\d.]+) MBit/s", re.M)
_COUNTERS = {
    "tx_retries": re.compile(r"^\s*tx retries:\s+(\d+)", re.M),
    "rx_bytes": re.compile(r"^\s*rx bytes:\s+(\d+)", re.M),
    "tx_bytes": re.compile(r"^\s*tx bytes:\s+(\d+)", re.M),
}


@dataclass(frozen=True)
class IwInfo:
    """`iw dev <ap-intf> info`."""

    bssid: str | None
    channel: int | None
    tx_power_dbm: float | None


@dataclass(frozen=True)
class StationEntry:
    """One client in `iw dev <ap-intf> station dump` (rates as seen by the AP)."""

    mac: str
    signal_dbm: float | None
    tx_retries: int
    rx_bytes: int
    tx_bytes: int
    tx_bitrate_mbps: float | None  # AP -> station (downlink)
    rx_bitrate_mbps: float | None  # station -> AP (uplink)


@dataclass(frozen=True)
class Link:
    """`iw dev <sta-intf> link`: which AP a station is connected to (all None if none)."""

    bssid: str | None
    signal_dbm: float | None
    tx_bitrate_mbps: float | None


def parse_channel_request(body: Any) -> int:
    """Validate a POST /aps/{id}/channel body; return the channel or raise ValueError."""
    value = _single_field(body, "channel")
    if not _is_int(value) or value not in CHANNELS:
        raise ValueError(f"channel must be one of {CHANNELS}, got {value!r}")
    return int(value)


def parse_txpower_request(body: Any) -> int:
    """Validate a POST /aps/{id}/txpower body; return whole dBm (Mininet applies integers)."""
    value = _single_field(body, "dbm")
    if not _is_number(value) or not TX_POWER_DBM_MIN <= value <= TX_POWER_DBM_MAX:
        raise ValueError(
            f"dbm must be a number in [{TX_POWER_DBM_MIN}, {TX_POWER_DBM_MAX}], got {value!r}"
        )
    dbm: float = value
    return round(dbm)


def parse_associate_request(body: Any) -> str:
    """Validate a POST /stations/{id}/associate body; return the target AP name."""
    value = _single_field(body, "ap")
    if not isinstance(value, str) or not _AP_NAME.match(value):
        raise ValueError(f"ap must be an AP name like 'ap2', got {value!r}")
    return value


def chan_switch_cmd(intf: str, channel: int) -> str:
    """hostapd channel switch (CSA): associated clients follow the AP without reconnecting.

    Mininet-WiFi 2.7's own setChannel() runs this through a code path that silently does
    nothing on the VM (P1.3 probe, 2026-10-07), so the agent calls hostapd_cli itself.
    """
    return f"hostapd_cli -i {intf} chan_switch {CSA_BEACONS} {FREQ_MHZ[channel]}"


def parse_iw_info(text: str) -> IwInfo:
    """Parse `iw dev <intf> info`."""
    return IwInfo(
        bssid=_first(_IW_ADDR, text),
        channel=_int(_first(_IW_CHANNEL, text)),
        tx_power_dbm=_float(_first(_IW_TXPOWER, text)),
    )


def parse_station_dump(text: str) -> list[StationEntry]:
    """Parse `iw dev <ap-intf> station dump` into one entry per associated client."""
    blocks = re.split(r"^Station ", text, flags=re.M)[1:]
    return [_station_entry(block) for block in blocks]


def parse_link(text: str) -> Link:
    """Parse `iw dev <sta-intf> link`."""
    bssid = _first(_LINK_BSSID, text)
    if bssid is None:
        return Link(None, None, None)
    return Link(
        bssid=bssid,
        signal_dbm=_float(_first(_SIGNAL, text)),
        tx_bitrate_mbps=_float(_first(_TX_BITRATE, text)),
    )


def byte_counters(entries: list[StationEntry]) -> Counters:
    """Per-client byte counters, kept by the agent as the baseline for the next airtime estimate."""
    return {e.mac: (e.rx_bytes, e.tx_bytes) for e in entries}


def airtime_util(prev: Counters | None, entries: list[StationEntry], dt_s: float) -> float:
    """Fraction of the last `dt_s` seconds the AP's channel was busy with its clients' traffic.

    Decision P1.3-1: hwsim gives no channel survey for APs, so busy time is estimated as each
    client's bits in each direction divided by that direction's bitrate. Slow clients therefore
    use more airtime. Clients without a baseline or whose counters went backwards are skipped.
    """
    if prev is None or dt_s <= 0:
        return 0.0
    busy_s = 0.0
    for e in entries:
        if e.mac not in prev:
            continue
        rx0, tx0 = prev[e.mac]
        busy_s += _airtime_s(e.rx_bytes - rx0, e.rx_bitrate_mbps)
        busy_s += _airtime_s(e.tx_bytes - tx0, e.tx_bitrate_mbps)
    return min(1.0, busy_s / dt_s)


def snr_db(rssi_dbm: float | None) -> float | None:
    """SNR against the hwsim noise floor (decision P1.3-2)."""
    return None if rssi_dbm is None else rssi_dbm - NOISE_FLOOR_DBM


def _station_entry(block: str) -> StationEntry:
    counters = {name: int(_first(rx, block) or 0) for name, rx in _COUNTERS.items()}
    return StationEntry(
        mac=block.split(maxsplit=1)[0],
        signal_dbm=_float(_first(_SIGNAL, block)),
        tx_bitrate_mbps=_float(_first(_TX_BITRATE, block)),
        rx_bitrate_mbps=_float(_first(_RX_BITRATE, block)),
        **counters,
    )


def _airtime_s(delta_bytes: int, bitrate_mbps: float | None) -> float:
    if delta_bytes <= 0 or not bitrate_mbps:
        return 0.0
    return 8.0 * delta_bytes / (bitrate_mbps * 1e6)


def _first(pattern: re.Pattern[str], text: str) -> str | None:
    match = pattern.search(text)
    return match.group(1) if match else None


def _int(value: str | None) -> int | None:
    return None if value is None else int(value)


def _float(value: str | None) -> float | None:
    return None if value is None else float(value)


def _single_field(body: Any, key: str) -> Any:
    if not isinstance(body, Mapping) or set(body) != {key}:
        raise ValueError(f'body must be a JSON object with exactly one key, "{key}"')
    return body[key]


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)
