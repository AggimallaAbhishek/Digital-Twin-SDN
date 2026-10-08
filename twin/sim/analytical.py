"""P3.3 analytical simulator: a TwinState -> predicted per-flow and network KPIs (pure, fast).

Used as `simulate(apply(state, action))` against `simulate(state)` by the verifier (P3.4). Steady
state of each AP that is up (the AP's downlink is the bottleneck: wired links are 100 Mbit/s
against 4.6 at the AP, so they are not modelled, deviation #12):

- **Capacity** C = ap_capacity_mbps, capped by co-channel APs that are up (twin/radio.py, the
  model the testbed emulates, deviation #7).
- **Demand** per flow: its app class's offered rate (config/sim.yaml `apps`), cut to its rate
  limit if it has one.
- **Sharing:** strict priority between OVS queues (1 = priority, then 0 = best effort, then
  2 = background); within a queue, what is left is shared max-min fair (water-filling).
  (The testbed does not provision these queues yet: deviation #11.)
- **Loss:** inelastic classes lose what they cannot send; elastic (TCP) classes adapt and only
  see base loss.
- **Latency:** base + service_ms * L, with L the mean number in an M/M/1/K queue at load rho =
  offered demand of the queue and the queues served before it, / C. The bounded queue levels
  latency off at saturation, as measured (data/v1). The KPI probe pings once per station, and
  its replies share the station's highest-priority queue (testbed/qos.py, decision P4.4a-A), so
  every flow of a station reports that queue's latency.
- **Fetch classes** (web): the probe reports the rate of one fetch, fetch_efficiency times the
  capacity not used by other (non-fetch) traffic in the same or a higher-priority queue. The
  traffic they put on the air is their small served rate (`carried_mbps`).
- **Network KPIs:** total traffic carried, mean latency and mean loss over all flows, and Jain's
  index of the client count of the APs that are up (problem statement §5.1).
- A flow whose station has no AP, or whose AP is down, is **dead**: throughput 0, loss 100%,
  latency = the probe timeout.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, get_args

from common.schemas import AppClass, KPIValues
from twin.radio import RadioParams, capped_capacity_mbps, cochannel_load
from twin.state.model import APState, FlowState, TwinState

SERVICE_ORDER = (1, 0, 2)  # OVS queues, highest priority first (common/schemas.py QOS_QUEUE_IDS)
_APP_KEYS = {"offered_mbps", "elastic", "fetch"}
_NUMBERS = ("fetch_efficiency", "base_latency_ms", "service_ms", "base_loss_pct", "dead_latency_ms")


@dataclass(frozen=True)
class AppModel:
    """How one app class loads the AP and how its KPIs are measured."""

    offered_mbps: float  # what the source sends
    elastic: bool  # TCP: adapts to its share, so it only sees base loss
    fetch: bool  # the probe reports one fetch's rate, not the average rate


@dataclass(frozen=True)
class SimParams:
    """config/sim.yaml."""

    enabled: bool  # RULEBOOK B-5: callers (verifier, API, loop) only use the model when on
    apps: Mapping[str, AppModel]
    fetch_efficiency: float
    base_latency_ms: float
    service_ms: float
    queue_slots: int
    base_loss_pct: float
    dead_latency_ms: float


@dataclass(frozen=True)
class FlowResult:
    """Predicted KPIs of one flow, as the KPI probe would measure them.

    `carried_mbps` is the traffic the flow puts on the air. It differs from `throughput_mbps`
    only for fetch classes (web), whose fetches rarely overlap."""

    throughput_mbps: float
    latency_ms: float
    loss_pct: float
    carried_mbps: float


@dataclass(frozen=True)
class SimResult:
    """Predicted per-flow KPIs, the utilisation of every AP that is up, and network KPIs."""

    flows: Mapping[str, FlowResult]
    ap_util: Mapping[str, float]
    kpis: KPIValues


def load_sim_params(raw: Mapping[str, Any]) -> SimParams:
    """Validate a parsed config/sim.yaml; ValueError names the bad field."""
    known = {"enabled", "apps", "queue_slots", *_NUMBERS}
    unknown = set(raw) - known
    if unknown:
        raise ValueError(f"sim config: unknown keys {sorted(unknown)}")
    if not isinstance(raw.get("enabled"), bool):
        raise ValueError(f"enabled must be true or false, got {raw.get('enabled')!r}")
    for key in _NUMBERS:
        _non_negative(key, raw.get(key))
    slots = raw.get("queue_slots")
    if not isinstance(slots, int) or isinstance(slots, bool) or slots < 1:
        raise ValueError(f"queue_slots must be an integer >= 1, got {slots!r}")
    if raw["fetch_efficiency"] > 1:
        raise ValueError(f"fetch_efficiency must be within [0, 1], got {raw['fetch_efficiency']!r}")
    return SimParams(
        enabled=raw["enabled"],
        apps=_load_apps(raw.get("apps")),
        queue_slots=slots,
        **{k: float(raw[k]) for k in _NUMBERS},
    )


def _load_apps(raw: Any) -> dict[str, AppModel]:  # Any: parsed YAML, checked here
    classes = set(get_args(AppClass))
    if not isinstance(raw, Mapping) or set(raw) != classes:
        raise ValueError(f"apps must have exactly the app classes {sorted(classes)}")
    apps = {}
    for name, entry in raw.items():
        if not isinstance(entry, Mapping) or set(entry) != _APP_KEYS:
            raise ValueError(f"apps.{name} needs exactly {sorted(_APP_KEYS)}")
        _non_negative(f"apps.{name}.offered_mbps", entry["offered_mbps"])
        for flag in ("elastic", "fetch"):
            if not isinstance(entry[flag], bool):
                raise ValueError(f"apps.{name}.{flag} must be true or false")
        apps[name] = AppModel(float(entry["offered_mbps"]), entry["elastic"], entry["fetch"])
    return apps


def _non_negative(key: str, value: Any) -> None:  # Any: parsed YAML, checked here
    if not isinstance(value, int | float) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{key} must be a number >= 0, got {value!r}")


def simulate(state: TwinState, radio: RadioParams, params: SimParams) -> SimResult:
    """Predicted KPIs of every flow in `state`, and every up AP's utilisation."""
    dead = FlowResult(0.0, params.dead_latency_ms, 100.0, 0.0)
    results: dict[str, FlowResult] = {f: dead for f in state.flows}
    up = state.up_aps()
    by_ap: dict[str, list[FlowState]] = defaultdict(list)
    for flow in state.flows.values():
        station = state.stations.get(flow.sta)
        if station is not None and station.ap is not None:
            by_ap[station.ap].append(flow)
    ap_util: dict[str, float] = {}
    for ap in up:
        capacity = _capacity(ap, up, radio)
        served = _serve_ap(by_ap[ap.name], capacity, params, results)
        ap_util[ap.name] = min(1.0, served / capacity)
    return SimResult(results, ap_util, _kpis(state, up, results))


