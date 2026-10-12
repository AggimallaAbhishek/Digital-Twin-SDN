"""P6.6 campaign analysis (experiments/analysis/campaign.py): per-run KPIs, mean ± 95% CI."""

from __future__ import annotations

from typing import Any

import pytest

from experiments.analysis.campaign import StressWindow, run_kpis, summarise

ONSET = 100.0
WINDOW = StressWindow(onset_s=ONSET, end_s=300.0)
Row = dict[str, Any]


def _run() -> tuple[list[Row], list[Row], list[Row]]:
    """ap1 is congested from the onset until 160 s, then calm; ap2 is calm throughout."""
    ap_rows, sta_rows, kpi_rows = [], [], []
    for t in range(300):
        ap_rows.append(
            {"t_s": float(t), "ap": "ap1", "channel_util": 0.95 if t < 160 else 0.5, "n_clients": 3}
        )
        ap_rows.append({"t_s": float(t), "ap": "ap2", "channel_util": 0.2, "n_clients": 1})
        sta_rows.append({"t_s": float(t), "sta": "sta1", "ap": "ap1"})
        sta_rows.append({"t_s": float(t), "sta": "sta2", "ap": "ap2"})
        for flow, app, thr, loss in (
            ("sta1-video", "video", 1.0, 2.0),
            ("sta2-web", "web", 5.0, 0.0),
        ):
            kpi_rows.append(
                {
                    "t_s": float(t),
                    "flow_id": flow,
                    "app_class": app,
                    "throughput_mbps": thr,
                    "latency_ms": 20.0,
                    "loss_pct": loss,
                }
            )
    return ap_rows, sta_rows, kpi_rows


def test_a_run_reports_recovery_and_the_affected_flows_kpis_after_the_onset() -> None:
    ap_rows, sta_rows, kpi_rows = _run()
    k = run_kpis(ap_rows, sta_rows, kpi_rows, WINDOW)
    assert k.affected_ap == "ap1"
    assert k.ttr_s == 60.0  # back under 80% at 160 s and held
    assert k.censor_s == 200.0
    # the affected flows are the stations on ap1 right after the onset: sta1's video only
    assert (k.throughput_mbps, k.latency_p95_ms, k.loss_pct) == (1.0, 20.0, 2.0)
    assert k.jain == pytest.approx(0.8)  # clients 3 and 1: (4)^2 / (2 * (9 + 1))


def test_a_run_that_never_recovers_has_no_recovery_time() -> None:
    ap_rows, sta_rows, kpi_rows = _run()
    stuck = [r | {"channel_util": 0.95} if r["ap"] == "ap1" else r for r in ap_rows]
    assert run_kpis(stuck, sta_rows, kpi_rows, WINDOW).ttr_s is None


def test_rows_before_the_onset_do_not_count() -> None:
    ap_rows, sta_rows, kpi_rows = _run()
    early = [r | {"throughput_mbps": 99.0} if r["t_s"] < ONSET else r for r in kpi_rows]
    assert run_kpis(ap_rows, sta_rows, early, WINDOW).throughput_mbps == 1.0


def test_when_the_event_names_an_ap_its_stations_before_the_onset_are_the_affected_ones() -> None:
    # ap_failure / cochannel (decision P6.6-A): the stations that lose service, wherever they
    # end up; here sta2 was on ap2 (the AP that fails) and moves to ap1 at the onset
    ap_rows, sta_rows, kpi_rows = _run()
    moved = [r | {"ap": "ap1"} if r["sta"] == "sta2" and r["t_s"] >= ONSET else r for r in sta_rows]
    window = StressWindow(onset_s=ONSET, end_s=300.0, event_ap="ap2")
    k = run_kpis(ap_rows, moved, kpi_rows, window)
    assert (k.throughput_mbps, k.loss_pct) == (5.0, 0.0)  # sta2's web flow only
    assert k.latency_p95_ms == 20.0  # no affected video: all affected flows


def test_a_summary_is_the_mean_with_a_t_based_95_percent_interval() -> None:
    s = summarise([10.0, 20.0, 30.0])
    assert (s.mean, s.n) == (20.0, 3)
    assert s.ci95 == pytest.approx(24.84, abs=0.01)  # t(0.975, 2) = 4.303; sd 10; / sqrt(3)


def test_one_value_has_no_interval_and_none_has_no_mean() -> None:
    assert summarise([5.0]).ci95 is None
    assert summarise([]).mean is None
