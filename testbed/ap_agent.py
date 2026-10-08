"""P1.3 AP agent: REST control of AP channel / tx power and station association.

OpenFlow cannot touch the radio, so this small HTTP server runs inside the topology process and
drives Mininet-WiFi directly (PROJECT_PLAN §5 design note). Runs on the testbed VM (Python 3.8).

    GET  /aps                        every AP: bssid, channel, tx power, position, clients
    GET  /aps/{ap}/stats             APStats fields (common/schemas.py) for one AP
    GET  /stations                   StationStats fields for every station
    GET  /kpi                        latest KPIRecord fields per traffic flow (P1.5 probe)
    POST /aps/{ap}/channel           {"channel": 6}     hostapd channel switch, clients follow
    POST /aps/{ap}/txpower           {"dbm": 12}        rounded to whole dBm
    POST /stations/{sta}/associate   {"ap": "ap2"}      steer the station to that AP

Errors: 422 invalid body or out-of-bounds value, 404 unknown AP/station/path, 500 the radio did
not apply the change. Records carry `ts`; the collector adds scenario_id and run_id (P2.1).
Validation and parsing live in testbed/ap_logic.py (unit-tested on the Mac).

Safety: the agent applies what it is told. Only the action executor (P4.4) may call the POST
endpoints, and only for actions with an accepted twin Verdict (RULEBOOK rule 1).
"""

from __future__ import annotations

import json
import re
import threading
import time
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Dict

import yaml
from mininet.log import info

from testbed import ap_logic
from testbed.interference import load_radio_model
from testbed.wifi_utils import steer

DEFAULT_HOST = "0.0.0.0"  # noqa: S104 - reachable from the Mac over the VM's host-only network
DEFAULT_PORT = 8081  # Ryu REST is on 8080
APPLY_TIMEOUT_S = 3.0  # CSA takes CSA_BEACONS x 100 ms beacon interval; tx power is immediate
APPLY_POLL_S = 0.2
MAX_BODY_BYTES = 4096
CAMPUS_CONFIG = Path(__file__).resolve().parents[1] / "config" / "campus_v1.yaml"

Record = Dict[str, Any]  # runtime alias: typing.Dict for Python 3.8


class NotFoundError(LookupError):
    """Unknown AP, station or path (404)."""


