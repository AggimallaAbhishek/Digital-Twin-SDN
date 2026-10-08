"""P3.2 apply an allow-listed Action to a copy of the TwinState (RULEBOOK C-7).

`apply(state, action)` returns a new TwinState; the input is never changed. What each action
does to the twin:

- steer_clients: the stations move to `to_ap`.
- set_ap_channel / set_ap_tx_power: that AP's channel / transmit power.
- ap_admin_state down: the AP is down with zero utilisation; its stations rejoin the nearest AP
  that is still up (the testbed's rule, decision P1.6-A), or none if no AP is up.
  up: the AP is up again; nobody moves back (clients are sticky).
- set_qos_queue: flows matching the zone / app class / flow id get the queue.
- rate_limit_flow: the flow gets a rate cap.
- reroute_flow: the flow records the explicit path (whether it exists is the verifier's job).

Static bounds were already checked by the Action schema and state-dependent ones are the
verifier's (P3.4); apply only refuses targets that are not in the state (ValueError).
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Callable, Iterable, Mapping
from typing import Any, TypeVar

from common.schemas import (
    Action,
    ApAdminState,
    QosMatch,
    RateLimitFlow,
    RerouteFlow,
    SetApChannel,
    SetApTxPower,
    SetQosQueue,
    SteerClients,
)
from twin.state.model import APState, FlowState, TwinState

T = TypeVar("T")


def apply(state: TwinState, action: Action) -> TwinState:
    """A copy of `state` with `action` applied; ValueError if a target is unknown or stale."""
    # Any: each handler takes its own Action subclass; _HANDLERS pairs them by type
    handler: Callable[[TwinState, Any], TwinState] = _HANDLERS[type(action)]
    return handler(state, action)


def _steer(state: TwinState, action: SteerClients) -> TwinState:
    p = action.params
    _need(state.aps, [p.from_ap, p.to_ap], "AP")
    _need(state.stations, p.stations, "station")
    for name in p.stations:
        if state.stations[name].ap != p.from_ap:
            raise ValueError(f"{name} is not on {p.from_ap}")
    stations = {**state.stations}
    for name in p.stations:
        stations[name] = dataclasses.replace(stations[name], ap=p.to_ap)
    return dataclasses.replace(state, stations=stations)


def _set_channel(state: TwinState, action: SetApChannel) -> TwinState:
    return _replace_ap(state, action.params.ap, channel=action.params.channel)


def _set_tx_power(state: TwinState, action: SetApTxPower) -> TwinState:
    return _replace_ap(state, action.params.ap, tx_power_dbm=float(action.params.dbm))


def _admin_state(state: TwinState, action: ApAdminState) -> TwinState:
    name = action.params.ap
    if action.params.state == "up":
        return _replace_ap(state, name, up=True)
    down = _replace_ap(state, name, up=False, util=0.0)
    up = down.up_aps()
    stations = {**down.stations}
    for sta in down.clients(name):
        position = stations[sta].position
        nearest = min(up, key=lambda ap: math.dist(ap.position, position)).name if up else None
        stations[sta] = dataclasses.replace(stations[sta], ap=nearest)
    return dataclasses.replace(down, stations=stations)


def qos_flow_ids(state: TwinState, match: QosMatch) -> list[str]:
    """The flows a QoS match selects (by flow id, app class and the zone of the station), sorted.
    The executor's actuator uses this too, so the network gets what the twin simulated."""

    def matches(flow: FlowState) -> bool:
        station = state.stations.get(flow.sta)
        zone = station.zone if station is not None else None
        return (
            (match.flow_id is None or flow.flow_id == match.flow_id)
            and (match.app_class is None or flow.app_class == match.app_class)
            and (match.zone is None or zone == match.zone)
        )

    return sorted(fid for fid, f in state.flows.items() if matches(f))


def _qos(state: TwinState, action: SetQosQueue) -> TwinState:
    selected = set(qos_flow_ids(state, action.params.match))
    queue = action.params.queue_id
    flows = {
        fid: dataclasses.replace(f, queue_id=queue) if fid in selected else f
        for fid, f in state.flows.items()
    }
    return dataclasses.replace(state, flows=flows)


def _rate_limit(state: TwinState, action: RateLimitFlow) -> TwinState:
    p = action.params
    return _replace_flow(state, p.flow_id, rate_limit_mbps=p.max_mbps)


def _reroute(state: TwinState, action: RerouteFlow) -> TwinState:
    p = action.params
    return _replace_flow(state, p.flow_id, path=tuple(p.path))


def _replace_ap(state: TwinState, name: str, **changes: Any) -> TwinState:  # Any: APState fields
    _need(state.aps, [name], "AP")
    aps: dict[str, APState] = {**state.aps, name: dataclasses.replace(state.aps[name], **changes)}
    return dataclasses.replace(state, aps=aps)


def _replace_flow(state: TwinState, flow_id: str, **changes: Any) -> TwinState:  # FlowState fields
    _need(state.flows, [flow_id], "flow")
    flow = dataclasses.replace(state.flows[flow_id], **changes)
    return dataclasses.replace(state, flows={**state.flows, flow_id: flow})


def _need(known: Mapping[str, T], names: Iterable[str], what: str) -> None:
    missing = [n for n in names if n not in known]
    if missing:
        raise ValueError(f"unknown {what}: {', '.join(missing)}")


_HANDLERS: dict[type, Callable[[TwinState, Any], TwinState]] = {  # Any: as in apply()
    SteerClients: _steer,
    SetApChannel: _set_channel,
    SetApTxPower: _set_tx_power,
    ApAdminState: _admin_state,
    SetQosQueue: _qos,
    RateLimitFlow: _rate_limit,
    RerouteFlow: _reroute,
}