def _serve_ap(
    flows: list[FlowState], capacity: float, params: SimParams, out: dict[str, FlowResult]
) -> float:
    """Serve one AP's flows queue by queue into `out`; the total rate served."""
    left, offered_so_far, busy = capacity, 0.0, 0.0  # busy: non-fetch traffic served so far
    latency: dict[int, float] = {}  # per queue
    rates: dict[str, tuple[float, float, float]] = {}  # flow -> (probe rate, loss, carried)
    for queue in SERVICE_ORDER:
        level = [f for f in flows if f.queue_id == queue]
        demand = {f.flow_id: _capped(params.apps[f.app_class].offered_mbps, f) for f in level}
        served = _water_fill(demand, left)
        left -= math.fsum(served.values())
        offered_so_far += math.fsum(demand.values())
        busy += math.fsum(served[f.flow_id] for f in level if not params.apps[f.app_class].fetch)
        latency[queue] = params.base_latency_ms + params.service_ms * _mm1k_mean_number(
            offered_so_far / capacity, params.queue_slots
        )
        for f in level:
            app, carried = params.apps[f.app_class], served[f.flow_id]
            fetch_rate = params.fetch_efficiency * max(0.0, capacity - busy)
            rate = _capped(fetch_rate, f) if app.fetch else carried
            rates[f.flow_id] = (rate, _loss(app, carried, params), carried)
    # the probe pings once per station; its replies share the station's highest-priority queue
    # (testbed/qos.py, decision P4.4a-A), so all the station's flows report that queue's latency
    ping_queue: dict[str, int] = {}
    for f in flows:
        best = ping_queue.get(f.sta, f.queue_id)
        ping_queue[f.sta] = min(best, f.queue_id, key=SERVICE_ORDER.index)
    for f in flows:
        rate, loss, carried = rates[f.flow_id]
        out[f.flow_id] = FlowResult(rate, latency[ping_queue[f.sta]], loss, carried)
    return capacity - left


