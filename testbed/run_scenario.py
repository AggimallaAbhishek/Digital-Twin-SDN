#!/usr/bin/env python3
"""P1.6 scenario runner: plays experiments/scenarios/<id>.yaml on the campus, unattended.

Runs ON THE VM via testbed/run_on_vm.sh (needs Ryu: RYU_APP=controller.apps.twin_controller):

    python3 -m testbed.run_scenario experiments/scenarios/lecture_flash_crowd.yaml \
        --run-id flash-1 --git-commit abc1234

Brings up campus_v1 with the AP agent (port 8081, reachable from the Mac for the collector,
P2.1) and the traffic probe (GET /kpi), then plays the scenario clock: crowd walks
(testbed/mobility), traffic starts (selectors resolved when the traffic starts) and radio events.
An interference controller re-reads the AP channels every second and applies the co-channel caps
of testbed/interference.py (deviation #7). Events are the *environment* changing, not control
actions, so they do not go through the twin; only the executor (P4.4) changes the network on
the system's behalf.

Artefacts in <LOG_DIR>/runs/<run_id>/: manifest.json (seed, commit, config hash; RULEBOOK rule
10), events.jsonl (scenario time of every event, cap change and re-association), kpi.jsonl
(every KPI record) and summary.json (per-class KPIs, scenario_plan.summarize_kpis).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict

import yaml
from mininet.log import info, setLogLevel

from testbed import ap_agent
from testbed.interference import ApRadio, RadioModel, capacity_caps, load_radio_model, tc_commands
from testbed.layout import CampusLayout, StationSpec, load_layout, place_stations
from testbed.mobility.crowd import Walk, nearest_ap, plan_crowd
from testbed.mobility.runner import CrowdRunner
from testbed.scenario_plan import (
    EventSpec,
    ScenarioSpec,
    Step,
    parse_scenario,
    resolve_selector,
    summarize_kpis,
    timeline,
    zones_at,
)
from testbed.topologies.campus_v1 import (
    DEFAULT_LAYOUT,
    Campus,
    build_campus,
    ping_matrix,
    start_campus,
)
from testbed.traffic.profiles import DEFAULT_CONFIG as TRAFFIC_CONFIG
from testbed.traffic.profiles import load_traffic_config_file
from testbed.traffic.runner import TrafficProbe
from testbed.wifi_utils import steer

INTERFERENCE_PERIOD_S = 1.0
Record = Dict[str, Any]  # runtime alias: typing.Dict for Python 3.8


class EventLog:
    """Appends {t_s, kind, ...} lines to events.jsonl, timed from the scenario start."""

    def __init__(self, path: Path, t0: float) -> None:
        self._path, self._t0, self._lock = path, t0, threading.Lock()

    def __call__(self, kind: str, **fields: Any) -> None:
        line = {"t_s": round(time.monotonic() - self._t0, 2), "kind": kind, **fields}
        with self._lock, self._path.open("a") as out:
            out.write(json.dumps(line) + "\n")
        info(f"SCENARIO_EVENT {json.dumps(line)}\n")


class Radios:
    """AP up/down state and the co-channel interference caps (testbed/interference.py)."""

    def __init__(
        self, campus: Campus, layout: CampusLayout, model: RadioModel, agent: ap_agent.ApAgent
    ) -> None:
        self._campus, self._layout, self._model, self._agent = campus, layout, model, agent
        self.down: set[str] = set()
        self._caps: dict[str, float | None] = {ap.name: None for ap in layout.aps}

    def apply_caps(self, log: EventLog) -> None:
        """Re-read every AP's channel and update the tc caps that changed."""
        radios = []
        with self._agent.lock:
            for spec in self._layout.aps:
                ap = self._campus.aps[spec.name]
                channel = self._agent.iw_info(ap).channel
                up = spec.name not in self.down and channel is not None
                radios.append(ApRadio(spec.name, spec.position, channel or 0, up))
        for name, cap in capacity_caps(radios, self._model).items():
            if cap != self._caps[name]:
                ap = self._campus.aps[name]
                with self._agent.lock:
                    for command in tc_commands(ap.wintfs[0].name, cap):
                        ap.cmd(command)
                self._caps[name] = cap
                log("interference_cap", ap=name, cap_mbps=cap)

    def run(self, stop: threading.Event, log: EventLog) -> None:
        """apply_caps() every INTERFERENCE_PERIOD_S until `stop`."""
        while not stop.is_set():
            self.apply_caps(log)
            stop.wait(INTERFERENCE_PERIOD_S)


