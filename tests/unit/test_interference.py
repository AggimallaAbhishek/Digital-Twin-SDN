"""P1.6 co-channel interference model (testbed/interference.py)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from testbed.interference import (
    ApRadio,
    RadioModel,
    capacity_caps,
    load_radio_model,
    tc_commands,
)

CAMPUS = yaml.safe_load(
    (Path(__file__).resolve().parents[2] / "config" / "campus_v1.yaml").read_text()
)
MODEL = RadioModel(
    ap_capacity_mbps=4.6, cochannel_full_m=30, cochannel_zero_m=60, orphan_rejoin_s=5
)
# campus_v1: ap1 (20,50) ch1, ap2 (60,50) ch6, ap3 (20,20) ch11, ap4 (60,20) ch1
CAMPUS_APS = [
    ApRadio("ap1", (20, 50), 1),
    ApRadio("ap2", (60, 50), 6),
    ApRadio("ap3", (20, 20), 11),
    ApRadio("ap4", (60, 20), 1),
]


def test_campus_config_has_the_radio_model() -> None:
    assert load_radio_model(CAMPUS) == MODEL


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"ap_capacity_mbps": 0}, "ap_capacity_mbps"),
        ({"cochannel_full_m": -1}, "cochannel_full_m"),
        ({"cochannel_zero_m": 30}, "cochannel_zero_m"),  # must be beyond full_m
        ({"orphan_rejoin_s": "soon"}, "orphan_rejoin_s"),
        ({"extra": 1}, "unknown"),
    ],
)
def test_bad_radio_model_is_rejected(change: dict[str, Any], message: str) -> None:
    raw = {"radio_model": {**CAMPUS["radio_model"], **change}}
    with pytest.raises(ValueError, match=message):
        load_radio_model(raw)


def test_missing_radio_model_is_rejected() -> None:
    with pytest.raises(ValueError, match="radio_model"):
        load_radio_model({})


def test_default_campus_caps_only_the_diagonal_channel_1_pair() -> None:
    # ap1-ap4 are 50 m apart: weight (60 - 50) / (60 - 30) = 1/3 -> 4.6 / (4/3) = 3.45
    assert capacity_caps(CAMPUS_APS, MODEL) == {
        "ap1": 3.45,
        "ap2": None,
        "ap3": None,
        "ap4": 3.45,
    }


def test_forcing_ap3_onto_channel_1_caps_three_aps() -> None:
    aps = [*CAMPUS_APS[:2], ApRadio("ap3", (20, 20), 1), CAMPUS_APS[3]]
    # ap1: ap3 at 30 m (1) + ap4 (1/3); ap3: ap1 (1) + ap4 at 40 m (2/3); ap4: 1/3 + 2/3
    assert capacity_caps(aps, MODEL) == {
        "ap1": round(4.6 / (1 + 1 + 1 / 3), 2),
        "ap2": None,
        "ap3": round(4.6 / (1 + 1 + 2 / 3), 2),
        "ap4": round(4.6 / (1 + 1 / 3 + 2 / 3), 2),
    }


def test_down_aps_neither_interfere_nor_get_a_cap() -> None:
    aps = [ApRadio("ap1", (20, 50), 1), ApRadio("ap4", (60, 20), 1, up=False)]
    assert capacity_caps(aps, MODEL) == {"ap1": None, "ap4": None}


def test_aps_far_apart_do_not_interfere() -> None:
    aps = [ApRadio("ap1", (0, 0), 1), ApRadio("ap9", (60, 0), 1)]
    assert capacity_caps(aps, MODEL) == {"ap1": None, "ap9": None}


def test_cap_installs_htb_with_fair_queueing() -> None:
    assert tc_commands("ap1-wlan1", 3.45) == [
        "tc qdisc replace dev ap1-wlan1 root handle 1: htb default 1",
        "tc class replace dev ap1-wlan1 parent 1: classid 1:1 htb rate 3.45mbit ceil 3.45mbit",
        "tc qdisc replace dev ap1-wlan1 parent 1:1 handle 10: fq_codel",
    ]


def test_no_cap_restores_the_default_qdisc() -> None:
    assert tc_commands("ap1-wlan1", None) == ["tc qdisc del dev ap1-wlan1 root"]
