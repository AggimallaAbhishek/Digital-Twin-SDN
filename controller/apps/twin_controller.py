"""P1.2 Ryu app: L2 learning + stats polling + northbound REST for the digital twin.

Runs on the testbed VM in ~/ryu-venv (Python 3.8, Ryu 4.34, ADR-002), from the repo root:

    PYTHONPATH=. ~/ryu-venv/bin/ryu-manager controller.apps.twin_controller   # REST on :8080

REST (JSON):
    GET    /stats/ports      latest per-port counters + rates for every datapath
    GET    /stats/flows      latest flow entries (ours carry their flow_id)
    GET    /topology         datapaths with ports, and learned host locations
    POST   /flows            install a flow (validated by ryu_logic.parse_flow_request)
    DELETE /flows/{flow_id}  remove a flow we installed
    POST   /qos/queue        install a set_queue + output flow (parse_qos_request)

Records omit scenario_id/run_id: the collector (P2.1) adds them and validates against
common/schemas.py on the Mac.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from typing import Any, ClassVar

from ryu.app.wsgi import ControllerBase, Response, WSGIApplication, route
from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, DEAD_DISPATCHER, MAIN_DISPATCHER, set_ev_cls
from ryu.lib import hub
from ryu.lib.packet import ether_types, ethernet, packet
from ryu.ofproto import ofproto_v1_3

from controller.apps.ryu_logic import (
    OURS_TAG,
    FlowSpec,
    dpid_str,
    is_ours,
    learn_mac,
    parse_flow_request,
    parse_qos_request,
    rate_bps,
)

APP_KEY = "twin_controller_app"
POLL_S = float(os.environ.get("TWIN_POLL_S", "1.0"))
L2_PRIORITY = 1
L2_IDLE_TIMEOUT_S = 30
HTTP_BAD_REQUEST, HTTP_NOT_FOUND, HTTP_CONFLICT = 400, 404, 409
_UNSAFE = re.compile(r"[^A-Za-z0-9_.:-]")


def _json(payload: Any, status: int = 200) -> Response:
    return Response(
        status=status,
        content_type="application/json",
        charset="utf-8",
        body=json.dumps(payload).encode(),
    )


def _iso(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(ts)) + f".{int(ts % 1 * 1000):03d}Z"


@dataclass(frozen=True)
class _Rule:
    """One OpenFlow rule to add (keeps _add_flow's signature small)."""

    priority: int
    match: Any
    actions: list[Any]
    cookie: int = 0
    idle: int = 0
    hard: int = 0


class TwinController(app_manager.RyuApp):
    """OpenFlow 1.3 learning switch with stats polling and a REST API."""

    OFP_VERSIONS: ClassVar[list[int]] = [ofproto_v1_3.OFP_VERSION]  # read by Ryu
    _CONTEXTS: ClassVar[dict[str, Any]] = {"wsgi": WSGIApplication}  # read by Ryu

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.datapaths: dict[int, Any] = {}
        self.mac_to_port: dict[int, dict[str, int]] = {}
        self.port_names: dict[int, dict[int, dict[str, str]]] = {}
        self.port_stats: dict[int, dict[int, dict[str, Any]]] = {}
        self.flow_stats: dict[int, list[dict[str, Any]]] = {}
        self._prev_port_bytes: dict[tuple[int, int], tuple[int, int, float]] = {}
        self._prev_flow_bytes: dict[tuple[int, str], tuple[int, float]] = {}
        self.installed: dict[str, FlowSpec] = {}
        kwargs["wsgi"].register(TwinRestController, {APP_KEY: self})
        self._poller = hub.spawn(self._poll)

    # ------------------------------------------------------------------ datapath lifecycle

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def _switch_features(self, ev: Any) -> None:
        dp = ev.msg.datapath
        parser, ofp = dp.ofproto_parser, dp.ofproto
        miss = [parser.OFPActionOutput(ofp.OFPP_CONTROLLER, ofp.OFPCML_NO_BUFFER)]
        self._add_flow(dp, _Rule(priority=0, match=parser.OFPMatch(), actions=miss))
        dp.send_msg(parser.OFPPortDescStatsRequest(dp, 0))

    @set_ev_cls(ofp_event.EventOFPStateChange, [MAIN_DISPATCHER, DEAD_DISPATCHER])
    def _state_change(self, ev: Any) -> None:
        dp = ev.datapath
        if ev.state == MAIN_DISPATCHER:
            self.datapaths[dp.id] = dp
        elif dp.id in self.datapaths:
            del self.datapaths[dp.id]

    @set_ev_cls(ofp_event.EventOFPPortDescStatsReply, MAIN_DISPATCHER)
    def _port_desc(self, ev: Any) -> None:
        dpid = ev.msg.datapath.id
        self.port_names[dpid] = {
            p.port_no: {"name": p.name.decode(errors="replace"), "hw_addr": p.hw_addr}
            for p in ev.msg.body
            if p.port_no < ev.msg.datapath.ofproto.OFPP_MAX
        }

    # ------------------------------------------------------------------ L2 learning

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def _packet_in(self, ev: Any) -> None:
        msg = ev.msg
        dp = msg.datapath
        parser, ofp = dp.ofproto_parser, dp.ofproto
        in_port = msg.match["in_port"]
        eth = packet.Packet(msg.data).get_protocols(ethernet.ethernet)[0]
        if eth.ethertype == ether_types.ETH_TYPE_LLDP:
            return
        if learn_mac(self.mac_to_port, dp.id, eth.src, in_port):
            self._forget_host(eth.src)
        out_port = self.mac_to_port[dp.id].get(eth.dst, ofp.OFPP_FLOOD)
        actions = [parser.OFPActionOutput(out_port)]
        if out_port != ofp.OFPP_FLOOD:
            match = parser.OFPMatch(in_port=in_port, eth_dst=eth.dst, eth_src=eth.src)
            self._add_flow(dp, _Rule(L2_PRIORITY, match, actions, idle=L2_IDLE_TIMEOUT_S))
        data = msg.data if msg.buffer_id == ofp.OFP_NO_BUFFER else None
        dp.send_msg(
            parser.OFPPacketOut(
                datapath=dp, buffer_id=msg.buffer_id, in_port=in_port, actions=actions, data=data
            )
        )

    # ------------------------------------------------------------------ stats polling

    def _poll(self) -> None:
        while True:
            for dp in list(self.datapaths.values()):
                parser, ofp = dp.ofproto_parser, dp.ofproto
                dp.send_msg(parser.OFPPortStatsRequest(dp, 0, ofp.OFPP_ANY))
                dp.send_msg(parser.OFPFlowStatsRequest(dp))
            hub.sleep(POLL_S)

    @set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
    def _port_stats(self, ev: Any) -> None:
        dpid, now = ev.msg.datapath.id, time.time()
        ports = self.port_stats.setdefault(dpid, {})
        for st in ev.msg.body:
            if st.port_no >= ev.msg.datapath.ofproto.OFPP_MAX:
                continue
            key = (dpid, st.port_no)
            prev = self._prev_port_bytes.get(key)
            rx_bps = rate_bps((prev[0], prev[2]) if prev else None, (st.rx_bytes, now))
            tx_bps = rate_bps((prev[1], prev[2]) if prev else None, (st.tx_bytes, now))
            self._prev_port_bytes[key] = (st.rx_bytes, st.tx_bytes, now)
            ports[st.port_no] = {
                "ts": _iso(now),
                "dpid": dpid_str(dpid),
                "port": st.port_no,
                "rx_bytes": st.rx_bytes,
                "tx_bytes": st.tx_bytes,
                "rx_pkts": st.rx_packets,
                "tx_pkts": st.tx_packets,
                "rx_dropped": st.rx_dropped,
                "tx_dropped": st.tx_dropped,
                "rx_bps": rx_bps,
                "tx_bps": tx_bps,
            }

    @set_ev_cls(ofp_event.EventOFPFlowStatsReply, MAIN_DISPATCHER)
    def _flow_stats(self, ev: Any) -> None:
        dpid, now = ev.msg.datapath.id, time.time()
        by_cookie = {spec.cookie: fid for fid, spec in self.installed.items()}
        records = []
        for st in ev.msg.body:
            match = {k: str(v) for k, v in st.match.items()}
            flow_id = self._flow_id(dpid, st.cookie, st.priority, match, by_cookie)
            prev = self._prev_flow_bytes.get((dpid, flow_id))
            self._prev_flow_bytes[(dpid, flow_id)] = (st.byte_count, now)
            records.append(
                {
                    "ts": _iso(now),
                    "dpid": dpid_str(dpid),
                    "flow_id": flow_id,
                    "ours": is_ours(st.cookie),
                    "priority": st.priority,
                    "match": match,
                    "bytes": st.byte_count,
                    "pkts": st.packet_count,
                    "duration_s": st.duration_sec + st.duration_nsec / 1e9,
                    "bps": rate_bps(prev, (st.byte_count, now)),
                }
            )
        self.flow_stats[dpid] = records

    @staticmethod
    def _flow_id(
        dpid: int, cookie: int, priority: int, match: dict[str, str], ours: dict[int, str]
    ) -> str:
        if cookie in ours:
            return ours[cookie]
        if priority == 0:
            return f"table_miss_{dpid_str(dpid)}"
        raw = "l2_{}_{}_{}_{}".format(
            dpid_str(dpid),
            match.get("in_port", ""),
            match.get("eth_src", ""),
            match.get("eth_dst", ""),
        )
        return _UNSAFE.sub("_", raw)[:64]

    # ------------------------------------------------------------------ flow programming

    def _add_flow(self, dp: Any, rule: _Rule) -> None:
        parser, ofp = dp.ofproto_parser, dp.ofproto
        inst = (
            [parser.OFPInstructionActions(ofp.OFPIT_APPLY_ACTIONS, rule.actions)]
            if rule.actions
            else []  # no instructions = drop
        )
        dp.send_msg(
            parser.OFPFlowMod(
                datapath=dp,
                cookie=rule.cookie,
                priority=rule.priority,
                match=rule.match,
                instructions=inst,
                idle_timeout=rule.idle,
                hard_timeout=rule.hard,
            )
        )

    def _forget_host(self, mac: str) -> None:
        """A host moved: delete the learned flows to and from it on every datapath.

        Learned flows have cookie 0; flows installed through REST carry OURS_TAG and are kept.
        Without this, traffic keeps refreshing the stale flows' idle timer and never reaches
        the host's new AP.
        """
        self.logger.info("host %s moved: deleting its learned flows", mac)
        for dp in self.datapaths.values():
            parser, ofp = dp.ofproto_parser, dp.ofproto
            for match in (parser.OFPMatch(eth_dst=mac), parser.OFPMatch(eth_src=mac)):
                dp.send_msg(
                    parser.OFPFlowMod(
                        datapath=dp,
                        cookie=0,
                        cookie_mask=OURS_TAG,
                        table_id=ofp.OFPTT_ALL,
                        command=ofp.OFPFC_DELETE,
                        out_port=ofp.OFPP_ANY,
                        out_group=ofp.OFPG_ANY,
                        match=match,
                    )
                )

    def install(self, spec: FlowSpec) -> None:
        """Install a validated flow; raise KeyError if the datapath is unknown."""
        dp = self.datapaths[spec.dpid]
        parser, ofp = dp.ofproto_parser, dp.ofproto
        special = {"normal": ofp.OFPP_NORMAL, "controller": ofp.OFPP_CONTROLLER}
        actions = []
        for kind, value in spec.actions:
            if kind == "output":
                port = special[value] if isinstance(value, str) else value
                actions.append(parser.OFPActionOutput(port))
            elif kind == "queue":
                actions.append(parser.OFPActionSetQueue(value))
        rule = _Rule(
            spec.priority,
            parser.OFPMatch(**spec.match),
            actions,
            cookie=spec.cookie,
            idle=spec.idle_timeout,
            hard=spec.hard_timeout,
        )
        self._add_flow(dp, rule)
        self.installed[spec.flow_id] = spec

    def remove(self, flow_id: str) -> None:
        """Delete one of our flows by flow_id; raise KeyError if unknown."""
        spec = self.installed.pop(flow_id)
        dp = self.datapaths[spec.dpid]
        parser, ofp = dp.ofproto_parser, dp.ofproto
        dp.send_msg(
            parser.OFPFlowMod(
                datapath=dp,
                cookie=spec.cookie,
                cookie_mask=0xFFFFFFFFFFFFFFFF,
                table_id=ofp.OFPTT_ALL,
                command=ofp.OFPFC_DELETE,
                out_port=ofp.OFPP_ANY,
                out_group=ofp.OFPG_ANY,
                match=parser.OFPMatch(),
            )
        )


class TwinRestController(ControllerBase):
    """Northbound REST API (JSON)."""

    def __init__(self, req: Any, link: Any, data: dict[str, Any], **config: Any) -> None:
        super().__init__(req, link, data, **config)
        self.app: TwinController = data[APP_KEY]

    @route("twin", "/stats/ports", methods=["GET"])
    def get_ports(self, req: Any, **_: Any) -> Response:
        """Latest per-port records for every datapath."""
        rows = [r for ports in self.app.port_stats.values() for r in ports.values()]
        return _json({"ports": rows})

    @route("twin", "/stats/flows", methods=["GET"])
    def get_flows(self, req: Any, **_: Any) -> Response:
        """Latest flow records for every datapath."""
        return _json({"flows": [r for rows in self.app.flow_stats.values() for r in rows]})

    @route("twin", "/topology", methods=["GET"])
    def get_topology(self, req: Any, **_: Any) -> Response:
        """Connected datapaths with their ports, and learned host (MAC) locations."""
        switches = [
            {
                "dpid": dpid_str(dpid),
                "ports": [
                    {"port_no": no, **info}
                    for no, info in sorted(self.app.port_names.get(dpid, {}).items())
                ],
            }
            for dpid in sorted(self.app.datapaths)
        ]
        hosts = [
            {"mac": mac, "dpid": dpid_str(dpid), "port": port}
            for dpid, table in sorted(self.app.mac_to_port.items())
            for mac, port in sorted(table.items())
        ]
        return _json({"switches": switches, "hosts": hosts})

    @route("twin", "/flows", methods=["POST"])
    def post_flow(self, req: Any, **_: Any) -> Response:
        """Install a flow described by the JSON body."""
        return self._install(req, parse_flow_request)

    @route("twin", "/qos/queue", methods=["POST"])
    def post_qos(self, req: Any, **_: Any) -> Response:
        """Install a QoS (set_queue + output) flow described by the JSON body."""
        return self._install(req, parse_qos_request)

    @route("twin", "/flows/{flow_id}", methods=["DELETE"])
    def delete_flow(self, req: Any, flow_id: str, **_: Any) -> Response:
        """Remove a flow previously installed through this API."""
        if flow_id not in self.app.installed:
            return _json({"error": f"unknown flow_id {flow_id!r}"}, HTTP_NOT_FOUND)
        self.app.remove(flow_id)
        return _json({"deleted": flow_id})

    def _install(self, req: Any, parse: Any) -> Response:
        try:
            spec = parse(json.loads(req.body or b"{}"))
        except (ValueError, TypeError) as exc:
            return _json({"error": str(exc)}, HTTP_BAD_REQUEST)
        if spec.flow_id in self.app.installed:
            return _json({"error": f"flow_id {spec.flow_id!r} already installed"}, HTTP_CONFLICT)
        if spec.dpid not in self.app.datapaths:
            return _json({"error": f"unknown dpid {dpid_str(spec.dpid)}"}, HTTP_NOT_FOUND)
        self.app.install(spec)
        return _json({"installed": spec.flow_id, "cookie": spec.cookie}, 201)
