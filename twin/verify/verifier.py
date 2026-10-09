"""P3.4 verifier: would these actions help? One joint Verdict per action (PROJECT_PLAN §7.5, §8).

    verdicts = verify(state, actions, VerifyContext(campus, radio, sim, config, policies))

The actions are checked and simulated **together** (an intent's actions are all or nothing,
decision P3.4-B); a heuristic's single action is a set of one.

1. **Bounds** that need live state (PROJECT_PLAN §7.3, ADR-004), on the state as the earlier
   actions of the set leave it: a steer moves at most MAX_STEER_FRACTION of the source AP's
   clients, only stations that are on it, each to a predicted signal >= MIN_TARGET_RSSI_DBM;
   a tx power step is at most 3 dB; an AP never goes down if it is the last one up in its zone;
   no reroute (campus_v1 is a tree, deviation #9). Unknown targets are refused.
2. **KPIs** (decision P3.4-A): the twin (twin/sim/analytical.py) predicts before and after. The
   verdict compares the **affected flows**, those whose predicted KPIs change, with the problem
   statement §5.1 definitions: mean throughput, p95 latency of the video flows (all flows if
   none is video), mean loss; Jain's index is network-wide.
3. **Acceptance rule** (§7.5): reject if any KPI gets worse by more than 5% while none gets better
   by more than 5%.
4. **Policies**: a hard constraint may not be broken, or made worse if it already is; an
   objective that was met may not become missed. Measured on the worst flow in scope. Jitter is
   not predicted by the twin, so jitter targets are not checked here.
5. **Impact** (§8): low applies on acceptance; high always needs approval; medium applies on
   acceptance only for the types config/verify.yaml lists, those P3.5 validated (P3.4-C).
"""

from __future__ import annotations

import dataclasses
import math
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from common.schemas import (
    IMPACT,
    MAX_STEER_FRACTION,
    MIN_TARGET_RSSI_DBM,
    Action,
    ApAdminState,
    Constraint,
    KPIValues,
    Objective,
    Policy,
    RerouteFlow,
    SetApTxPower,
    SteerClients,
    Verdict,
    impact_of,
)
from twin.radio import RadioParams, predicted_rssi_dbm
from twin.sim.analytical import FlowResult, SimParams, SimResult, simulate
from twin.sim.apply import apply
from twin.state.builder import CampusAPs
from twin.state.model import TwinState

TX_POWER_MAX_STEP_DB = 3.0  # PROJECT_PLAN §7.3
CHANGE_PCT = 5.0  # PROJECT_PLAN §7.5: worse / better by more than this share counts
P95 = 0.95
_LOWER_IS_BETTER = {"latency_ms", "loss_pct"}


@dataclass(frozen=True)
class VerifyConfig:
    """config/verify.yaml."""

    medium_auto_apply: frozenset[str]  # medium-impact types trusted to apply on acceptance


def load_verify_config(raw: Mapping[str, Any]) -> VerifyConfig:
    """Validate a parsed config/verify.yaml."""
    types = raw.get("medium_auto_apply")
    medium = {kind for kind, impact in IMPACT.items() if impact == "medium"}
    if set(raw) != {"medium_auto_apply"} or not isinstance(types, list) or not set(types) <= medium:
        raise ValueError(
            f"verify config must be exactly {{medium_auto_apply: [medium-impact types]}} "
            f"(one of {sorted(medium)}): {raw!r}"
        )
    return VerifyConfig(medium_auto_apply=frozenset(types))


@dataclass(frozen=True)
class VerifyContext:
    """Everything the verifier needs besides the state and the actions."""

    campus: CampusAPs
    radio: RadioParams
    sim: SimParams
    config: VerifyConfig
    policies: tuple[Policy, ...] = ()

    def with_policies(self, policies: Sequence[Policy]) -> VerifyContext:
        """The same context with these standing policies."""
        return dataclasses.replace(self, policies=tuple(policies))