class RadioError(RuntimeError):
    """The radio did not apply a change (500)."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class ApAgent:
    """Reads and changes the campus radios. Every Mininet call holds `lock`.

    Mininet node shells are not thread-safe, so anything else in the process that calls
    node.cmd() while the agent is serving (the scenario runner, P1.6) must hold `lock` too.
    """

    def __init__(self, aps: dict[str, Any], stations: dict[str, Any], capacity_mbps: float) -> None:
        self.lock = threading.RLock()
        self._aps = aps
        self._stations = stations
        self._ap_by_bssid = {ap.wintfs[0].mac: name for name, ap in aps.items()}
        self._baseline: dict[str, tuple[float, ap_logic.Counters]] = {}
        # Latest KPI records; set to TrafficProbe.latest when traffic runs (testbed/traffic, P1.5)
        self.kpi_source: Callable[[], list[Record]] = list
        # Current downlink capacity per AP (deviation #8): the nominal radio_model capacity unless
        # the scenario runner's interference controller sets a cap (set_capacity). Guarded by lock.
        self._nominal_mbps = capacity_mbps
        self._capacity_mbps: dict[str, float] = {}

    # ------------------------------------------------------------------ reads
    def list_aps(self) -> Record:
        with self.lock:
            aps = []
            for name, ap in sorted(self._aps.items()):
                iw = self.iw_info(ap)
                aps.append(
                    {
                        "ap": name,
                        "bssid": iw.bssid,
                        "ssid": ap.wintfs[0].ssid,
                        "channel": iw.channel,
                        "tx_power_dbm": iw.tx_power_dbm,
                        "x": float(ap.position[0]),
                        "y": float(ap.position[1]),
                        "n_clients": len(self._station_dump(ap)),
                    }
                )
            return {"ts": _now(), "aps": aps}

    def ap_stats(self, name: str) -> Record:
        ap = self._ap(name)
        with self.lock:
            iw = self.iw_info(ap)
            clients = self._station_dump(ap)
            now = time.monotonic()
            prev_t, prev = self._baseline.get(name, (now, None))
            self._baseline[name] = (now, ap_logic.byte_counters(clients))
            capacity = self._capacity_mbps.get(name, self._nominal_mbps)
        return {
            "ts": _now(),
            "ap": name,
            "channel": iw.channel,
            "n_clients": len(clients),
            "channel_util": ap_logic.capacity_util(prev, clients, now - prev_t, capacity),
            "tx_power_dbm": iw.tx_power_dbm,
            "retries": sum(c.tx_retries for c in clients),
            "noise_dbm": ap_logic.NOISE_FLOOR_DBM,
        }

    def stations(self) -> Record:
        with self.lock:
            # downlink bitrate per station, as seen by the AP it is on
            downlink = {
                c.mac: c.tx_bitrate_mbps
                for ap in self._aps.values()
                for c in self._station_dump(ap)
            }
            records = []
            for name, sta in sorted(self._stations.items(), key=lambda kv: _num(kv[0])):
                link = ap_logic.parse_link(sta.cmd(f"iw dev {sta.wintfs[0].name} link"))
                records.append(
                    {
                        "sta": name,
                        "ap": self._ap_by_bssid.get(link.bssid or ""),
                        "rssi_dbm": link.signal_dbm,
                        "snr_db": ap_logic.snr_db(link.signal_dbm),
                        "tx_bitrate_mbps": link.tx_bitrate_mbps,
                        "rx_bitrate_mbps": downlink.get(sta.wintfs[0].mac),
                        "x": float(sta.position[0]),
                        "y": float(sta.position[1]),
                    }
                )
        return {"ts": _now(), "stations": records}

    def kpi(self) -> Record:
        """Latest KPI record of every traffic flow (empty when no TrafficProbe is attached)."""
        return {"ts": _now(), "kpis": self.kpi_source()}

    def set_capacity(self, name: str, cap_mbps: float | None) -> None:
        """Record an AP's co-channel cap (None: back to nominal) for its channel_util."""
        with self.lock:
            if cap_mbps is None:
                self._capacity_mbps.pop(name, None)
            else:
                self._capacity_mbps[name] = cap_mbps

    # ------------------------------------------------------------------ writes
    def set_channel(self, name: str, body: Any) -> Record:
        ap = self._ap(name)
        channel = ap_logic.parse_channel_request(body)
        intf = ap.wintfs[0]
        with self.lock:
            if self.iw_info(ap).channel != channel:
                out = ap.cmd(ap_logic.chan_switch_cmd(intf.name, channel))
                if "OK" not in out:
                    raise RadioError(f"hostapd refused the channel switch: {out.strip()!r}")
                self._wait_for(lambda: self.iw_info(ap).channel == channel, "channel", channel)
                intf.channel = channel  # keep Mininet-WiFi's view in sync
        return {"ts": _now(), "ap": name, "channel": channel}

    def set_txpower(self, name: str, body: Any) -> Record:
        ap = self._ap(name)
        dbm = ap_logic.parse_txpower_request(body)
        with self.lock:
            ap.setTxPower(dbm)  # also updates wmediumd's interference model
            self._wait_for(lambda: self.iw_info(ap).tx_power_dbm == dbm, "tx power", dbm)
        return {"ts": _now(), "ap": name, "tx_power_dbm": float(dbm)}

    def associate(self, sta_name: str, body: Any) -> Record:
        sta = self._station(sta_name)
        ap_name = ap_logic.parse_associate_request(body)
        ap = self._ap(ap_name)
        if not steer(sta, ap, lock=self.lock):  # holds the lock per command, not for ~4 s
            raise RadioError(f"{sta_name} did not associate with {ap_name}")
        return {"ts": _now(), "sta": sta_name, "ap": ap_name}

    # ------------------------------------------------------------------ helpers
    def _ap(self, name: str) -> Any:
        if name not in self._aps:
            raise NotFoundError(f"unknown AP {name!r}")
        return self._aps[name]

    def _station(self, name: str) -> Any:
        if name not in self._stations:
            raise NotFoundError(f"unknown station {name!r}")
        return self._stations[name]

    @staticmethod
    def iw_info(ap: Any) -> ap_logic.IwInfo:
        """Parsed `iw dev <ap> info` (channel, tx power, bssid); caller holds `lock`."""
        return ap_logic.parse_iw_info(ap.cmd(f"iw dev {ap.wintfs[0].name} info"))

    @staticmethod
    def _station_dump(ap: Any) -> list[ap_logic.StationEntry]:
        return ap_logic.parse_station_dump(ap.cmd(f"iw dev {ap.wintfs[0].name} station dump"))

    @staticmethod
    def _wait_for(applied: Callable[[], bool], what: str, value: object) -> None:
        deadline = time.monotonic() + APPLY_TIMEOUT_S
        while not applied():
            if time.monotonic() > deadline:
                raise RadioError(f"{what} {value} not applied within {APPLY_TIMEOUT_S} s")
            time.sleep(APPLY_POLL_S)


