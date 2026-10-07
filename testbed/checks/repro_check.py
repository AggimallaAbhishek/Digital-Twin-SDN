#!/usr/bin/env python3
"""P1.6 reproducibility check: same scenario + seed, N runs -> per-class mean throughput within ±5%.

Run on the VM after testbed/run_scenario.py (make scenario-repro-vm):

    python3 -m testbed.checks.repro_check ~/p02/runs/flash-1 ~/p02/runs/flash-2 ~/p02/runs/flash-3
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from testbed.scenario_plan import max_deviation_pct

MAX_DEVIATION_PCT = 5.0  # PHASE_PLAN P1.6: "same seed x3 gives throughput within ±5%"
MIN_RUNS = 2


def main(argv: list[str]) -> int:
    """Compare the summary.json of every run directory in `argv`; return an exit code."""
    summaries = [json.loads((Path(d) / "summary.json").read_text()) for d in argv]
    if len(summaries) < MIN_RUNS or len({(s["scenario_id"], s["seed"]) for s in summaries}) != 1:
        print("REPRO_RESULT needs >= 2 runs of the same scenario and seed -> FAIL")
        return 1
    classes = set.intersection(*(set(s["by_class"]) for s in summaries))
    worst = 0.0
    for app_class in sorted(classes):
        values = [s["by_class"][app_class]["throughput_mbps"] for s in summaries]
        deviation = max_deviation_pct(values)
        worst = max(worst, deviation)
        print(f"REPRO {app_class}: throughput {values} Mbit/s, max deviation {deviation:.2f}%")
    ok = bool(classes) and worst <= MAX_DEVIATION_PCT
    runs = [s["run_id"] for s in summaries]
    print(f"REPRO_RESULT runs={runs} worst={worst:.2f}% -> {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
