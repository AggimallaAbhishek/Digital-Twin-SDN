"""Twin radio model: predicted client signal and co-channel interference load.

The same model the testbed emulates (testbed/interference.py, deviation #7), re-stated here because
the twin may not import the testbed (RULEBOOK §4); tests/contract/test_radio_model_parity.py fails
if the two drift apart. Parameters come from config/campus_v1.yaml (`radio_model`, `propagation`).

    predicted RSSI = rssi_at_1m_dbm - 10 * path_loss_exp * log10(max(d, 1 m))   (log-distance)
    co-channel load = sum over same-channel APs that are up of w(d),
        w(d) = 1 for d <= cochannel_full_m, 0 for d >= cochannel_zero_m, linear in between
    AP capacity under interference = ap_capacity_mbps / (1 + load)
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

MIN_DISTANCE_M = 1.0  # the log-distance model is defined from 1 m


@dataclass(frozen=True)
class RadioParams:
    """Radio model parameters (config/campus_v1.yaml)."""

    ap_capacity_mbps: float
    cochannel_full_m: float
    cochannel_zero_m: float
    rssi_at_1m_dbm: float
    path_loss_exp: float


def load_radio_params(campus: Mapping[str, Any]) -> RadioParams:
    """Read the radio model from a parsed campus YAML; ValueError if a section is missing."""
    radio, propagation = campus.get("radio_model"), campus.get("propagation")
    if not isinstance(radio, Mapping) or not isinstance(propagation, Mapping):
        raise ValueError("campus config needs radio_model and propagation sections")
    return RadioParams(
        ap_capacity_mbps=float(radio["ap_capacity_mbps"]),
        cochannel_full_m=float(radio["cochannel_full_m"]),
        cochannel_zero_m=float(radio["cochannel_zero_m"]),
        rssi_at_1m_dbm=float(propagation["rssi_at_1m_dbm"]),
        path_loss_exp=float(propagation["exp"]),
    )


def predicted_rssi_dbm(
    ap: tuple[float, float], station: tuple[float, float], params: RadioParams
) -> float:
    """Signal a station at `station` would get from an AP at `ap` (dBm)."""
    distance = max(MIN_DISTANCE_M, math.dist(ap, station))
    return params.rssi_at_1m_dbm - 10 * params.path_loss_exp * math.log10(distance)


def cochannel_load(neighbour_distances_m: Iterable[float], params: RadioParams) -> float:
    """Interference load from same-channel APs (that are up) at these distances."""
    span = params.cochannel_zero_m - params.cochannel_full_m
    return sum(
        min(1.0, max(0.0, (params.cochannel_zero_m - d) / span)) for d in neighbour_distances_m
    )