@dataclass
class ScenarioRun:
    """One unattended run of a scenario on a started campus."""

    spec: ScenarioSpec
    layout: CampusLayout
    model: RadioModel
    campus: Campus
    agent: ap_agent.ApAgent
    probe: TrafficProbe
    walks: list[Walk]
    log: EventLog
    stop: threading.Event = field(init=False, default_factory=threading.Event)
    radios: Radios = field(init=False)
    stations: list[StationSpec] = field(init=False)
    nodes: dict[str, Any] = field(init=False)  # Any: Mininet-WiFi station nodes
    _threads: list[threading.Thread] = field(init=False, default_factory=list)

    def __post_init__(self) -> None:
        self.radios = Radios(self.campus, self.layout, self.model, self.agent)
        self.stations = place_stations(self.layout)
        self.nodes = {sta.name: sta for sta, _ in self.campus.stations}

    def play(self, t0: float) -> None:
        """Run the scenario clock from monotonic time `t0` to duration_s."""
        self._thread(lambda: self.radios.run(self.stop, self.log), "interference")
        if self.walks:
            crowd = CrowdRunner(self.walks, self.layout, self.campus, lock=self.agent.lock)
            self._thread(lambda: self._walk(crowd), "crowd")
        for step in timeline(self.spec):
            if self.stop.wait(max(0.0, t0 + step.t_s - time.monotonic())):
                return
            self._step(step)
        self.stop.wait(max(0.0, t0 + self.spec.duration_s - time.monotonic()))

    def close(self) -> None:
        """Stop the clock threads (traffic and the network are stopped by the caller)."""
        self.stop.set()
        for thread in self._threads:
            thread.join(timeout=10)

    def _walk(self, crowd: CrowdRunner) -> None:
        for arrival in crowd.run(self.stop):  # returns once every walker has re-associated
            self.log(
                "arrived",
                sta=arrival.sta,
                ap=arrival.ap,
                associated=arrival.associated,
                walk_end_s=arrival.t_s,
            )

    def _step(self, step: Step) -> None:
        zone_of = zones_at(self.layout, self.stations, self.walks, step.t_s)
        items: list[tuple[str, str, float | None]] = []
        seen: set[tuple[str, str]] = set()
        for traffic in step.traffic:
            for sta in resolve_selector(traffic.stations, zone_of):
                if (sta, traffic.profile) in seen or self.probe.has_flow(sta, traffic.profile):
                    self.log("traffic_duplicate", sta=sta, profile=traffic.profile)
                    continue
                seen.add((sta, traffic.profile))
                items.append((sta, traffic.profile, traffic.rate_mbps))
        if items:
            self.probe.start_flows(items)
            self.log("traffic_started", flows=[f"{s}-{p}" for s, p, _ in items])
        for event in step.events:
            self._event(event)

    def _event(self, event: EventSpec) -> None:
        if event.type == "force_channel":
            self.agent.set_channel(event.ap, {"channel": event.channel})
            self.log("force_channel", ap=event.ap, channel=event.channel)
        elif event.type == "ap_down":
            orphans = [s["sta"] for s in self.agent.stations()["stations"] if s["ap"] == event.ap]
            out = self._hostapd(event.ap, "disable")
            self.radios.down.add(event.ap)
            self.log("ap_down", ap=event.ap, hostapd=out, orphans=orphans)
            self._thread(lambda: self._rejoin(orphans), f"rejoin-{event.ap}")
        else:  # ap_up (parse_scenario allows only the three types)
            out = self._hostapd(event.ap, "enable")
            self.radios.down.discard(event.ap)
            self.log("ap_up", ap=event.ap, hostapd=out)

    def _hostapd(self, ap_name: str, verb: str) -> str:
        """`hostapd_cli disable|enable` on an AP (disable drops all its clients)."""
        ap = self.campus.aps[ap_name]
        with self.agent.lock:
            return str(ap.cmd(f"hostapd_cli -i {ap.wintfs[0].name} {verb}")).strip()

    def _rejoin(self, orphans: list[str]) -> None:
        """Orphaned stations join the nearest AP still up, all at once (like real clients)."""
        if self.stop.wait(self.model.orphan_rejoin_s):
            return
        threads = [
            threading.Thread(target=self._rejoin_one, args=(name,), daemon=True) for name in orphans
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

    def _rejoin_one(self, name: str) -> None:
        sta = self.nodes[name]
        position = (float(sta.position[0]), float(sta.position[1]))
        target = nearest_ap(self.layout, position, down=self.radios.down)
        ok = steer(sta, self.campus.aps[target], lock=self.agent.lock)  # lock held per command
        self.log("rejoined", sta=name, ap=target, associated=ok)

    def _thread(self, target: Callable[[], None], name: str) -> None:
        thread = threading.Thread(target=target, name=name, daemon=True)
        thread.start()
        self._threads.append(thread)


def config_hash(paths: list[Path]) -> str:
    """sha256 over the scenario, campus and traffic config files (first 16 hex digits)."""
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.name.encode() + b"\0" + path.read_bytes())
    return digest.hexdigest()[:16]


