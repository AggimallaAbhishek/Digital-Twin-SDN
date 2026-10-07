"""Pure logic for the Ryu twin controller (P1.2): request validation, cookies, rates.

No Ryu import, so it is unit-tested on the Mac. It runs inside the Ryu venv on the VM, so it must
stay Python 3.8-compatible (ADR-002). REST bodies are validated here before anything reaches a
switch (RULEBOOK C-2, N-5).
"""

from __future__ import annotations

import hashlib
import ipaddress
import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Tuple, Union

OURS_TAG = 1 << 62  # cookies we install carry this bit; learned L2 flows use cookie 0
COOKIE_BITS = 62
DEFAULT_PRIORITY = 100
QOS_PRIORITY = 150
MAX_PRIORITY = 65535
QUEUE_IDS = (0, 1, 2)  # must match common/schemas.py QOS_QUEUE_IDS
SPECIAL_PORTS = ("normal", "controller")
ETH_TYPE_IPV4 = 0x0800
MAX_IP_PROTO = 255

_FLOW_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
_MAC = re.compile(r"^([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$")
_FLOW_KEYS = {"flow_id", "dpid", "priority", "match", "actions", "idle_timeout", "hard_timeout"}
_QOS_KEYS = {"flow_id", "dpid", "match", "queue_id", "out_port"}

Action = Tuple[str, Union[int, str]]  # runtime alias: typing.Tuple for Python 3.8


@dataclass(frozen=True)
class FlowSpec:
    """A validated flow to install on one datapath."""

    flow_id: str
    dpid: int
    priority: int
    match: dict[str, Any]
    actions: list[Action]
    idle_timeout: int = 0
    hard_timeout: int = 0
    cookie: int = field(default=0)


def dpid_str(dpid: int) -> str:
    """Datapath id as 16 lowercase hex digits (the form used in telemetry)."""
    return f"{dpid:016x}"


def flow_cookie(flow_id: str) -> int:
    """Stable 64-bit OpenFlow cookie for one of our flows (tagged so it never equals 0)."""
    digest = int(hashlib.sha256(flow_id.encode()).hexdigest(), 16)
    return OURS_TAG | (digest & ((1 << COOKIE_BITS) - 1))


def is_ours(cookie: int) -> bool:
    """True if the cookie belongs to a flow installed through our REST API."""
    return bool(cookie & OURS_TAG)


def learn_mac(tables: dict[int, dict[str, int]], dpid: int, mac: str, port: int) -> bool:
    """Record that `mac` was seen on `port` of `dpid`; return True if the host moved.

    A move (station steered or roamed to another AP) means the MAC turned up on a different port
    than learned. Its location is then forgotten on every datapath, and the caller must delete
    the learned flows to and from it, or they keep forwarding to the old AP (P1.3 bug).
    """
    table = tables.setdefault(dpid, {})
    moved = mac in table and table[mac] != port
    if moved:
        for other in tables.values():
            other.pop(mac, None)
    table[mac] = port
    return moved


def rate_bps(prev: tuple[int, float] | None, now: tuple[int, float]) -> float:
    """Bits per second between two (byte_counter, timestamp) samples; 0 if not computable."""
    if prev is None:
        return 0.0
    (b0, t0), (b1, t1) = prev, now
    if t1 <= t0 or b1 < b0:
        return 0.0
    return 8.0 * (b1 - b0) / (t1 - t0)


def parse_flow_request(body: Mapping[str, Any]) -> FlowSpec:
    """Validate a POST /flows body and return a FlowSpec; raise ValueError on any problem."""
    _check_keys(body, _FLOW_KEYS, required={"flow_id", "dpid", "match", "actions"})
    flow_id = _flow_id(body["flow_id"])
    actions = _actions(body["actions"])
    return FlowSpec(
        flow_id=flow_id,
        dpid=_dpid(body["dpid"]),
        priority=_int_in(body.get("priority", DEFAULT_PRIORITY), "priority", 1, MAX_PRIORITY),
        match=_match(body["match"]),
        actions=actions,
        idle_timeout=_int_in(body.get("idle_timeout", 0), "idle_timeout", 0, MAX_PRIORITY),
        hard_timeout=_int_in(body.get("hard_timeout", 0), "hard_timeout", 0, MAX_PRIORITY),
        cookie=flow_cookie(flow_id),
    )


