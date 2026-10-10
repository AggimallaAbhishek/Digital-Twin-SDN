"""P4.2 anomaly detector evaluation on the P2.3 dataset.

    uv run python -m experiments.analysis.anomaly_eval          # config/anomaly.yaml

Builds whole-network 30 s windows (ml/anomaly/features.py) for every run, fits Isolation Forest
on the train split's normal windows only (normal runs + windows before a disruption), picks the
alert threshold with the best F1 on val, and reports on test: window precision/recall/F1
(overall and per scenario), detection delay after each disruption, and what the ap_failure
alerts name. Writes models/anomaly/v1/metrics.json (RULEBOOK E-4, E-6).
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from experiments.batch import load_scenario
from experiments.dataset import disruption
from experiments.shell import git_commit
from ml.anomaly.features import Window, windows
from ml.anomaly.metrics import best_threshold, detection_delays, precision_recall_f1
from ml.anomaly.training import fit_from_runs, load_runs, normal_windows
from twin.state.builder import load_campus_aps

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "models" / "anomaly" / "v1"


def _scores(labels: list[bool], flags: list[bool]) -> dict[str, float]:
    p, r, f1 = precision_recall_f1(labels, flags)
    return {"precision": round(p, 3), "recall": round(r, 3), "f1": round(f1, 3)}


def main() -> int:
    """Fit, tune, report; 0 always (the report is the deliverable)."""
    config: dict[str, Any] = yaml.safe_load((ROOT / "config" / "anomaly.yaml").read_text())
    campus = yaml.safe_load((ROOT / "config" / "campus_v1.yaml").read_text())
    aps = sorted(load_campus_aps(campus).positions)
    runs = load_runs(ROOT / config["dataset"])  # shared with the live monitor (training.py)
    # detection delay counts from the scripted event, not the first stress-labelled sample
    scripted = {r.run_id: disruption(load_scenario(r.scenario_id)) for r in runs}
    onsets = {run_id: d.at_s if d else None for run_id, d in scripted.items()}
    all_windows = [w for r in runs for w in windows(r, aps, config["step_s"], config["window_s"])]
    split: dict[str, list[Window]] = defaultdict(list)
    for w in all_windows:
        split[w.split].append(w)

    step_s, window_s = config["step_s"], config["window_s"]
    normal = normal_windows(runs, aps, step_s, window_s)
    detector = fit_from_runs(
        runs,
        aps,
        step_s=step_s,
        window_s=window_s,
        seed=config["seed"],
        n_estimators=config["n_estimators"],
    )
    val_scores = detector.score([w.features for w in split["val"]])
    threshold = best_threshold(val_scores, [w.stress for w in split["val"]])

    test = split["test"]
    flags = [s >= threshold for s in detector.score([w.features for w in test])]
    val_flags = [s >= threshold for s in val_scores]
    report: dict[str, Any] = {"threshold": threshold, "train_normal_windows": len(normal)}
    for name, ws, f in (("val", split["val"], val_flags), ("test", test, flags)):
        report[name] = _scores([w.stress for w in ws], f) | {"windows": len(ws)}
    by_scenario = {}
    for scenario in sorted({w.scenario_id for w in test}):
        idx = [i for i, w in enumerate(test) if w.scenario_id == scenario]
        picked = [flags[i] for i in idx]
        by_scenario[scenario] = _scores([test[i].stress for i in idx], picked) | {
            "alerts": sum(picked)
        }
    report["test_by_scenario"] = by_scenario
    report["test_detection"] = detection_delays(
        [(w.run_id, onsets[w.run_id], w.t_end_s, f) for w, f in zip(test, flags, strict=True)]
    )
    ap_fail = [
        (w, f)
        for w, f in zip(test, flags, strict=True)
        if w.scenario_id == "ap_failure" and f and w.stress
    ]
    report["ap_failure_alert_entities"] = dict(
        Counter(detector.entity(w.features) for w, _ in ap_fail)
    )
    report |= {
        "created": datetime.now(UTC).isoformat(timespec="seconds"),
        "git_commit": git_commit(),
        "config": config,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "metrics.json").write_text(json.dumps(report, indent=1))
    print(f"ANOMALY_THRESHOLD {threshold:.4f} (train normal windows: {len(normal)})")
    for name in ("val", "test"):
        print(f"ANOMALY_{name.upper()} {report[name]}")
    for scenario, m in by_scenario.items():
        print(f"ANOMALY_TEST {scenario}: {m}")
    for run, d in report["test_detection"].items():
        print(f"ANOMALY_DETECT {run}: {d}")
    print(f"ANOMALY_AP_FAILURE_ENTITIES {report['ap_failure_alert_entities']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