def verify(state: TwinState, actions: Sequence[Action], context: VerifyContext) -> list[Verdict]:
    """One Verdict per action, all from the same joint check and simulation."""
    if not actions:
        raise ValueError("no actions to verify")
    start = time.perf_counter()
    after, violations = _apply_within_bounds(state, actions, context)
    before_sim = simulate(state, context.radio, context.sim)
    after_sim = simulate(after, context.radio, context.sim) if not violations else before_sim
    affected = sorted(f for f in state.flows if before_sim.flows[f] != after_sim.flows[f])
    baseline = _kpis(state, before_sim, affected)
    predicted = _kpis(state, after_sim, affected)
    if not violations:
        violations = _kpi_rule(baseline, predicted) + _policy_checks(
            state, before_sim, after_sim, context.policies
        )
    elapsed_ms = (time.perf_counter() - start) * 1000
    return [
        Verdict(
            action_id=a.action_id,
            accepted=not violations,
            predicted=predicted,
            baseline=baseline,
            violations=violations,
            impact=impact_of(a),
            needs_approval=_needs_approval(a, context.config),
            sim_mode="analytical",
            sim_time_ms=elapsed_ms,
        )
        for a in actions
    ]


def _needs_approval(action: Action, config: VerifyConfig) -> bool:
    impact = impact_of(action)
    return impact == "high" or (impact == "medium" and action.type not in config.medium_auto_apply)


def _apply_within_bounds(
    state: TwinState, actions: Sequence[Action], context: VerifyContext
) -> tuple[TwinState, list[str]]:
    """The state after all actions, or the violations that stop the set."""
    violations: list[str] = []
    current = state
    for action in actions:
        problems = _bounds(current, action, context)
        if not problems:
            try:
                current = apply(current, action)
            except ValueError as exc:  # unknown or stale targets
                problems = [str(exc)]
        violations += [f"{action.action_id}: {p}" for p in problems]
    return current, violations


def _bounds(state: TwinState, action: Action, context: VerifyContext) -> list[str]:
    if isinstance(action, SteerClients):
        return _steer_bounds(state, action, context.radio)
    if isinstance(action, SetApTxPower):
        return _tx_power_bound(state, action)
    if isinstance(action, ApAdminState) and action.params.state == "down":
        return _last_ap_bound(state, action.params.ap, context.campus)
    if isinstance(action, RerouteFlow):
        return ["reroute_flow: campus_v1 has one path between any two nodes (deviation #9)"]
    return []


def _steer_bounds(state: TwinState, action: SteerClients, radio: RadioParams) -> list[str]:
    p = action.params
    unknown = [ap for ap in (p.from_ap, p.to_ap) if ap not in state.aps]
    if unknown:
        return [f"unknown AP: {', '.join(unknown)}"]
    clients = state.clients(p.from_ap)
    problems = [f"{s} is not on {p.from_ap}" for s in p.stations if s not in clients]
    if len(p.stations) > MAX_STEER_FRACTION * len(clients):
        problems.append(
            f"moves {len(p.stations)} of {len(clients)} clients of {p.from_ap}: "
            f"more than {MAX_STEER_FRACTION:.0%} (ADR-004)"
        )
    target = state.aps[p.to_ap]
    for s in p.stations:
        if s in state.stations:
            rssi = predicted_rssi_dbm(target.position, state.stations[s].position, radio)
            if rssi < MIN_TARGET_RSSI_DBM:
                problems.append(
                    f"{s} would get {rssi:.0f} dBm at {p.to_ap}: "
                    f"below {MIN_TARGET_RSSI_DBM:g} dBm (ADR-004)"
                )
    return problems


def _tx_power_bound(state: TwinState, action: SetApTxPower) -> list[str]:
    ap = state.aps.get(action.params.ap)
    if ap is None or ap.tx_power_dbm is None:
        return []  # unknown AP: apply() refuses it; unknown power: no step to check
    step = abs(action.params.dbm - ap.tx_power_dbm)
    if step > TX_POWER_MAX_STEP_DB:
        return [f"tx power step {step:g} dB on {ap.name}: more than 3 dB (PROJECT_PLAN §7.3)"]
    return []


def _last_ap_bound(state: TwinState, name: str, campus: CampusAPs) -> list[str]:
    ap = state.aps.get(name)
    zone = campus.zone_of(ap.position) if ap is not None else None
    if zone is None:
        return []  # unknown AP (apply() refuses it) or an AP outside every zone
    others = [a for a in state.up_aps() if a.name != name and campus.zone_of(a.position) == zone]
    return [] if others else [f"{name} is the last AP up in {zone} (PROJECT_PLAN §7.3)"]


