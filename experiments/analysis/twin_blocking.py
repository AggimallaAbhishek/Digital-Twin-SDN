"""P6.5 twin blocking (H2) and the safety counts of problem statement §5.3, from the executor
ledgers of the campaign runs (data/raw/<version>/<run_id>/actions.db).

In V2 the loop applies every heuristic proposal, but the twin's verdict is still recorded
(ADR-005). An action counts as **harmful and blocked by the twin** when the twin rejected it,
V2 applied it anyway, and the executor's watch then measured a regression and rolled it back,
or tried to (decision P6.5-A). `applied_twin_rejected` is the looser count (no measured harm
needed); `unresolved` actions were still being watched when their run ended.
"""

from __future__ import annotations

from collections.abc import Sequence

from controller.executor.ledger import ActionRecord

# the watch measured a regression: rolled back, or the rollback itself failed (worse still)
HARMED = ("rolled_back", "rollback_failed")


def audit(records: Sequence[ActionRecord]) -> dict[str, int]:
    """The H2 and safety counts of one ledger."""
    applied = [r for r in records if r.applied_at is not None]
    rejected = [r for r in applied if not r.verdict.accepted]
    return {
        "recorded": len(records),
        "applied": len(applied),
        "applied_twin_rejected": len(rejected),
        "harmful_twin_rejected": sum(r.status in HARMED for r in rejected),
        "slipped_past_twin": sum(r.verdict.accepted and r.status == "rolled_back" for r in applied),
        "rollback_failed": sum(r.status == "rollback_failed" for r in applied),
        "high_impact_unapproved": sum(
            r.verdict.needs_approval and r.approved_by is None for r in applied
        ),
        "unresolved": sum(r.status == "applied" for r in applied),  # the run ended mid-watch
    }
