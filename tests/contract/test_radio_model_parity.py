"""The twin (twin/radio.py) and the testbed emulation (testbed/interference.py) must agree on the
co-channel caps (deviation #7): the twin predicts what the testbed actually does."""

import itertools
import math
from pathlib import Path

import pytest
import yaml

from testbed.interference import ApRadio, capacity_caps, load_radio_model
from testbed.layout import load_layout
from twin.radio import cochannel_load, load_radio_params

CAMPUS_PATH = Path(__file__).resolve().parents[2] / "config" / "campus_v1.yaml"
CAMPUS = yaml.safe_load(CAMPUS_PATH.read_text())
LAYOUT = load_layout(CAMPUS_PATH)
TESTBED = load_radio_model(CAMPUS)
TWIN = load_radio_params(CAMPUS)
CHANNELS = (1, 6, 11)


def _twin_caps(radios: list[ApRadio]) -> dict[str, float | None]:
    caps: dict[str, float | None] = {}
    for ap in radios:
        others = [
            math.dist(ap.position, o.position)
            for o in radios
            if o is not ap and o.up and o.channel == ap.channel
        ]
        load = cochannel_load(others, TWIN)
        caps[ap.name] = round(TWIN.ap_capacity_mbps / (1 + load), 2) if ap.up and load else None
    return caps


def test_both_read_the_same_numbers() -> None:
    assert (TWIN.ap_capacity_mbps, TWIN.cochannel_full_m, TWIN.cochannel_zero_m) == (
        TESTBED.ap_capacity_mbps,
        TESTBED.cochannel_full_m,
        TESTBED.cochannel_zero_m,
    )


@pytest.mark.parametrize("down", [(), ("ap2",), ("ap1", "ap4")], ids=str)
def test_caps_agree_for_every_channel_plan(down: tuple[str, ...]) -> None:
    for channels in itertools.product(CHANNELS, repeat=len(LAYOUT.aps)):
        radios = [
            ApRadio(ap.name, ap.position, ch, up=ap.name not in down)
            for ap, ch in zip(LAYOUT.aps, channels, strict=True)
        ]
        assert _twin_caps(radios) == capacity_caps(radios, TESTBED), channels
