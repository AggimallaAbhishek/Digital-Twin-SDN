"""P4.3 heuristic optimizer: candidate actions for a congested or interfering network.

Pure functions of a TwinState (no I/O). Two heuristics (deviation #9: no reroute on a tree):

- **Steering:** an AP at or above `util_high` sheds up to `max_steer_fraction` of its clients
  (rounded down) to APs below `util_target`, least-loaded first. A station is only moved to an AP
  where its predicted signal is at least `min_target_rssi_dbm` (twin/radio.py), strongest first.
- **Channel:** a congested AP (at or above `util_high`) that shares its channel with nearby APs
  that are up moves to the channel with the least co-channel load (twin/radio.py), if that is
  strictly better. Idle APs keep their channel: a channel change is high-impact (approval).
  APs are handled in order of decreasing load, each decision seeing the earlier ones, so two APs
  never jump onto the same channel together.

These are proposals: the twin verifier (P3.4) still checks every action and its bounds.
"""

from __future__ import annotations

import dataclasses
import hashlib
import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from common.schemas import (
    ACTION_ADAPTER,
    CHANNELS_24GHZ,
    MAX_STEER_FRACTION,
    MIN_TARGET_RSSI_DBM,
    Action,
    SetApChannelParams,
    SteerClientsParams,
)
from twin.radio import RadioParams, cochannel_load, predicted_rssi_dbm
from twin.state.model import APState, TwinState

SOURCE = "optimizer.heuristic"


@dataclass(frozen=True)
class HeuristicConfig:
    """config/optimizer.yaml."""

    util_high: float
    util_target: float
    max_steer_fraction: float
    min_target_rssi_dbm: float


_KEYS = tuple(f.name for f in dataclasses.fields(HeuristicConfig))
# A proposal before it gets an id: the action type, its params, and why
Draft = tuple[str, BaseModel, str]


def load_heuristic_config(raw: Mapping[str, Any]) -> HeuristicConfig:
    """Validate a parsed config/optimizer.yaml; ValueError names the bad field."""
    unknown = set(raw) - set(_KEYS)
    if unknown:
        raise ValueError(f"optimizer config: unknown keys {sorted(unknown)}")
    for key in _KEYS:
        value = raw.get(key)
        if not isinstance(value, int | float) or isinstance(value, bool):
            raise ValueError(f"{key} must be a number, got {value!r}")
    config = HeuristicConfig(*(float(raw[k]) for k in _KEYS))
    if not 0 < config.util_high <= 1:
        raise ValueError("util_high must be within (0, 1]")
    if not 0 <= config.util_target < config.util_high:
        raise ValueError("util_target must be >= 0 and below util_high")
    if not 0 < config.max_steer_fraction <= MAX_STEER_FRACTION:
        raise ValueError(f"max_steer_fraction must be within (0, {MAX_STEER_FRACTION}] (ADR-004)")
    if config.min_target_rssi_dbm < MIN_TARGET_RSSI_DBM:
        raise ValueError(f"min_target_rssi_dbm may not be below {MIN_TARGET_RSSI_DBM} (ADR-004)")
    return config


def propose(state: TwinState, config: HeuristicConfig, radio: RadioParams) -> list[Action]:
    """Steering then channel proposals, with deterministic ids (act_<ts>_<n>_<content hash>)."""
    drafts: list[Draft] = [
        *_steering(state, config, radio),
        *_channel_changes(state, config, radio),
    ]
    stamp = state.ts.strftime("%Y%m%d_%H%M%S")
    actions: list[Action] = []
    for n, (kind, params, reason) in enumerate(drafts, start=1):
        # the content hash keeps ids distinct across propose() calls within the same second
        digest = hashlib.sha256(f"{kind}{params.model_dump_json()}".encode()).hexdigest()[:8]
        action = {
            "action_id": f"act_{stamp}_{n:03d}_{digest}",
            "type": kind,  # selects the Action class (common/schemas.py discriminator)
            "source": SOURCE,
            "reason": reason,
            "created_at": state.ts,
            "params": params,
        }
        actions.append(ACTION_ADAPTER.validate_python(action))
    return actions


def _steering(state: TwinState, config: HeuristicConfig, radio: RadioParams) -> list[Draft]:
    drafts: list[Draft] = []
    up = state.up_aps()
    for ap in sorted((a for a in up if a.util >= config.util_high), key=lambda a: -a.util):
        clients = state.clients(ap.name)
        budget = math.floor(config.max_steer_fraction * len(clients))
        targets = sorted(
            (t for t in up if t.name != ap.name and t.util < config.util_target),
            key=lambda t: (t.util, t.name),
        )
        remaining = list(clients)
        for target in targets:
            if budget == 0:
                break
            movable = _movable(state, remaining, target, config, radio)[:budget]
            if not movable:
                continue
            budget -= len(movable)
            remaining = [s for s in remaining if s not in movable]
            reason = (
                f"{ap.name} at {ap.util:.0%} of capacity (>= {config.util_high:.0%}); "
                f"{target.name} at {target.util:.0%}; predicted signal at {target.name} "
                f">= {config.min_target_rssi_dbm:g} dBm for {', '.join(movable)}"
            )
            params = SteerClientsParams(from_ap=ap.name, to_ap=target.name, stations=movable)
            drafts.append(("steer_clients", params, reason))
    return drafts


def _movable(
    state: TwinState,
    stations: list[str],
    target: APState,
    config: HeuristicConfig,
    radio: RadioParams,
) -> list[str]:
    """Stations with a usable predicted signal at `target`, strongest first."""
    signal = {
        s: predicted_rssi_dbm(target.position, state.stations[s].position, radio) for s in stations
    }
    usable = [s for s in stations if signal[s] >= config.min_target_rssi_dbm]
    return sorted(usable, key=lambda s: -signal[s])


def _channel_changes(state: TwinState, config: HeuristicConfig, radio: RadioParams) -> list[Draft]:
    up = state.up_aps()
    channels = {ap.name: ap.channel for ap in up}

    def load(ap: APState, channel: int) -> float:
        others = [o for o in up if o.name != ap.name and channels[o.name] == channel]
        return cochannel_load((math.dist(ap.position, o.position) for o in others), radio)

    drafts: list[Draft] = []
    for ap in sorted(up, key=lambda a: (-load(a, channels[a.name]), a.name)):
        current = load(ap, channels[ap.name])
        if current == 0 or ap.util < config.util_high:
            continue
        best = min(CHANNELS_24GHZ, key=lambda ch: (load(ap, ch), ch != channels[ap.name], ch))
        best_load = load(ap, best)
        if best_load < current:
            reason = (
                f"{ap.name} on channel {channels[ap.name]} has co-channel load {current:.2f}; "
                f"channel {best} has {best_load:.2f}"
            )
            drafts.append(("set_ap_channel", SetApChannelParams(ap=ap.name, channel=best), reason))
            channels[ap.name] = best  # later decisions see this move
    return drafts
