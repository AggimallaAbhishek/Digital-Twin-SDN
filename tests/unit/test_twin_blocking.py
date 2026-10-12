"""P6.5 twin blocking and safety counts (experiments/analysis/twin_blocking.py)."""

from __future__ import annotations

from datetime import UTC, datetime

from common.schemas import ACTION_ADAPTER, KPIValues, Verdict
from controller.executor.ledger import ActionRecord
from experiments.analysis.twin_blocking import audit

T0 = datetime(2026, 10, 20, 10, 0, tzinfo=UTC)
KPIS = KPIValues(throughput_mbps=2.0, latency_ms=20.0, loss_pct=1.0, jain=0.9)


def _record(  # noqa: PLR0913 - one keyword per ledger column the counts read
    n: int,
    *,
    accepted: bool,
    status: str,
    applied: bool = True,
    high: bool = False,
    approved_by: str | None = None,
) -> ActionRecord:
    kind, params = (
        ("set_ap_channel", {"ap": "ap1", "channel": 6})
        if high
        else ("steer_clients", {"from_ap": "ap1", "to_ap": "ap2", "stations": [f"sta{n}"]})
    )
    action = ACTION_ADAPTER.validate_python(
        {
            "action_id": f"act_b_{n}",
            "type": kind,
            "source": "optimizer.heuristic",
            "reason": "test",
            "created_at": T0,
            "params": params,
        }
    )
    verdict = Verdict(
        action_id=action.action_id,
        accepted=accepted,
        predicted=KPIS,
        baseline=KPIS,
        violations=[] if accepted else ["latency_ms 12.0% worse"],
        impact="high" if high else "medium",
        needs_approval=high,
        sim_mode="analytical",
        sim_time_ms=1.0,
    )
    return ActionRecord(
        action_id=action.action_id,
        group_id=f"g{n}",
        action=action,
        verdict=verdict,
        status=status,
        approved_by=approved_by,
        previous=None,
        baseline=None,
        applied_at=T0 if applied else None,
        note="",
    )


def test_h2_counts_twin_rejected_actions_that_v2_applied_and_that_did_harm() -> None:
    records = [
        _record(1, accepted=False, status="rolled_back"),  # rejected, applied, harmful
        _record(2, accepted=False, status="kept"),  # rejected, applied, no measured harm
        _record(3, accepted=True, status="kept"),
        _record(4, accepted=True, status="rolled_back"),  # slipped past the twin
        _record(5, accepted=False, status="rejected", applied=False),  # V3: never applied
    ]
    counts = audit(records)
    assert counts == {
        "recorded": 5,
        "applied": 4,
        "applied_twin_rejected": 2,
        "harmful_twin_rejected": 1,  # decision P6.5-A: twin-rejected and rolled back
        "slipped_past_twin": 1,
        "rollback_failed": 0,
        "high_impact_unapproved": 0,
        "unresolved": 0,
    }


def test_a_failed_rollback_counts_as_harm_and_an_unfinished_watch_as_unresolved() -> None:
    records = [
        _record(1, accepted=False, status="rollback_failed"),  # harmful, and not even undone
        _record(2, accepted=False, status="applied"),  # the run ended during its watch
    ]
    counts = audit(records)
    assert (counts["harmful_twin_rejected"], counts["unresolved"]) == (1, 1)


def test_high_impact_actions_applied_without_an_approval_are_counted() -> None:
    records = [
        _record(1, accepted=True, status="kept", high=True),
        _record(2, accepted=True, status="kept", high=True, approved_by="operator"),
        _record(3, accepted=True, status="rollback_failed"),
    ]
    counts = audit(records)
    assert (counts["high_impact_unapproved"], counts["rollback_failed"]) == (1, 1)
