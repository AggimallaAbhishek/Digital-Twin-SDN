"""P4.4a QoS on the AP downlink: strict-priority queues and per-flow rate limits (deviation #11).

The bottleneck is each AP's radio, so QoS is enforced there with tc, in the same HTB tree as the
interference cap (testbed/interference.py). The AP agent owns the tree: it re-renders an AP's
tree whenever its cap or any flow's QoS changes, and every AP gets the same filters (they match
the station's IP, so a steered station keeps its treatment without moving rules).

    root 1: htb default 21
    └── 1:1  rate = the AP's cap (or nominal capacity)
        ├── 1:10  queue 1 (priority)     htb prio 0
        │   ├── 1:11   its unlimited traffic (fq_codel)
        │   └── 1:1xx  one class per rate-limited flow in the queue, ceil = its limit
        ├── 1:20  queue 0 (best effort)  htb prio 1; leaf 1:21 is the default
        └── 1:30  queue 2 (background)   htb prio 2; leaf 1:31

An HTB class with children cannot hold packets, so each queue keeps its unlimited traffic in a
leaf of its own.

Each queue class guarantees almost nothing (8 kbit) and borrows the rest from 1:1 in htb prio
order, so a higher queue is served first. A flow is matched by station IP + the srv1 port it
comes from (iperf3 reverse mode / HTTP); a station's ping replies (the latency probe) share the
queue of its highest-priority flow (decision P4.4a-A), so the probe measures what that flow
gets. Pure Python 3.8, no Mininet import: unit-tested on the Mac.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from testbed.interference import tc_commands

QOS_QUEUE_IDS = (0, 1, 2)  # = common/schemas.py QOS_QUEUE_IDS (contract test)
RATE_LIMIT_MIN_MBPS = 1.0  # = common/schemas.py RATE_LIMIT_MIN_MBPS (contract test)
_QUEUE_CLASS = {1: (10, 0), 0: (20, 1), 2: (30, 2)}  # queue -> (class minor, htb prio)
_PRIORITY_ORDER = (1, 0, 2)  # highest first
_GUARANTEE = "8kbit"


@dataclass(frozen=True)
class FlowQos:
    """What a flow should get: its queue, and an optional rate limit."""

    queue_id: int
    limit_mbps: float | None = None

    def __post_init__(self) -> None:
        if self.queue_id not in QOS_QUEUE_IDS:
            raise ValueError(f"queue_id must be one of {QOS_QUEUE_IDS}, got {self.queue_id!r}")
        if self.limit_mbps is not None and self.limit_mbps < RATE_LIMIT_MIN_MBPS:
            raise ValueError(f"limit_mbps must be >= {RATE_LIMIT_MIN_MBPS}, got {self.limit_mbps}")


@dataclass(frozen=True)
class FlowRule:
    """One tc filter: traffic to `dst_ip` from srv1 port `sport` (None: ICMP, the ping probe)."""

    name: str
    dst_ip: str
    sport: int | None
    queue_id: int
    limit_mbps: float | None


def flow_rules(
    qos: Mapping[str, FlowQos], endpoints: Mapping[str, tuple[str, int]]
) -> list[FlowRule]:
    """Filters for every flow that needs one (not plain best effort) and has started, by name,
    then one ping rule per station with a non-default queue."""
    rules = []
    best: dict[str, int] = {}  # station IP -> its highest-priority queue
    for flow_id in sorted(qos):
        want = qos[flow_id]
        if flow_id not in endpoints or (want.queue_id == 0 and want.limit_mbps is None):
            continue
        ip, port = endpoints[flow_id]
        rules.append(FlowRule(flow_id, ip, port, want.queue_id, want.limit_mbps))
        if ip not in best or _PRIORITY_ORDER.index(want.queue_id) < _PRIORITY_ORDER.index(best[ip]):
            best[ip] = want.queue_id
    rules += [FlowRule(f"ping-{ip}", ip, None, q, None) for ip, q in sorted(best.items()) if q != 0]
    return rules


def tc_tree(
    intf: str, cap_mbps: float | None, nominal_mbps: float, rules: Sequence[FlowRule]
) -> list[str]:
    """Shell commands that build `intf`'s whole egress tree (rebuilt from scratch each time)."""
    if not rules:
        return tc_commands(intf, cap_mbps)  # just the interference cap, as calibrated in P1.6
    dev = f"dev {intf}"
    rate = f"{cap_mbps if cap_mbps is not None else nominal_mbps:g}mbit"
    commands = [
        f"tc qdisc del {dev} root",
        f"tc qdisc add {dev} root handle 1: htb default 21",
        f"tc class add {dev} parent 1: classid 1:1 htb rate {rate} ceil {rate}",
    ]
    for minor, prio in _QUEUE_CLASS.values():
        leaf = minor + 1
        commands += [
            f"tc class add {dev} parent 1:1 classid 1:{minor} htb rate {_GUARANTEE} ceil {rate} "
            f"prio {prio}",
            f"tc class add {dev} parent 1:{minor} classid 1:{leaf} htb rate {_GUARANTEE} "
            f"ceil {rate} prio {prio}",
            f"tc qdisc add {dev} parent 1:{leaf} handle {leaf}: fq_codel",
        ]
    targets = []
    for n, rule in enumerate(rules, start=1):
        minor, prio = _QUEUE_CLASS[rule.queue_id]
        target = f"1:{minor + 1}"
        if rule.limit_mbps is not None:
            target = f"1:{100 + n}"
            commands += [
                f"tc class add {dev} parent 1:{minor} classid {target} htb rate {_GUARANTEE} "
                f"ceil {rule.limit_mbps:g}mbit prio {prio}",
                f"tc qdisc add {dev} parent {target} handle {100 + n}: fq_codel",
            ]
        targets.append(target)
    for n, (rule, target) in enumerate(zip(rules, targets), start=1):
        match = f"match ip dst {rule.dst_ip}/32 " + (
            f"match ip sport {rule.sport} 0xffff"
            if rule.sport is not None
            else "match ip protocol 1 0xff"
        )
        commands.append(
            f"tc filter add {dev} parent 1: protocol ip prio {n} u32 {match} flowid {target}"
        )
    return commands
