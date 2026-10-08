# ADR-004: Steering bounds are constants in `common/schemas.py`

- **Status:** Accepted (Abhishek, 2026-10-08)
- **Phase / task:** P4.3 (heuristics), P3.4 (verifier)
- **Deviation log:** PHASE_PLAN.md #10

## Context

PROJECT_PLAN §7.3 bounds `steer_clients` in two ways: at most **30%** of the source AP's clients per action, and a target signal of at least **−75 dBm**. These are state-dependent, so `common/schemas.py` can't check them on the `Action` itself; its docstring leaves them to the verifier (P3.4). Until now the numbers existed only in `config/optimizer.yaml` for the P4.3 heuristics. The verifier would have needed its own copy, and a safety bound would then live in two tunable places that could drift.

## Decision

Add `MAX_STEER_FRACTION = 0.3` and `MIN_TARGET_RSSI_DBM = -75.0` to `common/schemas.py`, next to the existing static bounds (`TX_POWER_DBM_MIN/MAX`, `CHANNELS_24GHZ`, `RATE_LIMIT_MIN_MBPS`).

- The **verifier (P3.4) enforces these constants** for every steering action, whatever proposed it.
- **`config/optimizer.yaml` may only be stricter.** The heuristics' loader rejects a steer fraction above the constant or a target signal below it.
- The schema module's behaviour doesn't change: these are new named constants, and no model or validator changes.

## Consequences

- **Positive:** one source for each safety bound. The verifier, the heuristics and later the LLM intent compiler all read the same values.
- **Negative:** a contract file changes before the P0.6 freeze, hence this ADR.
