"""Traffic profiles (P1.5): load testbed/traffic/profiles.yaml and build the tool commands.

Pure Python (no Mininet import), unit-tested on the Mac and run on the VM (Python 3.8, ADR-003).
Profile names are common/schemas.py AppClass. All traffic is downlink (srv1 -> station): video
and bulk are iperf3 reverse-mode clients on the station, web is curl fetching from srv1.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Union

import yaml

APP_CLASSES = ("video", "web", "bulk")  # = common/schemas.py AppClass
DEFAULT_CONFIG = Path(__file__).resolve().parent / "profiles.yaml"
_PORT_MIN, _PORT_MAX = 1024, 65535
_PROTOCOLS = ("udp", "tcp")
_IPERF_KEYS = {"protocol", "rate_mbps"}
_WEB_KEYS = {"object_kb", "think_mean_s", "timeout_s"}
CURL_FORMAT = "CURL %{http_code} %{size_download} %{time_total}\\n"  # parse.parse_curl


@dataclass(frozen=True)
class IperfProfile:
    """An iperf3 stream: UDP needs a rate; TCP rate None means unlimited."""

    name: str
    protocol: str
    rate_mbps: float | None


@dataclass(frozen=True)
class WebProfile:
    """Repeated HTTP fetches of one object with exponential think time between them."""

    name: str
    object_kb: int
    think_mean_s: float
    timeout_s: float


Profile = Union[IperfProfile, WebProfile]  # Union: evaluated at runtime on Python 3.8


@dataclass(frozen=True)
class TrafficConfig:
    """Validated traffic profiles and KPI probe settings."""

    window_s: float
    ping_interval_s: float
    ping_timeout_s: float
    iperf_base_port: int
    http_port: int
    profiles: dict[str, Profile]


def load_traffic_config(raw: Mapping[str, Any]) -> TrafficConfig:
    """Validate a parsed profiles.yaml; raise ValueError naming the bad field."""
    ping, server, profiles = raw.get("ping", {}), raw.get("server", {}), raw.get("profiles", {})
    if set(profiles) != set(APP_CLASSES):
        raise ValueError(f"profiles must be exactly {APP_CLASSES}, got {sorted(profiles)}")
    return TrafficConfig(
        window_s=_positive(raw, "window_s", "window_s"),
        ping_interval_s=_positive(ping, "interval_s", "ping.interval_s"),
        ping_timeout_s=_positive(ping, "timeout_s", "ping.timeout_s"),
        iperf_base_port=_port(server, "iperf_base_port"),
        http_port=_port(server, "http_port"),
        profiles={
            "video": _iperf_profile("video", profiles["video"]),
            "bulk": _iperf_profile("bulk", profiles["bulk"]),
            "web": _web_profile(profiles["web"]),
        },
    )


def load_traffic_config_file(path: Path = DEFAULT_CONFIG) -> TrafficConfig:
    """Load and validate a profiles YAML file."""
    return load_traffic_config(yaml.safe_load(path.read_text()))


def flow_id(sta: str, app_class: str) -> str:
    """Flow ID used in KPI records: one flow per station and class."""
    return f"{sta}-{app_class}"


def iperf_server_command(port: int) -> list[str]:
    """iperf3 server on srv1 (serves one test at a time, so one per iperf3 flow)."""
    return ["iperf3", "-s", "-p", str(port)]


def iperf_client_command(
    profile: IperfProfile,
    server_ip: str,
    port: int,
    duration_s: int,
    rate_mbps: float | None = None,
) -> list[str]:
    """iperf3 client on the station in reverse mode (srv1 sends), one flushed line per second.

    `rate_mbps` (a scenario's TrafficItem.rate_mbps) overrides the profile's rate.
    """
    command = ["iperf3", "-c", server_ip, "-p", str(port), "-R", "-i", "1", "--forceflush"]
    command += ["-t", str(duration_s)]
    if profile.protocol == "udp":
        command.append("-u")
    rate = rate_mbps if rate_mbps is not None else profile.rate_mbps
    if rate is not None:
        command += ["-b", f"{rate:g}M"]
    return command


def web_object_name(profile: WebProfile) -> str:
    """File the HTTP server on srv1 serves for the web profile."""
    return f"object_{profile.object_kb}kb.bin"


def http_server_command(directory: str, bind_ip: str, port: int) -> list[str]:
    """Static HTTP server on srv1 for the web profile, bound to srv1's own address."""
    return [
        "python3", "-m", "http.server", str(port), "--bind", bind_ip, "--directory", directory,
    ]  # fmt: skip


def web_fetch_command(profile: WebProfile, server_ip: str, port: int) -> list[str]:
    """One web fetch from the station: prints one CURL_FORMAT line, gives up after timeout_s."""
    url = f"http://{server_ip}:{port}/{web_object_name(profile)}"
    timeout = f"{profile.timeout_s:g}"
    return ["curl", "-s", "-o", "/dev/null", "--max-time", timeout, "-w", CURL_FORMAT, url]


def ping_command(config: TrafficConfig, server_ip: str) -> list[str]:
    """Latency probe from a station; -O prints a line for every unanswered ping (parse.py)."""
    return ["ping", "-n", "-O", "-i", f"{config.ping_interval_s:g}", server_ip]


def _iperf_profile(name: str, raw: Mapping[str, Any]) -> IperfProfile:
    where = f"profiles.{name}"
    _known_keys(raw, _IPERF_KEYS, where)
    protocol = raw.get("protocol")
    if protocol not in _PROTOCOLS:
        raise ValueError(f"{where}.protocol must be one of {_PROTOCOLS}, got {protocol!r}")
    rate = raw.get("rate_mbps")
    if rate is None and protocol == "udp":
        raise ValueError(f"{where}.rate_mbps is required for udp")
    rate_mbps = None if rate is None else _positive(raw, "rate_mbps", f"{where}.rate_mbps")
    return IperfProfile(name, protocol, rate_mbps)


def _web_profile(raw: Mapping[str, Any]) -> WebProfile:
    _known_keys(raw, _WEB_KEYS, "profiles.web")
    object_kb: Any = raw.get("object_kb")
    if not (_is_int(object_kb) and object_kb > 0):
        raise ValueError(f"profiles.web.object_kb must be an integer > 0, got {object_kb!r}")
    return WebProfile(
        "web",
        object_kb,
        _positive(raw, "think_mean_s", "profiles.web.think_mean_s"),
        _positive(raw, "timeout_s", "profiles.web.timeout_s"),
    )


def _known_keys(raw: Mapping[str, Any], allowed: set[str], where: str) -> None:
    unknown = set(raw) - allowed
    if unknown:
        raise ValueError(f"{where}: unknown keys {sorted(unknown)}")


def _positive(raw: Mapping[str, Any], key: str, where: str) -> float:
    value: Any = raw.get(key)
    if not _is_number(value) or value <= 0:
        raise ValueError(f"{where} must be a number > 0, got {value!r}")
    return float(value)


def _port(raw: Mapping[str, Any], key: str) -> int:
    value: Any = raw.get(key)
    if not (_is_int(value) and _PORT_MIN <= value <= _PORT_MAX):
        raise ValueError(f"server.{key} must be an integer port {_PORT_MIN}-{_PORT_MAX}")
    return int(value)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)
