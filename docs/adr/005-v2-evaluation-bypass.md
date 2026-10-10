# ADR-005: V2 evaluation runs may apply actions without an accepted twin verdict

- **Status:** Accepted (Abhishek, 2026-10-09)
- **Phase / task:** P4.5 (loop), P6 (evaluation, hypothesis H2)
- **Deviation log:** PHASE_PLAN.md #13

## Context

CLAUDE.md and RULEBOOK make it a non-negotiable that nothing reaches the network without an accepted twin `Verdict`. The evaluation, though, compares three variants (PHASE_PLAN §2): V1 plain SDN, **V2 heuristics without the twin**, V3 the full system. Hypothesis H2 asks whether the twin blocks actions that would have hurt KPIs and that an optimizer acting directly (V2) would apply. That can only be measured if V2 really applies what the heuristics propose, including what the twin would have rejected. Estimating V2's harm inside the twin instead would have the twin judge its own blocks, which is circular.

## Decision

- The executor gets one switch, `unverified_ok`, off by default. With it on, `apply` also takes actions the twin rejected and actions still waiting for approval. Everything else stays on: the verdict is still computed and recorded, every action is applied once at most, a verified set is still applied whole, the rate limits hold and the 30 s watch rolls back regressions (RULEBOOK N-6).
- Only the P4.5 loop turns it on, and only when `config/loop.yaml` says `mode: V2` **and** `evaluation: true`. The loader refuses V2 without `evaluation: true`. The API never turns it on.
- Each action applied this way carries the note `V2: applied without the twin` and the twin's verdict in the audit log, so the H2 analysis can see what the twin would have blocked.
- Allowed on the emulated testbed only (decisions Q2: there is no real network in this project).

## Addendum (2026-10-09, code review): experiment harnesses

Two experiment scripts also act outside the normal operator flow. Both are CLI tools run by Abhishek on the emulated testbed, never reachable from the API, and both are logged in the executor's ledger:

- **`experiments/check_rollback.py`** (P4.4 Done when "deliberate bad action rolled back") records an accepted verdict for an action the twin would reject, then approves it as `rollback-check`. That is the point of the check: it stands in for a twin miss, so the rollback path can be shown on the live testbed.
- **`experiments/validation_actor.py`** (P3.5 validation batch) approves, as `validation-batch`, the **medium**-impact actions of a set the twin accepted. It never approves a high-impact action: a set containing one is skipped (`batch_approvals`, tested), because PROJECT_PLAN §8 says high impact always needs a real operator.

## Addendum (2026-10-10, P5.5/P5.6 code review): GenAI evaluation harnesses

Two more evaluation harnesses build the API in-process with feature flags (RULEBOOK B-5) switched on whatever `config/*.yaml` says, because the features are measured before their flags may be turned on (M3). Neither can change the network: they hold no operator token, the copilot has no `apply_action`, and `apply` in the HTTP backend only proposes (decision P5.5-A).

- **`experiments/genai_actor.py`** (P5.5/P5.6 live eval, `make genai-batch`) turns on the twin simulator, the alert monitor and `POST /chat` for the batch run it plays alongside. Every verdict lands in that run's ledger (`<run_dir>/actions.db`); `make genai-live` counts them for the Phase 5 exit gate.
- **`experiments/analysis/rca_eval.py`** (P5.6 replay eval) turns on the twin simulator over a replayed data/v1 run; its executor has an actuator that refuses to apply anything.

Results from these harnesses are reported as coming from evaluation runs with the flags forced on.

## Consequences

- **Positive:** H2 is measured, not estimated. The audit log of a V2 run shows each action the twin would have rejected next to what it actually did to the KPIs.
- **Negative:** the safety rule has one written exception. It is narrow (one config combination, evaluation only), tested, and visible in every affected audit entry.
