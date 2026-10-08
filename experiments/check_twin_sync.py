"""P3.1 live check: the twin's state matches what the AP agent reports, with lag < 3 s.

Run while a scenario plays on the VM and the collector writes it to InfluxDB:

    uv run python -m experiments.check_twin_sync --run-id smoke-sync --duration-s 60

Every `PERIOD_S` it rebuilds the TwinState (twin/state/sync.py) and fetches the agent's own
/stations and /aps, then compares each station's AP and each AP's channel. Telemetry is up to a
second old, so a station caught mid-re-association can differ briefly: the check passes when at
least MIN_AGREEMENT of the comparisons agree and every refresh's lag is below config max_lag_s.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import yaml

from common.influx import InfluxConnection
from telemetry.collector.collector import http_fetch, load_collector_config
from twin.state.builder import lag_s, load_campus_aps
from twin.state.sync import TwinSync, load_sync_config

ROOT = Path(__file__).resolve().parents[1]
PERIOD_S = 2.0
MIN_AGREEMENT = 0.95


def main(argv: list[str] | None = None) -> int:
    """CLI entry point; 0 if the twin matched the agent and stayed fresh."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--duration-s", type=float, default=60.0)
    args = parser.parse_args(argv)

    config = load_sync_config(yaml.safe_load((ROOT / "config/twin.yaml").read_text()))
    campus = load_campus_aps(yaml.safe_load((ROOT / "config/campus_v1.yaml").read_text()))
    sync = TwinSync(InfluxConnection.from_env(), campus, args.run_id, config)
    agent = load_collector_config()
    base = f"http://{agent.vm_host}:{agent.agent_port}"
    compared = agreed = 0
    lags: list[float] = []
    end = time.monotonic() + args.duration_s
    while time.monotonic() < end:
        state = sync.refresh()
        lags.append(lag_s(state, datetime.now(UTC)))  # after the queries: they count too
        stations = {s["sta"]: s["ap"] for s in http_fetch(f"{base}/stations", 2.0)["stations"]}
        channels = {a["ap"]: a["channel"] for a in http_fetch(f"{base}/aps", 2.0)["aps"]}
        pairs: list[tuple[object, object]] = [
            (state.stations[s].ap if s in state.stations else "?", ap) for s, ap in stations.items()
        ]
        for name, channel in channels.items():  # a disabled AP has no channel: compare "down"
            ap = state.aps[name]
            pairs.append((ap.channel if ap.up else "down", channel if channel else "down"))
        compared += len(pairs)
        agreed += sum(twin == live for twin, live in pairs)
        time.sleep(PERIOD_S)
    agreement = agreed / compared if compared else 0.0
    ok = agreement >= MIN_AGREEMENT and max(lags, default=99.0) < config.max_lag_s
    print(
        f"TWIN_SYNC_RESULT refreshes={len(lags)} agreement={agreement:.1%} "
        f"max_lag={max(lags, default=0.0):.2f}s -> {'PASS' if ok else 'FAIL'}"
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
