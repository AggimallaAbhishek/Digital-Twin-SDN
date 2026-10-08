"""P1.3 AP agent logic (testbed/ap_logic.py): request validation, iw parsing, airtime."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from common import schemas
from testbed import ap_logic
from testbed.ap_logic import (
    IwInfo,
    Link,
    StationEntry,
    byte_counters,
    capacity_util,
    chan_switch_cmd,
    check_flow_id,
    parse_admin_request,
    parse_associate_request,
    parse_channel_request,
    parse_iw_info,
    parse_limit_request,
    parse_link,
    parse_queue_request,
    parse_station_dump,
    parse_txpower_request,
    snr_db,
)

IW = Path(__file__).resolve().parents[1] / "fixtures" / "iw"


def _iw(name: str) -> str:
    return (IW / name).read_text()


def test_bounds_match_the_frozen_schemas() -> None:
    # testbed runs on the VM's Python 3.8 without pydantic, so it keeps a copy of the bounds
    assert ap_logic.CHANNELS == schemas.CHANNELS_24GHZ
    assert (ap_logic.TX_POWER_DBM_MIN, ap_logic.TX_POWER_DBM_MAX) == (
        schemas.TX_POWER_DBM_MIN,
        schemas.TX_POWER_DBM_MAX,
    )


@pytest.mark.parametrize("channel", [1, 6, 11])
def test_channel_request_accepts_non_overlapping_channels(channel: int) -> None:
    assert parse_channel_request({"channel": channel}) == channel


@pytest.mark.parametrize(
    "body",
    [
        {"channel": 3},
        {"channel": 6.0},
        {"channel": "6"},
        {"channel": True},
        {},
        {"channel": 6, "extra": 1},
        [6],
        None,
    ],
    ids=["off-plan", "float", "string", "bool", "missing", "extra-key", "list", "null"],
)
def test_channel_request_rejects_bad_bodies(body: Any) -> None:
    with pytest.raises(ValueError, match="channel"):
        parse_channel_request(body)


@pytest.mark.parametrize(("dbm", "applied"), [(5, 5), (12, 12), (12.4, 12), (12.6, 13), (20, 20)])
def test_txpower_request_rounds_to_whole_dbm(dbm: float, applied: int) -> None:
    assert parse_txpower_request({"dbm": dbm}) == applied


@pytest.mark.parametrize(
    "body",
    [{"dbm": 4.9}, {"dbm": 20.1}, {"dbm": "12"}, {"dbm": False}, {}, {"dbm": 12, "x": 1}],
    ids=["below-min", "above-max", "string", "bool", "missing", "extra-key"],
)
def test_txpower_request_rejects_bad_bodies(body: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="dbm"):
        parse_txpower_request(body)


def test_associate_request_returns_target_ap() -> None:
    assert parse_associate_request({"ap": "ap2"}) == "ap2"


@pytest.mark.parametrize(
    "body",
    [{"ap": "AP2"}, {"ap": "s1"}, {"ap": 2}, {}, {"ap": "ap2", "x": 1}],
    ids=["uppercase", "not-an-ap", "int", "missing", "extra-key"],
)
def test_associate_request_rejects_bad_bodies(body: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="ap"):
        parse_associate_request(body)


def test_iw_info_gives_channel_txpower_and_bssid() -> None:
    assert parse_iw_info(_iw("ap_info.txt")) == IwInfo(
        bssid="02:00:00:00:14:00", channel=1, tx_power_dbm=14.0
    )


def test_iw_info_without_channel_or_txpower_gives_none() -> None:
    assert parse_iw_info("Interface ap1-wlan1\n\taddr 02:00:00:00:14:00\n") == IwInfo(
        bssid="02:00:00:00:14:00", channel=None, tx_power_dbm=None
    )


def test_station_dump_lists_every_client() -> None:
    entries = parse_station_dump(_iw("ap_station_dump.txt"))

    assert [e.mac for e in entries] == [
        "02:00:00:00:00:00",
        "02:00:00:00:01:00",
        "02:00:00:00:02:00",
    ]
    assert entries[2] == StationEntry(
        mac="02:00:00:00:02:00",
        signal_dbm=-37.0,
        tx_retries=0,
        rx_bytes=1242,
        tx_bytes=175,
        tx_bitrate_mbps=1.0,
        rx_bitrate_mbps=54.0,
    )


def test_station_dump_of_an_ap_without_clients_is_empty() -> None:
    assert parse_station_dump("") == []


def test_station_entry_missing_optional_fields_uses_none_and_zero() -> None:
    (entry,) = parse_station_dump("Station 02:00:00:00:09:00 (on ap1-wlan1)\n\tauthorized:\tyes\n")
    assert entry == StationEntry("02:00:00:00:09:00", None, 0, 0, 0, None, None)


def test_link_of_a_connected_station() -> None:
    assert parse_link(_iw("sta_link.txt")) == Link(
        bssid="02:00:00:00:14:00", signal_dbm=-56.0, tx_bitrate_mbps=12.0
    )


def test_link_of_a_disconnected_station() -> None:
    assert parse_link(_iw("sta_link_not_connected.txt")) == Link(None, None, None)


def test_snr_uses_the_hwsim_noise_floor() -> None:
    assert snr_db(-56.0) == 36.0
    assert snr_db(None) is None


@pytest.mark.parametrize(("channel", "freq"), [(1, 2412), (6, 2437), (11, 2462)])
def test_chan_switch_command_uses_the_channel_frequency(channel: int, freq: int) -> None:
    assert chan_switch_cmd("ap1-wlan1", channel) == f"hostapd_cli -i ap1-wlan1 chan_switch 5 {freq}"


def _client(
    mac: str, rx: int, tx: int, tx_rate: float | None, rx_rate: float | None
) -> StationEntry:
    return StationEntry(mac, -50.0, 0, rx, tx, tx_rate, rx_rate)


A, B = "02:00:00:00:00:00", "02:00:00:00:01:00"


# channel_util = (bits the AP sent + received) / its current capacity (deviation #8): the emulated
# AP carries ~4.6 Mbit/s whatever bitrate iw reports, and co-channel caps lower that.
def test_utilisation_is_traffic_over_capacity() -> None:
    before = [_client(A, rx=0, tx=0, tx_rate=54.0, rx_rate=12.0)]
    # 2 Mbit down + 0.3 Mbit up in 1 s on a 4.6 Mbit/s AP
    after = [_client(A, rx=37_500, tx=250_000, tx_rate=54.0, rx_rate=12.0)]
    assert capacity_util(
        byte_counters(before), after, dt_s=1.0, capacity_mbps=4.6
    ) == pytest.approx(0.5)


def test_a_lower_cap_means_higher_utilisation_for_the_same_traffic() -> None:
    before = [_client(A, 0, 0, 54.0, 54.0)]
    after = [_client(A, 0, 250_000, 54.0, 54.0)]  # 2 Mbit in 1 s
    nominal = capacity_util(byte_counters(before), after, dt_s=1.0, capacity_mbps=4.0)
    capped = capacity_util(byte_counters(before), after, dt_s=1.0, capacity_mbps=2.5)
    assert nominal == pytest.approx(0.5)
    assert capped == pytest.approx(0.8)


def test_reported_bitrate_does_not_matter() -> None:
    before = [_client(A, 0, 0, None, None)]
    after = [_client(A, 0, 125_000, None, None)]  # 1 Mbit in 1 s, no bitrate reported
    assert capacity_util(byte_counters(before), after, dt_s=1.0, capacity_mbps=4.0) == 0.25


def test_utilisation_is_capped_at_one() -> None:
    before = [_client(A, 0, 0, 1.0, 1.0)]
    after = [_client(A, 0, 1_250_000, 1.0, 1.0)]  # 10 Mbit in 1 s on a 4.6 Mbit/s AP
    assert capacity_util(byte_counters(before), after, dt_s=1.0, capacity_mbps=4.6) == 1.0


def test_utilisation_adds_clients_and_skips_new_or_reset_ones() -> None:
    before = [_client(A, 0, 0, 10.0, 10.0), _client(B, 0, 500_000, 10.0, 10.0)]
    after = [
        _client(A, 0, 125_000, 10.0, 10.0),  # 1 Mbit
        _client(B, 0, 100, 10.0, 10.0),  # counter went backwards (re-associated): ignored
        _client("02:00:00:00:02:00", 0, 9_999_999, 1.0, 1.0),  # new client: no baseline yet
    ]
    assert capacity_util(byte_counters(before), after, dt_s=1.0, capacity_mbps=4.0) == 0.25


@pytest.mark.parametrize("dt_s", [0.0, -1.0])
def test_utilisation_without_elapsed_time_is_zero(dt_s: float) -> None:
    entries = [_client(A, 0, 1_000, 1.0, 1.0)]
    assert capacity_util(byte_counters(entries), entries, dt_s=dt_s, capacity_mbps=4.6) == 0.0


def test_utilisation_without_a_previous_sample_is_zero() -> None:
    entries = [_client(A, 0, 1_000, 1.0, 1.0)]
    assert capacity_util(None, entries, dt_s=1.0, capacity_mbps=4.6) == 0.0


def test_capacity_must_be_positive() -> None:
    with pytest.raises(ValueError, match="capacity"):
        capacity_util(None, [], dt_s=1.0, capacity_mbps=0.0)


def test_queue_request_returns_the_queue() -> None:
    assert parse_queue_request({"queue_id": 1}) == 1


@pytest.mark.parametrize("body", [{"queue_id": 3}, {"queue_id": True}, {"queue_id": "1"}, {}])
def test_bad_queue_requests_are_refused(body: Any) -> None:
    with pytest.raises(ValueError, match="queue_id"):
        parse_queue_request(body)


@pytest.mark.parametrize(("body", "limit"), [({"max_mbps": 2}, 2.0), ({"max_mbps": None}, None)])
def test_limit_request_returns_the_limit_or_none(body: Any, limit: float | None) -> None:
    assert parse_limit_request(body) == limit


@pytest.mark.parametrize("body", [{"max_mbps": 0.5}, {"max_mbps": "2"}, {"max_mbps": True}])
def test_bad_limit_requests_are_refused(body: Any) -> None:
    with pytest.raises(ValueError, match="max_mbps"):
        parse_limit_request(body)


@pytest.mark.parametrize("state", ["up", "down"])
def test_admin_request_returns_the_state(state: str) -> None:
    assert parse_admin_request({"state": state}) == state


def test_bad_admin_request_is_refused() -> None:
    with pytest.raises(ValueError, match="state"):
        parse_admin_request({"state": "off"})


@pytest.mark.parametrize("flow_id", ["sta1-video", "sta20-bulk", "sta3-web"])
def test_known_flow_ids_are_accepted(flow_id: str) -> None:
    assert check_flow_id(flow_id) == flow_id


@pytest.mark.parametrize("flow_id", ["sta1-voip", "ap1-video", "sta1video", "sta1-video;rm"])
def test_other_flow_ids_are_refused(flow_id: str) -> None:
    with pytest.raises(ValueError, match="flow"):
        check_flow_id(flow_id)
