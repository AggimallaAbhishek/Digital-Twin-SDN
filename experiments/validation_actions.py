"""P3.5 validation batch: the actions to apply during a run, and when they happened.

A schedule (experiments/actions_v1.yaml) lists, per scenario, steps at scenario times:

- an explicit action type with its params (`set_qos_queue`, `rate_limit_flow`, ...);
- `steer_one` {from_ap, to_ap}: steer the from_ap client with the strongest predicted signal at
  to_ap (twin/radio.py), so the step stays valid whichever stations are there;
- `heuristic` {}: whatever the P4.3 optimizer proposes for the live state.

experiments/run_batch.py turns each due step into actions on the live twin state, has the twin
verify them and applies only accepted ones through the executor (CLAUDE.md: nothing reaches the
network without an accepted Verdict). It logs each step with its UTC time; `timed_actions`
turns the applied ones into scenario time for the dataset (actions.jsonl), the same clock the
telemetry rows use.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from common.schemas import ACTION_ADAPTER, IMPACT, Action
from ml.optimizer.heuristics import HeuristicConfig, propose
from twin.radio import RadioParams, predicted_rssi_dbm
from twin.state.model import TwinState

SPECIAL = ("steer_one", "heuristic")


@dataclass(frozen=True)
class ActionStep:
    """One scheduled step: at `at_s` seconds into the scenario."""

    at_s: float
    type: str
    params: dict[str, Any]  # Any: action params as JSON


def load_schedule(raw: Mapping[str, Any]) -> dict[str, list[ActionStep]]:
    """Validate a parsed schedule; steps sorted by time. ValueError names the bad step."""
    schedule = {}
    for scenario, steps in raw.items():
        parsed = []
        for step in steps:
            kind, at_s, params = step.get("type"), step.get("at_s"), step.get("params", {})
            ok = (
                isinstance(at_s, int | float)
                and at_s >= 0
                and (kind in IMPACT or kind in SPECIAL)
                and isinstance(params, dict)
                and not (kind == "heuristic" and params)
            )
            if not ok:
                raise ValueError(f"{scenario}: bad step {step!r}")
            parsed.append(ActionStep(float(at_s), str(kind), params))
        schedule[scenario] = sorted(parsed, key=lambda s: s.at_s)
    return schedule


def actions_for(
    step: ActionStep,
    state: TwinState,
    radio: RadioParams,
    heuristics: HeuristicConfig,
    run_id: str,
) -> list[Action]:
    """The actions a step means on the live state (maybe none)."""
    if step.type == "heuristic":
        return propose(state, heuristics, radio)
    if step.type == "steer_one":
        best = _strongest_client(state, step.params["from_ap"], step.params["to_ap"], radio)
        if best is None:
            return []
        kind, params = "steer_clients", {**step.params, "stations": [best]}
    else:
        kind, params = step.type, step.params
    action = ACTION_ADAPTER.validate_python(
        {
            "action_id": f"act_{run_id.replace('-', '_')}_{int(step.at_s)}",
            "type": kind,
            "source": "operator",
            "reason": f"P3.5 validation batch step at {step.at_s:g} s",
            "created_at": state.ts,
            "params": params,
        }
    )
    return [action]


def _strongest_client(state: TwinState, from_ap: str, to_ap: str, radio: RadioParams) -> str | None:
    target = state.aps.get(to_ap)
    clients = state.clients(from_ap)
    if target is None or not clients:
        return None
    return max(
        clients,
        key=lambda s: predicted_rssi_dbm(target.position, state.stations[s].position, radio),
    )


def timed_actions(lines: Sequence[Mapping[str, Any]], t0: datetime) -> list[dict[str, Any]]:
    """Applied steps as {run_id, t_s, action}, t_s counted from the scenario start `t0`."""
    return [
        {
            "run_id": line["run_id"],
            "t_s": round((datetime.fromisoformat(line["utc"]) - t0).total_seconds(), 3),
            "action": line["action"],
        }
        for line in lines
        if line["applied"]
    ]
