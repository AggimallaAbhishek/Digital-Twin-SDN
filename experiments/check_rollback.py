"""P4.4 live check: a deliberately bad action is rolled back (PHASE_PLAN P4.4 Done when).

Run while the `normal` scenario plays on the VM and the collector writes it to InfluxDB:

    uv run python -m experiments.check_rollback --run-id rollback-check

The bad action moves ap2 onto channel 1, next to ap1 (40 m) and ap4 (30 m): the testbed's
interference model then cuts ap1, ap2 and ap4's capacity. The twin would reject it, so this
harness records an accepted verdict for it **on purpose**, standing in for a twin miss: it is
what rollback exists for (PROJECT_PLAN §8, "bad actions that slipped past the twin"). Everything
after that is the real executor: approval, the AP agent actuator, the 30 s watch on live
InfluxDB KPIs, and the rollback. Passes if the action is rolled back and ap2 is on channel 6.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from api.wiring import agent_url, build_executor, load_yaml
from common.influx import InfluxConnection
from common.schemas import ACTION_ADAPTER, KPIValues, Verdict
from controller.executor.executor import load_executor_config
from twin.state.model import TwinState

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "logs" / "rollback_check.db"  # gitignored
GRACE_S = 5  # past the watch, so the last KPI records are in InfluxDB
PLANNED_CHANNEL = 6  # ap2's channel in config/campus_v1.yaml


def main(argv: list[str] | None = None) -> int:
    """CLI entry point; 0 if the bad action was rolled back and ap2 is back on channel 6."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args(argv)

    config = load_executor_config(load_yaml("executor.yaml"))
    base = agent_url()
    LEDGER.unlink(missing_ok=True)
    executor = build_executor(InfluxConnection.from_env(), args.run_id, LEDGER)
    now = datetime.now(UTC)
    action = ACTION_ADAPTER.validate_python(
        {
            "action_id": f"act_{now:%Y%m%d_%H%M%S}_rollback_check",
            "type": "set_ap_channel",
            "source": "operator",
            "reason": "P4.4 check: deliberately bad (co-channel with ap1 and ap4)",
            "created_at": now,
            "params": {"ap": "ap2", "channel": 1},
        }
    )
    placeholder = KPIValues(throughput_mbps=0, latency_ms=0, loss_pct=0, jain=1)
    injected = Verdict(  # the harness's stand-in for a twin miss (see the module docstring)
        action_id=action.action_id,
        accepted=True,
        predicted=placeholder,
        baseline=placeholder,
        impact="high",
        needs_approval=True,
        sim_mode="analytical",
        sim_time_ms=0,
    )
    executor.record([action], [injected])
    executor.approve(action.action_id, by="rollback-check")
    executor.apply([action.action_id], TwinState(now, {}, {}))
    print(
        f"ROLLBACK_CHECK applied {action.action_id} (ap2 -> channel 1), "
        f"watching {config.watch_s:g} s"
    )
    time.sleep(config.watch_s + GRACE_S)
    outcome = executor.check()
    [record] = executor.history()
    with urllib.request.urlopen(f"{base}/aps", timeout=10) as response:  # noqa: S310 - http config
        channel = {a["ap"]: a["channel"] for a in json.loads(response.read())["aps"]}["ap2"]
    ok = outcome == [(action.action_id, "rolled_back")] and channel == PLANNED_CHANNEL
    print(f"ROLLBACK_CHECK outcome={outcome} note={record.note!r} ap2_channel={channel}")
    print(f"ROLLBACK_RESULT {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
