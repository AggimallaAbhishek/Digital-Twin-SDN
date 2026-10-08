"""P4.4 actuator: turns an action into AP agent calls (testbed/ap_agent.py) and back.

`apply` reads the current configuration first and returns it; `revert` puts it back. The radio
lives behind the AP agent (OpenFlow can't touch it) and so does QoS (enforced on the AP downlink,
deviation #11); `reroute_flow` is not supported on the campus tree (deviation #9). QoS matches
are resolved to flows with the twin's own rule (twin/sim/apply.py `qos_flow_ids`), so the
network gets exactly what was simulated. Only the executor calls this.
"""

from __future__ import annotations

import json
import urllib.request
from collections.abc import Callable
from typing import Any

from common.influx import is_http_url
from common.schemas import (
    Action,
    ApAdminState,
    RateLimitFlow,
    SetApChannel,
    SetApTxPower,
    SetQosQueue,
    SteerClients,
)
from twin.sim.apply import qos_flow_ids
from twin.state.model import TwinState

TIMEOUT_S = 10.0  # a channel switch waits for the CSA and a steer for re-association (~4 s)
# (method, path, JSON body or None, timeout) -> parsed JSON reply
Transport = Callable[[str, str, Any, float], Any]  # Any: JSON


class AgentActuator:
    """Applies and reverts actions through the AP agent's REST API."""

    def __init__(self, base_url: str, transport: Transport | None = None) -> None:
        if not is_http_url(base_url):
            raise ValueError(f"AP agent URL must be http(s): {base_url!r}")
        self._call = transport or _http(base_url.rstrip("/"))

    def apply(self, action: Action, state: TwinState) -> dict[str, Any]:  # Any: JSON config
        """Apply `action`; return the configuration it replaced."""
        if isinstance(action, SteerClients):
            p = action.params
            for sta in p.stations:
                self._post(f"/stations/{sta}/associate", {"ap": p.to_ap})
            return {"stations": {sta: p.from_ap for sta in p.stations}}
        if isinstance(action, SetApChannel):
            old = self._ap(action.params.ap)["channel"]
            self._post(f"/aps/{action.params.ap}/channel", {"channel": action.params.channel})
            return {"channel": old}
        if isinstance(action, SetApTxPower):
            old = self._ap(action.params.ap)["tx_power_dbm"]
            self._post(f"/aps/{action.params.ap}/txpower", {"dbm": action.params.dbm})
            return {"dbm": old}
        if isinstance(action, ApAdminState):
            self._ap(action.params.ap)
            self._post(f"/aps/{action.params.ap}/admin", {"state": action.params.state})
            return {"state": "up" if action.params.state == "down" else "down"}
        if isinstance(action, SetQosQueue):
            qos = self._qos()
            flows = qos_flow_ids(state, action.params.match)
            for flow in flows:
                self._post(f"/flows/{flow}/queue", {"queue_id": action.params.queue_id})
            return {"queues": {f: qos.get(f, {}).get("queue_id", 0) for f in flows}}
        if isinstance(action, RateLimitFlow):
            old = self._qos().get(action.params.flow_id, {}).get("max_mbps")
            self._post(
                f"/flows/{action.params.flow_id}/limit", {"max_mbps": action.params.max_mbps}
            )
            return {"max_mbps": old}
        raise ValueError(f"{action.type}: not supported on the campus tree (deviation #9)")

    def revert(self, action: Action, previous: dict[str, Any]) -> None:  # Any: JSON config
        """Put back what `apply` replaced."""
        if isinstance(action, SteerClients):
            for sta, ap in previous["stations"].items():
                self._post(f"/stations/{sta}/associate", {"ap": ap})
        elif isinstance(action, SetApChannel):
            self._post(f"/aps/{action.params.ap}/channel", previous)
        elif isinstance(action, SetApTxPower):
            self._post(f"/aps/{action.params.ap}/txpower", previous)
        elif isinstance(action, ApAdminState):
            self._post(f"/aps/{action.params.ap}/admin", previous)
        elif isinstance(action, SetQosQueue):
            for flow, queue in previous["queues"].items():
                self._post(f"/flows/{flow}/queue", {"queue_id": queue})
        elif isinstance(action, RateLimitFlow):
            self._post(f"/flows/{action.params.flow_id}/limit", previous)

    def _post(self, path: str, body: dict[str, Any]) -> None:  # Any: JSON
        self._call("POST", path, body, TIMEOUT_S)

    def _ap(self, name: str) -> dict[str, Any]:  # Any: JSON
        for ap in self._call("GET", "/aps", None, TIMEOUT_S)["aps"]:
            if ap["ap"] == name:
                return dict(ap)
        raise ValueError(f"the AP agent does not know {name}")

    def _qos(self) -> dict[str, Any]:  # Any: JSON
        return dict(self._call("GET", "/qos", None, TIMEOUT_S)["flows"])


def _http(base_url: str) -> Transport:
    def call(method: str, path: str, body: Any, timeout_s: float) -> Any:  # Any: JSON
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(  # noqa: S310 - http(s) only, checked in __init__
            base_url + path, data=data, method=method, headers={"Content-Type": "application/json"}
        )
        # http(s) only: the scheme is checked in AgentActuator.__init__ (ruff S310, bandit B310)
        with urllib.request.urlopen(request, timeout=timeout_s) as response:  # noqa: S310  # nosec B310
            return json.loads(response.read() or b"null")

    return call