def write_summary(run_dir: Path, manifest: Record) -> Record:
    """Summarise kpi.jsonl into summary.json; return the summary."""
    kpi_log = run_dir / "kpi.jsonl"
    lines = kpi_log.read_text().splitlines() if kpi_log.exists() else []
    records = [json.loads(line) for line in lines]
    summary = {
        "scenario_id": manifest["scenario_id"],
        "run_id": manifest["run_id"],
        "seed": manifest["seed"],
        "flows": len({r["flow_id"] for r in records}),
        "records": len(records),
        "by_class": summarize_kpis(records),
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=1))
    return summary


def main(argv: list[str] | None = None) -> int:
    """CLI entry point; returns a process exit code."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("scenario", type=Path)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--git-commit", required=True, help="recorded in the manifest (rule 10)")
    parser.add_argument("--agent-port", type=int, default=ap_agent.DEFAULT_PORT)
    args = parser.parse_args(argv)

    spec = parse_scenario(yaml.safe_load(args.scenario.read_text()))
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_id = args.run_id or f"{spec.scenario_id}-{stamp}"
    run_dir = Path(os.environ.get("LOG_DIR", str(Path.home() / "p02"))) / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    layout = load_layout(DEFAULT_LAYOUT)
    model = load_radio_model(yaml.safe_load(DEFAULT_LAYOUT.read_text()))
    walks = plan_crowd(spec.groups, layout, place_stations(layout), seed=spec.seed)
    manifest = {
        "scenario_id": spec.scenario_id,
        "run_id": run_id,
        "seed": spec.seed,
        "duration_s": spec.duration_s,
        "git_commit": args.git_commit,
        "config_hash": config_hash([args.scenario, DEFAULT_LAYOUT, TRAFFIC_CONFIG]),
        "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "host": socket.gethostname(),
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=1))
    info(f"SCENARIO_START {json.dumps(manifest)}\n")

    campus = build_campus(layout, "127.0.0.1", 6653)
    server, probe, run = None, None, None
    try:
        assoc = start_campus(campus)
        hosts = [*campus.servers.values(), *(sta for sta, _ in campus.stations)]
        ping_matrix(hosts, count=1)  # warm-up: ARP + controller MAC learning
        agent = ap_agent.from_campus(campus)
        server = ap_agent.start_in_background(agent, port=args.agent_port)
        probe = TrafficProbe(
            campus, load_traffic_config_file(), run_dir, lock=agent.lock, seed=spec.seed
        )
        agent.kpi_source = probe.latest
        t0 = time.monotonic()
        log = EventLog(run_dir / "events.jsonl", t0)
        log("started", associated=sum(assoc.values()), stations=len(assoc))
        probe.start()
        run = ScenarioRun(spec, layout, model, campus, agent, probe, walks, log)
        run.play(t0)
        log("finished")
    finally:
        if run is not None:
            run.close()
        if probe is not None:
            probe.stop_all()
        if server is not None:
            server.shutdown()
        campus.net.stop()
    summary = write_summary(run_dir, manifest)
    ok = all(assoc.values()) and summary["records"] > 0
    print(
        f"SCENARIO_RESULT run_id={run_id} flows={summary['flows']} records={summary['records']} "
        f"-> {'PASS' if ok else 'FAIL'}"
    )
    return 0 if ok else 1


if __name__ == "__main__":
    setLogLevel("info")
    sys.exit(main())
