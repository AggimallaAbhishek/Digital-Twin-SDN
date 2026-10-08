"""P5.3 deterministic policy compiler: a validated Policy -> concrete actions (PROJECT_PLAN §5.1).

The LLM only writes the Policy; this code decides what it means, so the result is predictable and
testable (RULEBOOK L-1, L-2). Decision P5.3-A:

- `priority` -> `set_qos_queue` for the policy's scope: high -> queue 1, normal -> 0, low -> 2;
  one action per app class (a QoS match holds one). A priority for all traffic everywhere would
  put everything in one queue, which changes nothing, so it is refused.
- `throughput_mbps <= X` -> `rate_limit_flow(X)` on every flow in scope (the strictest cap wins).
  X below the schema's rate-limit bound is refused.
- Every other objective (latency, loss, jitter, throughput floors) and every constraint is not an
  action: it stays on the policy and the verifier checks it every loop (P3.4).

Invalid LLM output never gets here: the client validates it against the Policy schema first.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime

from pydantic import BaseModel

from common.schemas import (
    ACTION_ADAPTER,
    RATE_LIMIT_MIN_MBPS,
    Action,
    Objective,
    Policy,
    QosMatch,
    RateLimitFlowParams,
    SetQosQueueParams,
)

SOURCE = "llm.intent"
QUEUE_FOR_PRIORITY = {"high": 1, "normal": 0, "low": 2}  # common/schemas.py QOS_QUEUE_IDS


class CompileError(ValueError):
    """The policy can't be turned into safe actions; the message says why."""


@dataclass(frozen=True)
class FlowRef:
    """A live flow the compiler can target: its id, app class and the zone of its station."""

    flow_id: str
    app_class: str
    zone: str | None


@dataclass(frozen=True)
class Compiled:
    """The actions to verify, and the objectives that stay standing (checked every loop)."""

    actions: list[Action] = field(default_factory=list)
    standing: list[Objective] = field(default_factory=list)


def compile_policy(policy: Policy, flows: Sequence[FlowRef], now: datetime) -> Compiled:
    """Deterministic: the same policy, flows and time give the same actions and ids."""
    drafts: list[tuple[str, BaseModel, str]] = []
    priorities = {o.value for o in policy.objectives if o.kpi == "priority"}
    if len(priorities) > 1:
        raise CompileError(f"conflicting priorities in one policy: {sorted(map(str, priorities))}")
    if priorities:
        drafts += _queue_drafts(policy, str(priorities.pop()))
    caps = [float(o.value) for o in policy.objectives if _is_cap(o)]
    if caps:
        drafts += _cap_drafts(policy, min(caps), flows)
    standing = [o for o in policy.objectives if o.kpi != "priority" and not _is_cap(o)]
    if caps and not any(kind == "rate_limit_flow" for kind, _, _ in drafts):
        standing += [o for o in policy.objectives if _is_cap(o)]  # nothing to limit right now
    return Compiled(_actions(drafts, policy, now), standing)


def _is_cap(objective: Objective) -> bool:
    return objective.kpi == "throughput_mbps" and objective.op == "<="


def _queue_drafts(policy: Policy, priority: str) -> list[tuple[str, BaseModel, str]]:
    zone, apps = policy.scope.zone, policy.scope.app_class
    if zone is None and apps is None:
        raise CompileError("a priority for all traffic everywhere changes nothing")
    queue = QUEUE_FOR_PRIORITY[priority]
    reason = f"{policy.policy_id}: priority {priority} -> queue {queue}"
    return [
        (
            "set_qos_queue",
            SetQosQueueParams(match=QosMatch(zone=zone, app_class=app), queue_id=queue),
            reason,
        )
        for app in ([*apps] if apps else [None])  # None: every app class in the zone
    ]


def _cap_drafts(
    policy: Policy, cap: float, flows: Sequence[FlowRef]
) -> list[tuple[str, BaseModel, str]]:
    if cap < RATE_LIMIT_MIN_MBPS:
        raise CompileError(
            f"throughput cap {cap:g} Mbit/s is below the {RATE_LIMIT_MIN_MBPS} Mbit/s "
            "rate-limit bound"
        )
    zone, apps = policy.scope.zone, policy.scope.app_class
    matching = [
        f
        for f in sorted(flows, key=lambda f: f.flow_id)
        if (zone is None or f.zone == zone) and (apps is None or f.app_class in apps)
    ]
    reason = f"{policy.policy_id}: throughput <= {cap:g} Mbit/s"
    return [
        ("rate_limit_flow", RateLimitFlowParams(flow_id=f.flow_id, max_mbps=cap), reason)
        for f in matching
    ]


def _actions(
    drafts: list[tuple[str, BaseModel, str]], policy: Policy, now: datetime
) -> list[Action]:
    stamp = now.strftime("%Y%m%d_%H%M%S")
    actions: list[Action] = []
    for n, (kind, params, reason) in enumerate(drafts, start=1):
        # the hash keeps ids distinct across policies compiled within the same second
        digest = hashlib.sha256(
            f"{policy.policy_id}{kind}{params.model_dump_json()}".encode()
        ).hexdigest()[:8]
        action = {
            "action_id": f"act_{stamp}_{n:03d}_{digest}",
            "type": kind,  # selects the Action class (common/schemas.py discriminator)
            "source": SOURCE,
            "reason": reason,
            "created_at": now,
            "params": params,
        }
        actions.append(ACTION_ADAPTER.validate_python(action))
    return actions
