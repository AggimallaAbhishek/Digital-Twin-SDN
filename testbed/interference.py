"""Co-channel interference model (P1.6, deviation #7): which APs to cap, and the tc commands.

mac80211_hwsim + wmediumd on the VM give every AP ~4.6 Mbit/s whatever the bitrate, and APs on
the same channel do not slow each other down (P1.6 calibration). So the scenario runner emulates
interference explicitly: while APs that are up share a channel, each one's downlink is capped at

    cap = ap_capacity_mbps / (1 + sum of w(d) over same-channel APs that are up)
    w(d) = 1 for d <= cochannel_full_m, 0 for d >= cochannel_zero_m, linear in between

and the cap follows the live channels, so a channel change really removes it. The twin's
airtime model (P3.3) uses the same `radio_model` section of config/campus_v1.yaml.

Pure Python (no Mininet import), unit-tested on the Mac and run on the VM (Python 3.8, ADR-003).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

_KEYS = ("ap_capacity_mbps", "cochannel_full_m", "cochannel_zero_m", "orphan_rejoin_s")


@dataclass(frozen=True)
class RadioModel:
    """Emulation parameters from config/campus_v1.yaml `radio_model`."""

    ap_capacity_mbps: float
    cochannel_full_m: float
    cochannel_zero_m: float
    orphan_rejoin_s: float


@dataclass(frozen=True)
class ApRadio:
    """An AP's live radio state: where it is, its channel, and whether it is up."""

    name: str
    position: tuple[float, float]
    channel: int
    up: bool = True


def load_radio_model(campus: Mapping[str, Any]) -> RadioModel:
    """Validate the `radio_model` section of a parsed campus YAML; ValueError names the field."""
    raw = campus.get("radio_model")
    if not isinstance(raw, Mapping):
        raise ValueError("campus config has no radio_model section")
    unknown = set(raw) - set(_KEYS)
    if unknown:
        raise ValueError(f"radio_model: unknown keys {sorted(unknown)}")
    values: dict[str, float] = {}
    for key in _KEYS:
        value: Any = raw.get(key)
        if not _is_number(value) or value < 0 or (key == "ap_capacity_mbps" and value == 0):
            raise ValueError(f"radio_model.{key} must be a number >= 0 (> 0 for capacity)")
        values[key] = float(value)
    if values["cochannel_zero_m"] <= values["cochannel_full_m"]:
        raise ValueError("radio_model.cochannel_zero_m must be greater than cochannel_full_m")
    return RadioModel(**values)


def capacity_caps(aps: Sequence[ApRadio], model: RadioModel) -> dict[str, float | None]:
    """Downlink cap (Mbit/s, 2 decimals) for every AP; None where nothing interferes."""
    caps: dict[str, float | None] = {}
    for ap in aps:
        load = sum(
            _weight(math.dist(ap.position, other.position), model)
            for other in aps
            if other is not ap and other.up and other.channel == ap.channel
        )
        caps[ap.name] = round(model.ap_capacity_mbps / (1 + load), 2) if ap.up and load else None
    return caps


def tc_commands(intf: str, cap_mbps: float | None) -> list[str]:
    """Shell commands that cap `intf`'s egress (AP downlink) at `cap_mbps`, or remove the cap."""
    if cap_mbps is None:
        return [f"tc qdisc del dev {intf} root"]  # back to the kernel default (mq + fq_codel)
    rate = f"{cap_mbps:g}mbit"
    return [
        f"tc qdisc replace dev {intf} root handle 1: htb default 1",
        f"tc class replace dev {intf} parent 1: classid 1:1 htb rate {rate} ceil {rate}",
        f"tc qdisc replace dev {intf} parent 1:1 handle 10: fq_codel",
    ]


def _weight(distance_m: float, model: RadioModel) -> float:
    span = model.cochannel_zero_m - model.cochannel_full_m
    return min(1.0, max(0.0, (model.cochannel_zero_m - distance_m) / span))


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)
