"""P3.5 twin validation (twin/validation/validate.py): predicted vs measured, per flow."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml

from common.schemas import ACTION_ADAPTER
from twin.radio import RadioParams
from twin.sim.analytical import load_sim_params
from twin.state.builder import CampusAPs
from twin.validation.validate import (
    Applied,
    Case,
    RunTelemetry,
    TwinModel,
    action_cases,
    mape,
    steady_cases,
    summary,
)

ROOT = Path(__file__).resolve().parents[2]
T0 = datetime(2026, 10, 8, 10, 0, tzinfo=UTC)
RADIO = RadioParams(4.6, 30.0, 60.0, -16.0, 4.0)
PARAMS = load_sim_params(yaml.safe_load((ROOT / "config" / "sim.yaml").read_text()))
CAMPUS = CampusAPs({"ap1": (0.0, 0.0), "ap2": (40.0, 0.0)}, {"ap1": 1, "ap2": 6}, {})
MODEL = TwinModel(CAMPUS, RADIO, PARAMS)


def _run(video_mbps: float, measured_after: float, seconds: int = 60) -> RunTelemetry:
    """Two stations on ap1, each with a video; from t = 30 s it measures `measured_after`."""
    ap_rows, sta_rows, kpi_rows = [], [], []
    for t in range(seconds):
        ts = T0 + timedelta(seconds=t)
        for ap, channel in (("ap1", 1), ("ap2", 6)):
            ap_rows.append(_row(ts, t, ap=ap, channel=channel, channel_util=0.2))
        for sta in ("sta1", "sta2"):
            sta_rows.append(_row(ts, t, sta=sta, ap="ap1", x=1.0, y=0.0))
            thr = video_mbps if t < 30 else measured_after
            kpi_rows.append(
                _row(
                    ts,
                    t,
                    flow_id=f"{sta}-video",
                    app_class="video",
                    throughput_mbps=thr,
                    latency_ms=2.0,
                    loss_pct=0.0,
                )
            )
    return RunTelemetry("r1", "test", "test", ap_rows, sta_rows, kpi_rows)


def _row(ts: datetime, t: int, **fields: Any) -> dict[str, Any]:
    return {"ts": ts, "t_s": float(t), **fields}


def test_a_steady_window_compares_the_prediction_with_the_measured_median() -> None:
    cases = steady_cases(_run(0.4, 0.4), MODEL, times=[20], horizon_s=20)
    assert [(c.flow_id, c.kind) for c in cases] == [
        ("sta1-video", "steady"),
        ("sta2-video", "steady"),
    ]
    # the twin sees each video send 0.4 Mbit/s (measured, no loss) and predicts 0.4
    assert all(c.predicted_mbps == pytest.approx(0.4) for c in cases)
    assert all(c.measured_mbps == pytest.approx(0.4) for c in cases)
    assert mape(cases) == pytest.approx(0.0)


def test_a_window_without_telemetry_gives_no_cases() -> None:
    assert steady_cases(_run(0.4, 0.4), MODEL, times=[0], horizon_s=20) == []


def test_an_action_case_predicts_from_the_state_before_and_measures_after_settling() -> None:
    action = ACTION_ADAPTER.validate_python(
        {
            "action_id": "act_v_1",
            "type": "set_ap_channel",
            "source": "operator",
            "reason": "validation",
            "created_at": T0,
            "params": {"ap": "ap2", "channel": 1},
        }
    )
    # ap2 joins ap1's channel 40 m away: ap1 capped at 4.6 / 1.667 = 2.76 Mbit/s, which still
    # fits 2 x 0.4; measured after the change: 0.3 each
    cases = action_cases(_run(0.4, 0.3), Applied(30, action), MODEL, settle_s=5, measure_s=20)
    assert {c.kind for c in cases} == {"set_ap_channel"}
    assert all(c.predicted_mbps == pytest.approx(0.4) for c in cases)
    assert all(c.measured_mbps == pytest.approx(0.3) for c in cases)
    assert mape(cases) == pytest.approx(1 / 3)  # |0.4 - 0.3| / 0.3
    # at t = 0 there is no telemetry before the action yet: no case
    assert action_cases(_run(0.4, 0.3), Applied(0, action), MODEL, settle_s=5, measure_s=20) == []


def _case(kind: str, predicted: float, measured: float, app: str = "video") -> Case:
    return Case("r", "s", "test", kind, 0.0, "sta1-video", app, predicted, measured)


def test_mape_skips_flows_that_measured_almost_nothing() -> None:
    cases = [_case("steady", 1.0, 1.0), _case("steady", 1.0, 0.01)]  # a dead flow: no ratio
    assert mape(cases) == pytest.approx(0.0)
    assert mape([]) is None


def test_summary_groups_by_kind_and_app_class() -> None:
    cases = [
        _case("steady", 1.1, 1.0),
        _case("steady", 0.9, 1.0),
        _case("set_ap_channel", 1.5, 1.0),
        _case("steady", 0.5, 0.5, app="bulk"),
    ]
    table = summary(cases)
    assert table["all"] == {"mape": pytest.approx(0.175), "n": 4}  # (0.1 + 0.1 + 0.5 + 0) / 4
    assert table["steady/video"] == {"mape": pytest.approx(0.1), "n": 2}
    assert table["set_ap_channel/video"] == {"mape": pytest.approx(0.5), "n": 1}
    assert table["steady/bulk"] == {"mape": pytest.approx(0.0), "n": 1}