def _num(name: str) -> int:
    """sta2 sorts before sta10."""
    return int(re.sub(r"\D", "", name) or 0)


_ROUTES: list[tuple[str, re.Pattern[str], str]] = [
    ("GET", re.compile(r"^/aps$"), "list_aps"),
    ("GET", re.compile(r"^/aps/([^/]+)/stats$"), "ap_stats"),
    ("GET", re.compile(r"^/stations$"), "stations"),
    ("GET", re.compile(r"^/kpi$"), "kpi"),
    ("POST", re.compile(r"^/aps/([^/]+)/channel$"), "set_channel"),
    ("POST", re.compile(r"^/aps/([^/]+)/txpower$"), "set_txpower"),
    ("POST", re.compile(r"^/stations/([^/]+)/associate$"), "associate"),
]


class _Handler(BaseHTTPRequestHandler):
    agent: ApAgent  # set on the subclass made by make_server()

    def do_GET(self) -> None:
        self._dispatch("GET")

    def do_POST(self) -> None:
        self._dispatch("POST")

    def _dispatch(self, method: str) -> None:
        try:
            status, payload = HTTPStatus.OK, self._route(method)
        except NotFoundError as exc:
            status, payload = HTTPStatus.NOT_FOUND, {"error": str(exc)}
        except ValueError as exc:  # includes invalid JSON
            status, payload = HTTPStatus.UNPROCESSABLE_ENTITY, {"error": str(exc)}
        except RadioError as exc:
            status, payload = HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)}
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _route(self, method: str) -> Record:
        path = self.path.split("?", 1)[0]
        for verb, pattern, handler in _ROUTES:
            match = pattern.match(path)
            if verb == method and match:
                args: list[Any] = list(match.groups())
                if method == "POST":
                    args.append(self._json_body())
                result: Record = getattr(self.agent, handler)(*args)
                return result
        raise NotFoundError(f"no route {method} {path}")

    def _json_body(self) -> Any:
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY_BYTES:
            raise ValueError(f"body larger than {MAX_BODY_BYTES} bytes")
        try:
            return json.loads(self.rfile.read(length) or b"null")
        except ValueError as exc:
            raise ValueError(f"body is not valid JSON: {exc}") from exc

    def log_message(self, format: str, *args: Any) -> None:
        info(f"AP_AGENT {self.address_string()} {format % args}\n")


def make_server(
    agent: ApAgent, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT
) -> ThreadingHTTPServer:
    """An HTTP server for `agent` (not yet serving)."""
    handler = type("ApAgentHandler", (_Handler,), {"agent": agent})
    server = ThreadingHTTPServer((host, port), handler)
    server.daemon_threads = True
    return server


def start_in_background(
    agent: ApAgent, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT
) -> ThreadingHTTPServer:
    """Serve `agent` from a daemon thread; call .shutdown() on the result to stop."""
    server = make_server(agent, host, port)
    threading.Thread(target=server.serve_forever, name="ap-agent", daemon=True).start()
    info(f"AP_AGENT listening on http://{host}:{port}\n")
    return server


def from_campus(campus: Any, campus_config: Path = CAMPUS_CONFIG) -> ApAgent:
    """An agent for a started campus (testbed/topologies/campus_v1.py)."""
    stations = {sta.name: sta for sta, _ in campus.stations}
    model = load_radio_model(yaml.safe_load(campus_config.read_text()))
    return ApAgent(dict(campus.aps), stations, model.ap_capacity_mbps)
