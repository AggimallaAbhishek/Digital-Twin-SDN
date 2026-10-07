"""P1.5 traffic profiles and probe settings (testbed/traffic/profiles.py)."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
import yaml

from testbed.traffic.profiles import (
    CURL_FORMAT,
    IperfProfile,
    WebProfile,
    flow_id,
    http_server_command,
    iperf_client_command,
    iperf_server_command,
    load_traffic_config,
    load_traffic_config_file,
    ping_command,
    web_fetch_command,
)

CONFIG_PATH = Path(__file__).resolve().parents[2] / "testbed" / "traffic" / "profiles.yaml"
RAW: dict[str, Any] = yaml.safe_load(CONFIG_PATH.read_text())


def test_shipped_config_loads() -> None:
    config = load_traffic_config_file(CONFIG_PATH)
    assert config.window_s == 1.0
    assert (config.ping_interval_s, config.ping_timeout_s) == (0.2, 1.0)
    assert (config.iperf_base_port, config.http_port) == (5201, 8000)
    assert config.profiles == {
        "video": IperfProfile("video", "udp", 1.0),  # deviation #7: was 3 Mbit/s
        "bulk": IperfProfile("bulk", "tcp", None),
        "web": WebProfile("web", 50, 5.0, 10.0),  # deviation #7: was 500 KB / 2 s
    }


_DELETE = object()


def _with(path: tuple[str, ...], value: Any) -> dict[str, Any]:
    raw = copy.deepcopy(RAW)
    node = raw
    for key in path[:-1]:
        node = node[key]
    if value is _DELETE:
        del node[path[-1]]
    else:
        node[path[-1]] = value
    return raw


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (("window_s",), 0, "window_s"),
        (("window_s",), "1s", "window_s"),
        (("ping", "interval_s"), -0.2, "ping.interval_s"),
        (("ping", "timeout_s"), _DELETE, "ping.timeout_s"),
        (("server", "http_port"), 80, "server.http_port"),
        (("server", "iperf_base_port"), 70000, "server.iperf_base_port"),
        (("server", "iperf_base_port"), 5201.5, "server.iperf_base_port"),
        (("profiles", "voip"), {"protocol": "udp", "rate_mbps": 0.1}, "voip"),
        (("profiles", "bulk"), _DELETE, "bulk"),
        (("profiles", "video", "protocol"), "sctp", "profiles.video.protocol"),
        (("profiles", "video", "rate_mbps"), None, "profiles.video.rate_mbps"),
        (("profiles", "bulk", "rate_mbps"), 0, "profiles.bulk.rate_mbps"),
        (("profiles", "bulk", "burst"), True, "profiles.bulk"),
        (("profiles", "web", "object_kb"), 0, "profiles.web.object_kb"),
        (("profiles", "web", "object_kb"), 2.5, "profiles.web.object_kb"),
        (("profiles", "web", "think_mean_s"), True, "profiles.web.think_mean_s"),
        (("profiles", "web", "timeout_s"), _DELETE, "profiles.web.timeout_s"),
        (("profiles", "web", "protocol"), "tcp", "profiles.web"),
    ],
)
def test_bad_config_is_rejected_naming_the_field(
    path: tuple[str, ...], value: Any, message: str
) -> None:
    with pytest.raises(ValueError, match=message.replace(".", r"\.")):
        load_traffic_config(_with(path, value))


CONFIG = load_traffic_config(RAW)
VIDEO, BULK, WEB = (CONFIG.profiles[name] for name in ("video", "bulk", "web"))
SRV = "10.0.1.1"


def test_flow_id_names_station_and_class() -> None:
    assert flow_id("sta5", "video") == "sta5-video"


def test_iperf_server_listens_on_its_port() -> None:
    assert iperf_server_command(5203) == ["iperf3", "-s", "-p", "5203"]


def test_video_client_is_reverse_udp_at_the_profile_rate() -> None:
    assert isinstance(VIDEO, IperfProfile)
    assert iperf_client_command(VIDEO, SRV, 5201, duration_s=600) == [
        "iperf3", "-c", SRV, "-p", "5201", "-R", "-i", "1", "--forceflush", "-t", "600",
        "-u", "-b", "1M",
    ]  # fmt: skip


def test_scenario_rate_overrides_the_profile_rate() -> None:
    assert isinstance(VIDEO, IperfProfile)
    command = iperf_client_command(VIDEO, SRV, 5201, duration_s=600, rate_mbps=1.5)
    assert command[-2:] == ["-b", "1.5M"]


def test_bulk_client_is_unlimited_reverse_tcp() -> None:
    assert isinstance(BULK, IperfProfile)
    command = iperf_client_command(BULK, SRV, 5202, duration_s=600)
    assert command[-2:] == ["-t", "600"]
    assert "-u" not in command
    assert "-b" not in command


def test_capped_bulk_client_gets_a_rate() -> None:
    assert isinstance(BULK, IperfProfile)
    command = iperf_client_command(BULK, SRV, 5202, duration_s=600, rate_mbps=10)
    assert command[-2:] == ["-b", "10M"]


def test_http_server_serves_a_directory() -> None:
    assert http_server_command("/home/u/p02/www", SRV, 8000) == [
        "python3", "-m", "http.server", "8000", "--bind", SRV,
        "--directory", "/home/u/p02/www",
    ]  # fmt: skip


def test_web_fetch_prints_one_result_line_and_times_out() -> None:
    assert isinstance(WEB, WebProfile)
    assert web_fetch_command(WEB, SRV, 8000) == [
        "curl", "-s", "-o", "/dev/null", "--max-time", "10", "-w", CURL_FORMAT,
        "http://10.0.1.1:8000/object_50kb.bin",
    ]  # fmt: skip
    assert CURL_FORMAT == "CURL %{http_code} %{size_download} %{time_total}\\n"


def test_ping_reports_unanswered_pings() -> None:
    assert ping_command(CONFIG, SRV) == ["ping", "-n", "-O", "-i", "0.2", SRV]
