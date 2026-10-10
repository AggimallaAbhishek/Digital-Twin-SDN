"""P5.6 replay eval (experiments/analysis/rca_eval.py): recorded runs through the real API."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from experiments.analysis.rca_eval import EXPECTED, Replay, backend_for, score

T0 = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)


def _replay(seconds: int = 60, ap2_down_at: int = 40) -> Replay:
    """ap1 and ap2 report every second until ap2 goes down; one station, one flow."""
    ap, sta, kpi = [], [], []
    for t in range(seconds):
        ts = T0 + timedelta(seconds=t)
        for name, channel in (("ap1", "1"), ("ap2", "6")):
            if name == "ap2" and t >= ap2_down_at:
                continue
            ap.append(
                {"ts": ts, "ap": name, "channel": channel, "channel_util": 0.5, "n_clients": 1}
                | {"tx_power_dbm": 14.0, "retries": 0.0, "noise_dbm": -92.0}
            )
        sta.append({"ts": ts, "sta": "sta1", "ap": "ap1", "x": 20.0, "y": 50.0})
        kpi.append(
            {"ts": ts, "flow_id": "sta1-video", "app_class": "video", "throughput_mbps": 0.6}
            | {"latency_ms": 12.0, "jitter_ms": 1.0, "loss_pct": 0.0}
        )
    return Replay("ap_failure-s44", "ap_failure", 40.0, T0, ap, sta, kpi)


def test_rows_are_the_window_before_the_replay_clock() -> None:
    ap, sta, kpi = _replay().rows(T0 + timedelta(seconds=10), T0 + timedelta(seconds=20))
    assert len(sta) == len(kpi) == 10
    assert min(r["ts"] for r in ap) == T0 + timedelta(seconds=10)
    assert max(r["ts"] for r in ap) == T0 + timedelta(seconds=19)


def test_the_api_serves_the_replay_as_of_its_clock(tmp_path: Path) -> None:
    replay = _replay()
    clock = [T0 + timedelta(seconds=50)]
    backend = backend_for(replay, lambda: clock[0], tmp_path / "ledger.db")
    aps = {a["name"]: a["up"] for a in backend.topology()["aps"]}
    assert (aps["ap1"], aps["ap2"]) == (True, False)  # ap2 silent for 10 s > ap_stale_s
    points = backend.metrics("ap1", "channel_util", 5)
    assert len(points) == 5
    assert points[-1]["ts"] == (T0 + timedelta(seconds=49)).isoformat()
    assert backend.metrics("ap2", "channel_util", 5) == []
    clock[0] = T0 + timedelta(seconds=30)  # the replay is rewound: ap2 is up again
    assert {a["name"]: a["up"] for a in backend.topology()["aps"]}["ap2"] is True


def _report(category: str, entity: str) -> dict[str, Any]:
    return {"likely_causes": [{"category": category, "entity": entity}, {"category": "other"}]}


def test_a_diagnosis_is_correct_when_its_top_cause_names_the_fault_and_its_ap() -> None:
    assert EXPECTED["ap_failure"] == ("ap_down", "ap2")
    assert score("ap_failure", _report("ap_down", "ap2")) is True
    assert score("ap_failure", _report("ap_down", "ap1")) is False
    assert score("ap_failure", _report("congestion", "ap2")) is False
    assert score("cochannel_interference", _report("cochannel_interference", "ap3")) is True
