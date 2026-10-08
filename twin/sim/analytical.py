"""P3.3 analytical simulator: a TwinState -> predicted per-flow and network KPIs (pure, fast).

Used as `simulate(apply(state, action))` against `simulate(state)` by the verifier (P3.4). Steady
state of each AP that is up (the AP's downlink is the bottleneck: wired links are 100 Mbit/s
against 4.6 at the AP, so they are not modelled, deviation #12):

- **Capacity** C = ap_capacity_mbps, capped by co-channel APs that are up (twin/radio.py, the
  model the testbed emulates, deviation #7).
- **Demand** per flow by app class (config/sim.yaml), cut to its rate limit if it has one.
- **Sharing:** strict priority between OVS queues (1 = priority, then 0 = best effort, then
  2 = background); within a queue, what is left is shared max-min fair (water-filling).
  (The testbed does not provision these queues yet: deviation #11.)
- **Loss:** inelastic traffic (video, web) loses what it cannot send; TCP bulk adapts and only
  sees base loss.
- **Latency:** base + service_ms * mean queue length of an M/M/1/K queue at load rho = offered
  demand of the flow's queue and the queues served before it, / C. The bounded queue levels
  latency off at saturation, as measured (data/v1).
- **Web throughput** is what the KPI probe measures: the rate of one fetch, web_efficiency times
  the capacity not used by other traffic in the same or a higher-priority queue.
- **Network KPIs:** total throughput, mean latency and mean loss over all flows, and Jain's index
  of the client count of the APs that are up (problem statement §5.1).
- A flow whose station has no AP, or whose AP is down, is **dead**: throughput 0, loss 100%,
  latency = the probe timeout.
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from common.schemas import KPIValues
from twin.radio import RadioParams, capped_capacity_mbps, cochannel_load
from twin.state.model import APState, FlowState, TwinState

INELASTIC = ("video", "web")
SERVICE_ORDER = (1, 0, 2)  # OVS queues, highest priority first (common/schemas.py QOS_QUEUE_IDS)


@dataclass(frozen=True)
class SimParams:
    """config/sim.yaml."""

    video_mbps: float
    web_mbps: float
    bulk_mbps: float
    web_efficiency: float
    base_latency_ms: float
    service_ms: float
    queue_slots: int
    base_loss_pct: float
    dead_latency_ms: float


_KEYS = tuple(f.name for f in dataclasses.fields(SimParams))


@dataclass(frozen=True)
class FlowResult:
    """Predicted KPIs of one flow."""

    throughput_mbps: float
    latency_ms: float
    loss_pct: float


@dataclass(frozen=True)
class SimResult:
    """Predicted per-flow KPIs, the utilisation of every AP that is up, and network KPIs."""

    flows: Mapping[str, FlowResult]
    ap_util: Mapping[str, float]
    kpis: KPIValues


def load_sim_params(raw: Mapping[str, Any]) -> SimParams:
    """Validate a parsed config/sim.yaml; ValueError names the bad field."""
    unknown = set(raw) - set(_KEYS)
    if unknown:
        raise ValueError(f"sim config: unknown keys {sorted(unknown)}")
    for key in _KEYS:
        value = raw.get(key)
        if not isinstance(value, int | float) or isinstance(value, bool) or value < 0:
            raise ValueError(f"{key} must be a number >= 0, got {value!r}")
    if not isinstance(raw["queue_slots"], int) or raw["queue_slots"] < 1:
        raise ValueError(f"queue_slots must be an integer >= 1, got {raw['queue_slots']!r}")
    if raw["web_efficiency"] > 1:
        raise ValueError(f"web_efficiency must be within [0, 1], got {raw['web_efficiency']!r}")
    numbers = {k: float(raw[k]) for k in _KEYS if k != "queue_slots"}
    return SimParams(queue_slots=raw["queue_slots"], **numbers)


def simulate(state: TwinState, radio: RadioParams, params: SimParams) -> SimResult:
    """Predicted KPIs of every flow in `state`, and every up AP's utilisation."""
    dead = FlowResult(0.0, params.dead_latency_ms, 100.0)
    results: dict[str, FlowResult] = {f: dead for f in state.flows}
    ap_util: dict[str, float] = {}
    for ap in state.up_aps():
        flows = [
            f
            for f in state.flows.values()
            if f.sta in state.stations and state.stations[f.sta].ap == ap.name
        ]
        capacity = _capacity(ap, state, radio)
        served = _ap_flows(flows, capacity, params, results)
        ap_util[ap.name] = min(1.0, served / capacity)
    return SimResult(results, ap_util, _kpis(state, results))


