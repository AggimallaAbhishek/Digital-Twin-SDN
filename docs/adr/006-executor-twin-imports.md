# ADR-006: The executor may read twin state types and the twin's QoS flow match

- **Status:** Accepted (Abhishek, 2026-10-09)
- **Phase / task:** P4.4 (executor), code review of P3.4–P4.5
- **Deviation log:** PHASE_PLAN.md #14

## Context

RULEBOOK §4 lets `controller/executor/` import `common` and `twin.verify` (types only). The executor is built around the twin's state, though:

- `Executor.apply(action_ids, state)` and the actuator take a `TwinState` (`twin/state/model.py`), the same state the verifier judged.
- A `set_qos_queue` action names its traffic by zone and app class. The actuator turns that into flow ids with the twin's own rule, `twin.sim.apply.qos_flow_ids`, so the network gets exactly the flows the twin simulated. A second copy of that rule in the executor could drift.

The import-linter contract for `controller` did not restrict `twin` at all, so the rule was neither followed nor enforced.

## Decision

- `controller/executor/` may also import **`twin.state.model`** (state types) and **`twin.sim.apply`** (for `qos_flow_ids`; `apply` itself only builds new states). Read-only use: the executor never changes the twin.
- Everything else in `twin` stays forbidden to the executor (the simulator, sync, builder, radio model, validation), and the Ryu app (`controller/apps/`) may not import `twin` at all. Two import-linter contracts enforce this.

## Consequences

- **Positive:** one QoS matching rule for the twin and the network; the boundary is now written down and checked by `make check`, where before it was neither.
- **Negative:** the executor depends on two twin modules. A change to `TwinState` or `qos_flow_ids` must keep the executor's tests passing (they do run in `make check`).
