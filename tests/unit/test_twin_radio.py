"""Twin radio model (twin/radio.py): predicted signal and co-channel interference."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from twin.radio import (
    RadioParams,
    capped_capacity_mbps,
    cochannel_load,
    load_radio_params,
    predicted_rssi_dbm,
)

CAMPUS: dict[str, Any] = yaml.safe_load(
    (Path(__file__).resolve().parents[2] / "config" / "campus_v1.yaml").read_text()
)
PARAMS = RadioParams(
    ap_capacity_mbps=4.6,
    cochannel_full_m=30.0,
    cochannel_zero_m=60.0,
    rssi_at_1m_dbm=-16.0,
    path_loss_exp=4.0,
)


def test_params_come_from_the_campus_config() -> None:
    assert load_radio_params(CAMPUS) == PARAMS


@pytest.mark.parametrize("capacity", [0, -4.6])
def test_an_ap_capacity_that_is_not_positive_is_an_error(capacity: float) -> None:
    campus = {**CAMPUS, "radio_model": {**CAMPUS["radio_model"], "ap_capacity_mbps": capacity}}
    with pytest.raises(ValueError, match="ap_capacity_mbps"):
        load_radio_params(campus)


def test_missing_section_is_an_error() -> None:
    with pytest.raises(ValueError, match="radio_model"):
        load_radio_params({"propagation": CAMPUS["propagation"]})


@pytest.mark.parametrize(
    ("distance_m", "measured_dbm"),
    [(10.0, -56.0), (15.0, -63.0), (20.0, -67.0)],  # P1.6 calibration (iw signal)
)
def test_prediction_matches_the_measured_signal(distance_m: float, measured_dbm: float) -> None:
    rssi = predicted_rssi_dbm((0.0, 0.0), (distance_m, 0.0), PARAMS)
    assert rssi == pytest.approx(measured_dbm, abs=1.5)


def test_steering_bound_is_reached_at_about_30_m() -> None:
    assert predicted_rssi_dbm((0, 0), (30, 0), PARAMS) == pytest.approx(-75.1, abs=0.1)


def test_a_station_on_top_of_the_ap_is_capped_at_1_m() -> None:
    assert predicted_rssi_dbm((5, 5), (5, 5), PARAMS) == -16.0


@pytest.mark.parametrize(
    ("distance_m", "weight"), [(10.0, 1.0), (30.0, 1.0), (45.0, 0.5), (60.0, 0.0), (80.0, 0.0)]
)
def test_cochannel_neighbour_weight_falls_off_linearly(distance_m: float, weight: float) -> None:
    assert cochannel_load([distance_m], PARAMS) == pytest.approx(weight)


def test_cochannel_load_adds_neighbours() -> None:
    assert cochannel_load([30.0, 50.0], PARAMS) == pytest.approx(1 + 1 / 3)


@pytest.mark.parametrize(("load", "cap"), [(0.0, None), (1 / 3, 3.45), (1.0, 2.3)])
def test_capacity_under_interference(load: float, cap: float | None) -> None:
    assert capped_capacity_mbps(load, PARAMS) == cap