def _kpis(state: TwinState, sim: SimResult, flow_ids: Sequence[str]) -> KPIValues:
    """§5.1 KPIs over `flow_ids`: mean throughput, p95 video latency, mean loss; network Jain."""
    flows = [sim.flows[f] for f in flow_ids]
    video = [sim.flows[f] for f in flow_ids if state.flows[f].app_class == "video"]
    latencies = sorted(r.latency_ms for r in (video or flows))
    return KPIValues(
        throughput_mbps=_mean(r.throughput_mbps for r in flows),
        latency_ms=latencies[math.ceil(P95 * len(latencies)) - 1] if latencies else 0.0,
        loss_pct=_mean(r.loss_pct for r in flows),
        jain=sim.kpis.jain,
    )


def _mean(values: Any) -> float:  # Any: an iterable of floats
    items = list(values)
    return math.fsum(items) / len(items) if items else 0.0


def _kpi_rule(baseline: KPIValues, predicted: KPIValues) -> list[str]:
    """§7.5: reject if a KPI gets > 5% worse while none gets > 5% better."""
    worse, better = {}, False
    for kpi, before in baseline.model_dump().items():
        change = _better_pct(kpi, before, getattr(predicted, kpi))
        if change < -CHANGE_PCT:
            worse[kpi] = change
        better = better or change > CHANGE_PCT
    if better:
        return []
    return [
        f"{kpi} {-pct:.1f}% worse and no KPI improves by more than {CHANGE_PCT:g}%"
        for kpi, pct in worse.items()
    ]


def _better_pct(kpi: str, before: float, after: float) -> float:
    """How much better `after` is than `before`, in percent (negative = worse)."""
    if before == after:
        return 0.0
    if before == 0:
        return math.inf if (after < before) == (kpi in _LOWER_IS_BETTER) else -math.inf
    gain = (after - before) / before * 100
    return -gain if kpi in _LOWER_IS_BETTER else gain


def _policy_checks(
    state: TwinState, before: SimResult, after: SimResult, policies: Sequence[Policy]
) -> list[str]:
    problems = []
    for policy in policies:
        rules: list[Constraint | Objective] = [*policy.constraints, *policy.objectives]
        for rule in rules:
            if rule.kpi in ("priority", "jitter_ms"):
                continue  # a priority is an action, not a KPI; the twin does not predict jitter
            flow_ids = _scope(state, policy, rule)
            if not flow_ids:
                continue
            was = _worst(rule, before, flow_ids)
            now = _worst(rule, after, flow_ids)
            met_before, met_now = _meets(rule, was), _meets(rule, now)
            hard = isinstance(rule, Constraint)
            broken = not met_now and (met_before or (hard and _better_pct(rule.kpi, was, now) < 0))
            if broken:
                problems.append(
                    f"{policy.policy_id}: {rule.kpi} {rule.op} {float(rule.value):g} "
                    f"{'broken' if hard else 'no longer met'} ({now:.2f} predicted)"
                )
    return problems


def _scope(state: TwinState, policy: Policy, rule: Constraint | Objective) -> list[str]:
    if isinstance(rule, Constraint) and rule.scope == "all":
        return sorted(state.flows)
    zone, apps = policy.scope.zone, policy.scope.app_class
    return sorted(
        f.flow_id
        for f in state.flows.values()
        if (zone is None or state.stations[f.sta].zone == zone)
        and (apps is None or f.app_class in apps)
    )


def _worst(rule: Constraint | Objective, sim: SimResult, flow_ids: Sequence[str]) -> float:
    values = [_metric(sim.flows[f], rule.kpi) for f in flow_ids]
    return max(values) if rule.op == "<=" else min(values)


def _metric(result: FlowResult, kpi: str) -> float:
    return float(getattr(result, kpi))


def _meets(rule: Constraint | Objective, value: float) -> bool:
    target = float(rule.value)
    return value <= target if rule.op == "<=" else value >= target