def parse_qos_request(body: Mapping[str, Any]) -> FlowSpec:
    """Validate a POST /qos/queue body: matching traffic -> set_queue(queue_id) -> out_port."""
    _check_keys(body, _QOS_KEYS, required=_QOS_KEYS)
    return parse_flow_request(
        {
            "flow_id": body["flow_id"],
            "dpid": body["dpid"],
            "priority": QOS_PRIORITY,
            "match": body["match"],
            "actions": [{"queue": body["queue_id"]}, {"output": body["out_port"]}],
        }
    )


# --------------------------------------------------------------------------- helpers


def _check_keys(body: Mapping[str, Any], allowed: set[str], required: set[str]) -> None:
    if not isinstance(body, Mapping):
        raise ValueError("body must be a JSON object")
    unknown = set(body) - allowed
    if unknown:
        raise ValueError(f"unknown field(s): {sorted(unknown)}")
    missing = required - set(body)
    if missing:
        raise ValueError(f"missing field(s): {sorted(missing)}")


def _flow_id(value: Any) -> str:
    if not isinstance(value, str) or not _FLOW_ID.match(value):
        raise ValueError("flow_id must be 1-64 chars of [A-Za-z0-9_.:-]")
    return value


def _dpid(value: Any) -> int:
    try:
        dpid = int(value, 16) if isinstance(value, str) else int(value)
    except (TypeError, ValueError):
        raise ValueError(f"dpid must be an int or hex string, got {value!r}") from None
    if dpid < 0 or dpid >= 1 << 64:
        raise ValueError(f"dpid out of range: {value!r}")
    return dpid


def _int_in(value: Any, name: str, lo: int, hi: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not lo <= value <= hi:
        raise ValueError(f"{name} must be an integer in [{lo}, {hi}], got {value!r}")
    return value


def _match(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, Mapping) or not raw:
        raise ValueError("match must be a non-empty object")
    match: dict[str, Any] = {}
    for key, value in raw.items():
        if key == "in_port":
            match[key] = _int_in(value, "in_port", 1, 0xFFFFFF00)
        elif key in ("eth_src", "eth_dst"):
            if not isinstance(value, str) or not _MAC.match(value):
                raise ValueError(f"{key} must be a MAC address, got {value!r}")
            match[key] = value.lower()
        elif key in ("ipv4_src", "ipv4_dst"):
            try:
                match[key] = str(ipaddress.IPv4Address(value))
            except ValueError:
                raise ValueError(f"{key} must be an IPv4 address, got {value!r}") from None
        elif key == "ip_proto":
            match[key] = _int_in(value, "ip_proto", 0, MAX_IP_PROTO)
        elif key == "eth_type":
            match[key] = _int_in(value, "eth_type", 0, 0xFFFF)
        else:
            raise ValueError(f"unknown match field {key!r}")
    if any(k in match for k in ("ipv4_src", "ipv4_dst", "ip_proto")):
        match.setdefault("eth_type", ETH_TYPE_IPV4)  # OpenFlow prerequisite
    return match


def _actions(raw: Any) -> list[Action]:
    if not isinstance(raw, list) or not raw:
        raise ValueError("actions must be a non-empty list")
    actions: list[Action] = []
    for item in raw:
        if not isinstance(item, Mapping) or len(item) != 1:
            raise ValueError("each action must be an object with exactly one key")
        ((kind, value),) = item.items()
        actions.append(_action(kind, value))
    kinds = [k for k, _ in actions]
    if "drop" in kinds and len(actions) > 1:
        raise ValueError("drop cannot be combined with other actions")
    if "queue" in kinds and "output" not in kinds:
        raise ValueError("a queue action needs an output action too")
    return actions


def _action(kind: str, value: Any) -> Action:
    if kind == "output":
        if isinstance(value, str):
            if value not in SPECIAL_PORTS:
                raise ValueError(f"output must be a port number or one of {SPECIAL_PORTS}")
            return ("output", value)
        return ("output", _int_in(value, "output port", 1, 0xFFFFFF00))
    if kind == "queue":
        if value not in QUEUE_IDS or isinstance(value, bool):
            raise ValueError(f"queue must be one of {QUEUE_IDS}, got {value!r}")
        return ("queue", value)
    if kind == "drop":
        if value is not True:
            raise ValueError("drop must be true")
        return ("drop", 0)
    raise ValueError(f"unknown action {kind!r}")
