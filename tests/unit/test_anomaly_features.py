"""P4.2 window features (ml/anomaly/features.py) on hand-made rows; expected values by hand."""

from __future__ import annotations

from typing import Any

import pytest

from ml.anomaly.features import RunRows, feature_names, windows

APS = ("ap1", "ap2")


def _ap(t_s: float, ap: str, util: float, clients: int) -> dict[str, Any]:
    return {"t_s": t_s, "ap": ap, "channel_util": util, "n_clients": clients}


def _run(**overrides: Any) -> RunRows:
    ap_rows = [_ap(t, "ap1", 0.2, 3) for t in range(0, 60)] + [
        _ap(t, "ap2", 0.4, 5) for t in range(0, 60)
    ]
    sta_rows = [{"t_s": t, "sta": "sta1", "ap": "ap1"} for t in range(0, 60)]
    kpi_rows = [{"t_s": t, "loss_pct": 1.0, "latency_ms": 10.0} for t in range(0, 60)]
    base = {
        "run_id": "normal-s42",
        "scenario_id": "normal",
        "split": "train",
        "onset_s": None,
        "ap_rows": ap_rows,
        "sta_rows": sta_rows,
        "kpi_rows": kpi_rows,
    }
    return RunRows(**{**base, **overrides})


def test_feature_names_are_per_ap_then_network() -> None:
    assert feature_names(APS) == [
        "ap1.util_mean", "ap1.util_max", "ap1.clients_mean", "ap1.clients_delta", "ap1.silent",
        "ap2.util_mean", "ap2.util_max", "ap2.clients_mean", "ap2.clients_delta", "ap2.silent",
        "net.unassociated", "net.loss_mean", "net.latency_p95",
    ]  # fmt: skip


def test_steady_run_gives_steady_windows() -> None:
    # 60 s at 5 s steps = 12 bins; 30 s windows (6 bins) end at bins 5..11 -> 7 windows
    ws = windows(_run(), APS, step_s=5, window_s=30)
    assert len(ws) == 7
    first = dict(zip(feature_names(APS), ws[0].features, strict=True))
    assert first["ap1.util_mean"] == pytest.approx(0.2)
    assert first["ap2.clients_mean"] == pytest.approx(5)
    assert first["ap1.clients_delta"] == 0
    assert first["ap1.silent"] == 0.0
    assert first["net.unassociated"] == 0.0
    assert first["net.loss_mean"] == pytest.approx(1.0)
    assert ws[0].t_end_s == 30.0  # end of bin 5
    assert not any(w.stress for w in ws)


def test_a_silent_ap_and_its_orphans_show_up() -> None:
    ap_rows = [_ap(t, "ap1", 0.2, 3) for t in range(0, 60)] + [
        _ap(t, "ap2", 0.4, 5)
        for t in range(0, 30)  # ap2 stops reporting at 30 s
    ]
    sta_rows = [{"t_s": t, "sta": "sta1", "ap": "ap2" if t < 30 else None} for t in range(0, 60)]
    ws = windows(_run(ap_rows=ap_rows, sta_rows=sta_rows), APS, step_s=5, window_s=30)
    last = dict(zip(feature_names(APS), ws[-1].features, strict=True))  # window 30-60 s
    assert last["ap2.silent"] == 1.0
    assert last["ap2.util_mean"] == 0.0  # a silent AP carries nothing
    assert last["net.unassociated"] == pytest.approx(1.0)


def test_client_delta_follows_a_crowd() -> None:
    ap_rows = [_ap(t, "ap1", 0.2, 3 + t // 10) for t in range(0, 60)] + [
        _ap(t, "ap2", 0.4, 5) for t in range(0, 60)
    ]
    ws = windows(_run(ap_rows=ap_rows), APS, step_s=5, window_s=30)
    first = dict(zip(feature_names(APS), ws[0].features, strict=True))  # bins 0-5 (0-30 s)
    # clients per 5 s bin: 3,3,4,4,5,5 -> delta last - first = 2
    assert first["ap1.clients_delta"] == 2


def test_windows_after_the_onset_are_stress() -> None:
    ws = windows(_run(onset_s=40.0), APS, step_s=5, window_s=30)
    # windows end at 30..60 s; the one ending at 40 s covers [10, 40) and has no data after onset
    assert [w.stress for w in ws] == [False, False, False, True, True, True, True]
    assert ws[2].t_end_s == 40.0


def test_p95_latency_uses_nearest_rank() -> None:
    kpi_rows = [
        {"t_s": float(t) / 2, "loss_pct": 0.0, "latency_ms": float(t)} for t in range(1, 21)
    ]
    ws = windows(_run(kpi_rows=kpi_rows), APS, step_s=5, window_s=10)  # first window 0-10 s
    first = dict(zip(feature_names(APS), ws[0].features, strict=True))
    # rows at 0.5 s steps; 10.0 s falls in the next bin, so 19 values (1..19): nearest rank = 19
    assert first["net.latency_p95"] == 19.0


def test_a_run_shorter_than_one_window_has_none() -> None:
    short = _run(ap_rows=[_ap(0, "ap1", 0.1, 1)], sta_rows=[], kpi_rows=[])
    assert windows(short, APS, step_s=5, window_s=30) == []