def _ap_flows(
    flows: list[FlowState], capacity: float, params: SimParams, out: dict[str, FlowResult]
) -> float:
    """Serve one AP's flows queue by queue into `out`; the total rate served."""
    left, offered_so_far, busy = capacity, 0.0, 0.0  # busy: rate of non-web traffic served
    for queue in SERVICE_ORDER:
        level = [f for f in flows if f.queue_id == queue]
        demand = {f.flow_id: _demand(f, params) for f in level}
        served = _water_fill(demand, left)
        left -= math.fsum(served.values())
        offered_so_far += math.fsum(demand.values())
        busy += math.fsum(served[f.flow_id] for f in level if f.app_class != "web")
        queue_len = _mm1k_queue(offered_so_far / capacity, params.queue_slots)
        latency = params.base_latency_ms + params.service_ms * queue_len
        for f in level:
            rate = served[f.flow_id]
            if f.app_class == "web":  # the probe measures one fetch's rate
                rate = params.web_efficiency * max(0.0, capacity - busy)
                rate = min(rate, f.rate_limit_mbps) if f.rate_limit_mbps is not None else rate
            out[f.flow_id] = FlowResult(rate, latency, _loss(f, demand, served, params))
    return capacity - left


def _kpis(state: TwinState, flows: Mapping[str, FlowResult]) -> KPIValues:
    results = list(flows.values())
    n = len(results)
    clients = [len(state.clients(ap.name)) for ap in state.up_aps()]
    squares = sum(c * c for c in clients)
    return KPIValues(
        throughput_mbps=math.fsum(r.throughput_mbps for r in results),
        latency_ms=math.fsum(r.latency_ms for r in results) / n if n else 0.0,
        loss_pct=math.fsum(r.loss_pct for r in results) / n if n else 0.0,
        jain=sum(clients) ** 2 / (len(clients) * squares) if squares else 1.0,
    )


def _capacity(ap: APState, state: TwinState, radio: RadioParams) -> float:
    neighbours = [
        math.dist(ap.position, o.position)
        for o in state.up_aps()
        if o.name != ap.name and o.channel == ap.channel
    ]
    capped = capped_capacity_mbps(cochannel_load(neighbours, radio), radio)
    return capped if capped is not None else radio.ap_capacity_mbps


def _demand(flow: FlowState, params: SimParams) -> float:
    """What the flow can get through: what its source sends, cut to its rate limit."""
    offered = _offered(flow, params)
    return min(offered, flow.rate_limit_mbps) if flow.rate_limit_mbps is not None else offered


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


def _mm1k_queue(rho: float, k: int) -> float:
    """Mean number waiting-or-served in an M/M/1/K queue at load `rho`."""
    if math.isclose(rho, 1.0):
        return k / 2
    return rho / (1 - rho) - (k + 1) * rho ** (k + 1) / (1 - rho ** (k + 1))


def _loss(
    flow: FlowState, demand: Mapping[str, float], served: Mapping[str, float], params: SimParams
) -> float:
    if flow.app_class not in INELASTIC or demand[flow.flow_id] == 0:
        return params.base_loss_pct
    unserved = 1 - served[flow.flow_id] / _offered(flow, params)
    return min(100.0, 100 * unserved + params.base_loss_pct)


def _offered(flow: FlowState, params: SimParams) -> float:
    """What the source sends, before any rate limit polices it."""
    return {"video": params.video_mbps, "web": params.web_mbps, "bulk": params.bulk_mbps}[
        flow.app_class
    ]