def _capped(rate: float, flow: FlowState) -> float:
    """`rate`, cut to the flow's rate limit if it has one."""
    return min(rate, flow.rate_limit_mbps) if flow.rate_limit_mbps is not None else rate


def _kpis(state: TwinState, up: list[APState], flows: Mapping[str, FlowResult]) -> KPIValues:
    """Network KPIs. Jain's fairness index over the client counts x_i of the up APs:
    J = (sum x_i)^2 / (n * sum x_i^2) (R. Jain, D. Chiu, W. Hawe, DEC-TR-301, 1984); 1 = even."""
    results = list(flows.values())
    n = len(results)
    clients = [len(state.clients(ap.name)) for ap in up]
    squares = sum(c * c for c in clients)
    return KPIValues(
        throughput_mbps=math.fsum(r.carried_mbps for r in results),  # fetch rates don't add
        latency_ms=math.fsum(r.latency_ms for r in results) / n if n else 0.0,
        loss_pct=math.fsum(r.loss_pct for r in results) / n if n else 0.0,
        jain=sum(clients) ** 2 / (len(clients) * squares) if squares else 1.0,
    )


def _capacity(ap: APState, up: list[APState], radio: RadioParams) -> float:
    neighbours = [
        math.dist(ap.position, o.position)
        for o in up
        if o.name != ap.name and o.channel == ap.channel
    ]
    capped = capped_capacity_mbps(cochannel_load(neighbours, radio), radio)
    return capped if capped is not None else radio.ap_capacity_mbps


def _water_fill(demand: Mapping[str, float], capacity: float) -> dict[str, float]:
    """Max-min fair shares of `capacity`: nobody gets more than it asks for."""
    served: dict[str, float] = {}
    left = capacity
    pending = sorted(demand, key=lambda k: (demand[k], k))
    while pending:
        share = left / len(pending)
        name = pending[0]
        if demand[name] <= share:
            served[name] = demand[name]
            left -= demand[name]
            pending.pop(0)
        else:
            for rest in pending:
                served[rest] = share
            break
    return served


def _mm1k_mean_number(rho: float, k: int) -> float:
    """Mean number in an M/M/1/K queue (at most K in the system) at load rho:

        L = rho / (1 - rho) - (K + 1) * rho^(K+1) / (1 - rho^(K+1)),   L = K / 2 at rho = 1

    (L. Kleinrock, Queueing Systems Vol. 1, 1975, §3.6). Defined for any rho >= 0, including
    overload, which is why it suits a saturated AP better than M/M/1."""
    if math.isclose(rho, 1.0):
        return k / 2
    return rho / (1 - rho) - (k + 1) * rho ** (k + 1) / (1 - rho ** (k + 1))


def _loss(app: AppModel, carried: float, params: SimParams) -> float:
    """Inelastic traffic loses the share of what it sends that was not carried."""
    if app.elastic or app.offered_mbps == 0:
        return params.base_loss_pct
    return min(100.0, 100 * (1 - carried / app.offered_mbps) + params.base_loss_pct)
