---
title: "Revision Report: Google Deep Review rounds"
subtitle: "A Twin-Gated Control Loop for Campus Wi-Fi (IEEE conference paper)"
---

# How to read this report

For every round it lists **each review comment**, the **modification made** in response (with
the place in the paper and the files or experiments that changed), and the **PDF that was
uploaded**. A comment that was not acted on, or only partly, says why. The comments are kept
word for word in `round1_deep_review.md` (each given an ID such as I2.1 there: W = weakness,
I = potential issue, M = minor correction); this report refers to those IDs.

| Round | Uploaded PDF | Comments | Fully addressed | Partly (the rest declined, with reason) |
|---|---|---|---|---|
| Draft (before review) | `round0_draft/paper_draft_v0.pdf` | n/a | n/a | n/a |
| Round 1 | `round0_draft/paper_draft_v0.pdf` (revised as `paper_rev1.pdf`) | 27 | 15 | 12 |
| Round 2 | `paper_rev1.pdf` (revised as `paper_rev2.pdf`) | 30 | 17 (+1 explained) | 12 |
| Round 3 | `paper_rev2.pdf` (revised as `paper_rev3.pdf`) | 28 | 12 (+1 not done, cosmetic) | 15 |
| Round 4 (final) | `paper_rev3.pdf` (revised as `paper_rev4.pdf`, the final draft) | 30 | 14 (+1 explained) | 15 |

Two complete review and revision rounds are required before submission; a third is recommended.
Each reviewed version is kept unchanged (`round0_draft/` to `round3_draft/`: source and PDF); the revision is the
current `paper/`.

# Round 1

**Uploaded:** `round0_draft/paper_draft_v0.pdf` (the draft). **Revision:** `paper_rev1.pdf`
(7 pages; the draft had 6). Every new number in the paper is generated from the recorded runs
(`make paper`), with new unit tests.

## What the review found that was right

- The count of harmful actions applied after an accepted verdict was **38 and should be 41**
  (the three failed rollbacks were left out: 21 in V2 and 20 in V3); the rollback failure rate is **3 of 43 attempted rollbacks**,
  not 3 of 117 applied actions (I3.2).
- The paper claimed the twin "accounts for" the reconnection cost of a steer. It does not
  (it predicts steady state; the watch ignores the first 10 s). Corrected (I2.6).
- The forecaster and detector do not feed the heuristics' proposals. Corrected in text and
  Fig. 1 (I2.6).
- "Validated against the testbed" and "needs no training data" were too strong (I1.2, I3.6).
- H2 was concluded to "hold" on a count above zero. It now holds only in its weak form (I3.1).

## What the review got wrong, or what the data answers

- **Eq. (6) is not a typo** (I2.1, W1). The code evaluates the disjunction; the rule as
  written agrees with the recorded verdict of all 114 resolved actions of V2 and V3. We tried
  the stricter rules on the same recorded predictions of V2 (the only variant that applies
  rejected actions too; pooling V3, which applies accepted actions alone, would bias the rates
  against the twin): rejecting any predicted regression above 5% would stop only 4 of 23
  harmful actions (and 4 of 38 that were kept); the reviewer's conjunction stops 4 of 23 and
  6 of 38. So the leak is in the prediction, not the rule (new Table IV).
- The reviewer's Fisher test (p = 0.29) used 61 twin-accepted V2 actions; 61 is all resolved V2
  actions. With the correct 58 the one-sided p is 0.32 (not significant either way).
- Fig. 2's whiskers are not inconsistent with Table II: they are truncated at the KPI's physical
  bounds on purpose (loss 0 to 100%); the caption now says so (M3.2).
- "Fixing the tracked cohort by station identity" (I3.3) is already how the cohort is defined;
  the text now says so.

## Per comment

| ID | Comment (short) | Result | Modification, and where | Files, experiments |
|---|---|---|---|---|
| W1 | Permissive rule (or), unvalidated non-throughput KPIs | Partly | Sec. VII-B: rule confirmed as implemented (114 of 114 verdicts); stricter rules tried (Table IV); closed-loop error of all four KPIs reported (median error vs live: throughput 56.7%, latency 70.5%, loss 57.2%, against 46.5/62.3/50.3% for "nothing changes"). **Not done:** changing the verifier's rule (a safety threshold: needs an ADR and approval, and the data shows it would not help) | `experiments/paper_build.py` (`_verifier_numbers`, `table_rules`), tests |
| W2 | Circular validation; Eq. (3) simplifications; Bianchi, Heusse, RouteNet-Fermi | Partly | Sec. IV-A: circularity, load independence and the tc mechanism stated; Eq. (3) framed as a fitted surrogate with its 15.8 ms cap and the p95 mapping; Sec. II: Bianchi, Heusse, RouteNet-Fermi cited and the fluid model justified; Sec. VIII lists them. **Not done:** replacing the model with a CSMA/CA Markov model or a GNN (a different paper) | `main.tex`, `references.bib` |
| W3 | Seed reuse, unattended V3, censoring, t intervals | Partly | Per-seed values and recovered-run counts given; intervals truncated and explained; limitations strengthened. **Not done this round:** a campaign on fresh seeds (about 6 h of VM time) and an auto-approving V3 (a new campaign and an executor change). Both are listed as the next experiments | `main.tex`, `paper_build.py` (`_run_numbers`) |
| W4 | Prior art: MAPE-K, IBN, NetConfEval, twin standards, roaming | Partly | Sec. II: Kephart and Chess (MAPE-K), RFC 9315, NetConfEval, Batfish, VeriFlow, IEEE 802.11k/v/r added. **Not added:** Zhou 2024 (an IETF draft), NetIntent 2025, Net2d-LLM 2025: their bibliographic details could not be checked, and we do not cite what we cannot verify | `references.bib` |
| I1.1 | H1 wording and censored baseline | Fixed | Sec. I: H1 now covers all three disruptions and states that a run that never recovers counts at its end; Eq. (5) takes the minimum with the run end; recovered-run counts (0, 6, 3 of 9) added | `main.tex` |
| I1.2 | "Needs no training data" vs calibration | Fixed | Sec. II: "no neural training, but a few parameters are calibrated on the target testbed" | `main.tex` |
| I1.3 | Missing prior art (wired verifiers; Bianchi; 802.11k/v/r) | Fixed | Sec. II (see W2, W4); V1 with native steering named as a further baseline not evaluated | `main.tex` |
| I2.1 | Or vs and in Eq. (6) | Partly | See W1: the code is the disjunction; stated next to Eq. (6) and tested on the recorded actions. Rule not changed | `main.tex`, Table IV |
| I2.2 | Circularity; load-independent interference | Partly | Sec. IV-A and VIII: stated, with the tc mechanism. **Not done:** weighting by the interferer's utilization (a model change; future work) | `main.tex` |
| I2.3 | Little's law, 15.8 ms cap, p95 mapping, fixed s, priority queues | Partly | Sec. IV-A: Eq. (3) is a calibrated surrogate (s and K fitted to the measured plateau), cap stated (computed from the configuration), recovery uses measured latency, p95 defined (95th percentile over the affected video flows). **Not done:** a different delay model | `main.tex` |
| I2.4 | Set vs per-proposal semantics; watch concurrency; LLM entry | Fixed | Sec. V and Alg. 1 caption: proposals are verified and applied one at a time with their own watch (interactions within a tick not simulated, stated); an intent's actions are verified jointly and applied only by an operator's call, never by the loop | `main.tex` (checked against `api/loop.py`) |
| I2.5 | Watch ordering, liveness precondition, abort condition | Partly | (S4): scope of live KPIs and the noise floor defined; Sec. VIII states the two fixes. **Not done:** implementing them in the executor (outside this task) | `main.tex` |
| I2.6 | Reproducibility details | Partly | Added: scope and invariance of Jain, J = 1 convention, base loss, web-fetch fraction, bulk demand, residual clamp, utilization definition, log-distance model, the reconnection claim corrected, forecaster role corrected. **Not expanded:** the policy compiler's mapping rules (no space; documented in the repository) | `main.tex` |
| M2.1 | d vs d_ij | Fixed | Eq. (1) text | `main.tex` |
| M2.2 | Sum placement; meaning of the precedence relation | Fixed | The relation is defined; the sum is rewritten | `main.tex` |
| M2.3 | J when no clients | Fixed | Convention J = 1 | `main.tex` |
| M2.4 | Eq. (5) empty set | Fixed | Minimum with the run end | `main.tex` |
| I3.1 | H2 holds: threshold, sensitivity, Fisher | Fixed | H2 stated in its weak form; verdict "holds only in its weak, existential form"; V2: 2 of 23 harmful actions rejected, 21 missed (V3 applied only accepted actions, 20 of them harmful); V2: harm 2 of 3 (twin-rejected) vs 21 of 58 (twin-accepted), Fisher p = 0.32 | `main.tex`, `paper_build.py` |
| I3.2 | Harmful counts; Tables I and III | Fixed | 41 harmful actions applied after an accepted verdict (21 V2, 20 V3); 3 of 43 attempted rollbacks failed; Table I says V2 also watches and rolls back; Table III caption explains V2's shadow verdicts | `main.tex` |
| I3.3 | Unattended V3; pre-disruption steering; liveness ablation | Partly | Confound stated where V2 and V3 are compared; cohort definition clarified. **Not done:** the auto-approving V3 and the liveness ablation (new runs) | `main.tex` |
| I3.4 | Seed leakage | Partly | Limitation made specific (calibration and evaluation runs are separate, the controller acts, V1 acts not at all; fresh seeds named as the next campaign). **Not done this round:** fresh seeds 45 to 47 (about 6 h on the VM, to be run by the authors) | `main.tex` |
| I3.5 | Student-t at n = 3; censoring | Partly | Caption and Sec. VI explain the intervals; per-seed values for the failure cases; recovered-run counts. **Not done:** a median and range table | `main.tex` |
| I3.6 | Unvalidated latency and loss; LLM identifiers | Fixed | Contribution (ii) qualified; closed-loop error for all four KPIs; models named (`gpt-oss:120b-cloud`, `qwen2.5:3b`); 0 repairs in 60 calls | `main.tex`, `paper_build.py` |
| M3.1 | The 0.8 for Jain | Fixed | "the 0.8 fairness target of the problem statement" | `main.tex` |
| M3.2 | Fig. 2 whiskers vs Table II | Explained | Whiskers are truncated at the physical bounds by design; caption and Table II caption say so | `main.tex` |
| M3.3 | Fig. 3 marker overlap | Fixed | Wider jitter and transparency | `paper_build.py` |
| I4.1 | Feasibility of suspending the watch | Fixed | Sec. VIII: suspension only on verifiable infrastructure events, never on any anomaly | `main.tex` |

## Not done, and what it needs (for round 2 or the next paper)

1. A campaign on fresh seeds (`make campaign MODE=V1`, `V2`, `V3` with new seeds in
   `experiments/batch_eval_v*.yaml`): about 6 hours of VM time.
2. An auto-approving V3 (operator delay 15 to 30 s): a small executor and batch change plus
   one more campaign.
3. A rollback that avoids a failed AP and a watch that stops on an AP going silent: a change in
   `controller/executor/`, with tests, then a re-run of the AP-failure scenario.
4. Validating the twin's latency and loss predictions against the testbed.

# Round 2

**Uploaded:** `paper_rev1.pdf` (the round-1 revision, 7 pages). **Revision:** `paper_rev2.pdf`
(8 pages; the references take the last page). The reviewed revision is kept unchanged in
`round1_draft/`. The comments are in `round2_deep_review.md` (30 of them, each given an ID).
The citation checker passed all 19 references it was given, among them the fifteen we added
in round 1. Every new number is generated from the recorded runs (`make paper`), with new unit
tests; `make check` passes (1676 tests).

## What the review found that was right

- **H1 and H2 were not falsifiable as stated** (I1.1, I1.2). H1 is now decided on the capped
  recovery times and is **not met** (V3 faster by 8, 17 and 0%); the cap can only understate
  V1's true time, but in the interference scenario V3 itself never recovered, so nothing
  supports H1 there. H2 now asks that the twin rejects a majority of V2's harmful actions and
  is **not met** (2 of 23); the weak form (at least one) is reported as trivially true.
- **The H3 claim "no invalid configuration reaches the network" is an architectural
  property, not a result about the LLM** (I1.3). It is no longer part of H3.
- **Eq. (6) had an unclear baseline and no formula for δ** (I2.1). The baseline is the
  twin's own simulated no-action outcome f(s, ∅), not the live measurement; the formula, the
  zero-baseline convention and the flows compared are now written out.
- **Eq. (2) had no solution when a queue is not saturated** (I2.2). Corrected, and the way
  the demand λ is rebuilt from telemetry (received rate ÷ (1 − loss) for video) and how web
  flows enter the sharing are stated.
- **Load-independent interference means steering cannot relieve a co-channel AP** (I2.4).
  Stated: only a channel change or taking an AP down changes C_i.
- **Algorithm 1 can apply up to three proposals per tick with concurrent watches, an approved
  action is applied without re-verification, and a rollback does not re-check (S1)** (I2.3).
  All three are true of the code; stated in Sections IV-B and V.
- **The 15.8 ms latency ceiling means the twin cannot see a latency above it** (I2.1), and
  its p95 is a percentile over stations, not packet delays. Stated.
- **A table of means with Student-t intervals misdescribes three seeds** (W3, I3.4). Table II
  and Fig. 2 now show the mean and the smallest and largest of the three seeds.
- Our sentence "most harmful actions had no predicted regression" was loose (I3.2): 12 of
  V2's 23 harmful actions had none, 7 a regression below 5% and 4 above. Replaced by the counts.
- The 0.8 target for Jain's index was not introduced (M2.5); the 1000 ms value was not
  explained (M3.2); the twelve calibration runs were not itemised (M3.1). Fixed.

## What the review got wrong, or what the data answers

- **"The Jain clause lets steers bypass the flow checks" (I2.1.3)** is true of the rule, but
  it is not what let the harmful actions through: only **1 of the 41** harmful actions applied
  after an accepted verdict was accepted on Jain's index alone (new count, Sec. IV-B). The
  others were predicted to improve a flow KPI.
- **"Any action that keeps the AP up automatically predicts a latency improvement against live
  measurements above 16.7 ms" (I2.1.2)** does not happen: the baseline of δ is the twin's own
  simulated baseline, not the live measurement. What is true is that both sides are capped, so
  a latency change cannot show once both saturate (stated).
- **"V1 recovers in 0 of 9 runs because it never roams" (I3.5)** is right for the flash crowd
  and the interference scenario, but in the AP failure V1 does re-associate, its loss and
  latency are fine, and it still counts as never recovered: its p95 latency stays near 18 ms,
  so, as far as the data show, it is the utilization condition (the busiest surviving AP under
  0.8) that is not met. Stated in Sec. VII-A.
- **Algorithm 1 notation (M2.4):** the source already writes the predicted vector in bold
  (`\hat\KPI`); no change.
- **Fisher test (I3.4.3):** its non-independence is already stated in round 1; the caveat is
  now in the text next to the p-value as well.

## Per comment

| ID | Comment (short) | Result | Modification, and where | Files, experiments |
|---|---|---|---|---|
| W1 | V2 vs V3 confounds twin and operator gate | Partly | Abstract and Sec. I: V3 combines the twin with an operator gate, and the loop runs a heuristic optimizer while the LLM is tested apart; Sec. VIII: the clean ablation is an auto-approving V3 **without** delay or a V2 that keeps the operator gate (a human-scale delay would confound it again). **Not done:** running either (about 2 h of VM time each) | `main.tex` |
| W2 | Circular interference; simplified surrogates; Akgun, RouteNet-Fermi, Poorzare | Partly | Sec. IV-A: consequence of the load-independent cap; ceiling and station-level p95 of Eq. (3) stated. **Not done:** validating against physical contention or a learned surrogate on the calibration data (a different study). **Not added:** Akgun 2024 and Poorzare 2025: their details could not be checked here (RouteNet-Fermi is already cited) | `main.tex` |
| W3 | n = 3, seed reuse, t intervals, Fisher, no finite V1 baseline | Partly | Ranges instead of intervals (Table II, Fig. 2, Sec. VI); Fisher caveat. **Not done:** fresh seeds (about 6 h), a V1 with 802.11k/v/r roaming (now named in Sec. VIII with the reason it matters) | `paper_build.py` (`kpi_range`), `main.tex` |
| W4 | Novelty; LLM benchmark scope; adversarial intents | Partly | H3 reduced to translation accuracy; scope of the 30 intents against NetConfEval explained (Sec. II); Sec. VIII states the limit. **Not done:** a standard benchmark or adversarial intents. **Not added:** the other suggested references (unverified) | `main.tex` |
| I1.1 | H1 falsifiability under censoring | Fixed | Sec. I: H1 on capped times; Sec. VII-A: not met (8, 17, 0%), and why the cap favours V3 | `main.tex`, `paper_build.py` (`HoneCapped`) |
| I1.2 | H2 existential, nearly vacuous | Fixed | Sec. I: H2 asks for a majority; Sec. VII-B: not met | `main.tex` |
| I1.3 | H3 mixes accuracy with an architectural invariant | Fixed | Sec. I; Sec. II (scope against NetConfEval) | `main.tex` |
| I1.4 | "never roam" vs "re-associate" | Fixed | Sec. II: no load-driven roaming, but re-association when the AP goes down | `main.tex` |
| I2.1 | δ baseline, zero baseline, 15.8 ms ceiling, Jain clause | Partly | Sec. IV-B: baseline f(s, ∅), formula, ±∞ convention, flows compared, Jain's effect (1 of 41); Sec. IV-A: ceiling and station-level p95. **Not done:** scaling s with C_i or separating Jain from the flow KPIs (model changes) | `main.tex`, `paper_build.py` (`HarmJainOnly`) |
| I2.2 | Eq. (2) unsaturated, demand, queues, web | Fixed | Sec. IV-A: Eq. (2) with min(R_q, Σλ), R_q by allocated rates, λ rebuilt as received ÷ (1 − loss), default best-effort queue, web in ρ_q | `main.tex` |
| I2.3 | Multi-action ticks, stale approvals, rollback without S1 | Partly | Sec. IV-B (S3, S4) and Sec. V: stated. **Not done:** changing the loop or the executor | `main.tex` |
| I2.4 | Load-independent cap makes steering useless | Fixed | Sec. IV-A | `main.tex` |
| I2.5 | Scope, gating, heuristic rules, policy compiler | Partly | Flows compared; S3 gating of unvalidated medium-impact types; steering (one proposal per target, floor(0.3 n) stations, strongest signal) and channel (least distance-weighted co-channel load). **Not expanded:** the policy compiler's mapping rules (no space; in the repository) | `main.tex` |
| M2.1 to M2.3, M2.5 | Wording of scenarios, R_q formula, U and t_d, the 0.8 target | Fixed | Sec. III, IV-A, IV-B, VII-A | `main.tex` |
| M2.4 | Bold k̂ in Algorithm 1 | Explained | Already bold in the source | none |
| I3.1 | Confound, framing, matched delay | Partly | See W1 | `main.tex` |
| I3.2 | Latency and loss unvalidated; Table IV threshold breakdown; learned surrogate | Partly | Predicted regressions counted: 11 of 23 any, 4 of 23 above 5%. **Not done:** held-out latency and loss error (the validation scores throughput only; extending it is a code change), a learned surrogate | `paper_build.py` (`HarmAnyRegress`), `main.tex` |
| I3.3 | Failed rollbacks collide with the scheduled fault | Partly | Sec. VII-B: the failed rollbacks and any steer whose watch overlapped the failure are counted harmful although the failure caused the regression. **Not done:** separating them in Tables III and IV (needs run-relative times in the ledger) | `main.tex` |
| I3.4 | Seed reuse, t intervals, Fisher | Partly | See W3. **Not done:** fresh seeds; an offline test of the verifier on scripted unsafe actions | `main.tex`, `paper_build.py` |
| I3.5 | Degenerate V1; H3 scope and fate of the LLM actions | Partly | V1 AP-failure explained; the local model's 9 misses are compound intents that pass the schema (a semantic error nothing downstream catches); the 6 audited actions are suggestions with a verdict, none applied. **Not done:** roaming V1, adversarial intents | `main.tex` |
| M3.1 | The 12 calibration runs | Fixed | Sec. VI: the three scenarios and a disruption-free one, three seeds | `main.tex` |
| M3.2 | `(0)` in Table II; 1000 ms | Fixed | `(0)` always shown; 1000 ms is the probe's value for a ping with no reply | `paper_build.py`, `main.tex` |
| M3.3 | Table III accounting | Fixed | Caption gives the partition (23 harmful + 38 kept; the 3 rejected were 2 harmful and 1 kept; 41 = 21 + 20). Not put in the cell itself | `main.tex` |
| M3.4 | Fig. 3 overlap | Fixed | Wider offset between the three seeds | `paper_build.py` |
| M3.5 | Comma splice in Sec. VIII | Fixed | Sentence rewritten | `main.tex` |
| I4.1 | Limitations omit V1 roaming and H3 scope | Fixed | Sec. VIII | `main.tex` |
| I4.2 | A watch blocks the loop during a fault | Fixed | Sec. VIII: cancelling a watch on an infrastructure event should also release the loop | `main.tex` |

## Not done, and what it needs (for round 3 or the next paper)

1. A campaign on fresh seeds (`make campaign MODE=V1|V2|V3`, new seeds): about 6 hours of VM time.
2. An auto-approving V3 without delay, or a V2 that keeps the operator gate: a small executor
   and batch change plus one campaign.
3. A V1 with native 802.11k/v/r steering, to give V1 a finite recovery time.
4. A rollback that avoids a failed AP and a watch that stops on an AP going silent, with the
   loop released: a change in `controller/executor/`, with tests.
5. Validating the twin's latency and loss predictions, and separating exogenous collisions in
   the ledgers.

# Round 3

**Uploaded:** `paper_rev2.pdf` (the round-2 revision, 8 pages). **Revision:** `paper_rev3.pdf`
(8 pages). The reviewed revision is kept unchanged in `round2_draft/`. The comments are in
`round3_deep_review.md` (28 of them, each given an ID). This round found no new problem with
the numbers: the reviewer re-derived the counts of Tables II to IV, H1's percentages and the
Fisher p-value and found them consistent. The citation checker again passed all 19 references.
Every new number is generated from the recorded runs (`make paper`), with new unit tests.

## What the review found that was right

- **The abstract's 4.5% was not exact** (M1.1): it is the error over all 586 held-out
  situations; 4.0% is the steady-state error. Both are now given.
- **ap1 and ap4 start every run at 3.45 Mbit/s, not 4.6** (I2.5): they share channel 1 at 50 m.
  Now stated (generated from the configuration).
- **The twin cannot see a transmit-power step** (I2.6): it is recorded in its state, but
  nothing it computes depends on it, so it predicts no change and accepts it (a reroute is
  always rejected, the campus having one path). True of the code; now stated. The heuristics
  never propose either, so no result depends on it.
- **The sign of δ when the baseline is zero was not written out** (I2.3). Now: +∞ for an
  improvement, −∞ for a degradation (a loss appearing where there was none). This is what the
  code does.
- **Steering details a reader needs** (I2.1, I2.6): the budget of ⌊0.3 n⌋ stations is shared
  by the target APs, so no station is proposed twice; an AP with fewer than four clients sheds
  none; the channel set is 1, 6, 11 over the APs that are up, ties keep the current channel,
  then the lowest. All stated from `ml/optimizer/heuristics.py`.
- **What happens at 100% loss** (I2.6): a video flow with no throughput or 100% loss falls
  back to its class's configured rate, and loss is capped at 100%. Stated.
- **Several presentation points** (M2.1, M2.2, M2.3, M2.5, M3.1 to M3.5): ≺ defined where first
  used; the delay constant renamed σ so that s is only the twin state; an unrecovered run is
  assigned T_end − t_d; the stress window for Jain's index is [t_d, T_end]; "the course problem
  statement" removed; Jain's index "a function of client counts"; the table row renamed
  "Rejected, not applied"; the grammar slip fixed.
- **The silent semantic misses of the local model** (I3.6, W5): the paper now says the schema,
  compiler and executor guarantee syntax and bounds, not fidelity to the operator's goal.

## What the data answers

- **"A scheduled fault contaminates the harm labels" (I3.2, W4).** Tested, and answered with
  data: from the run start times in the telemetry and the ledgers' timestamps, the scenario's
  disruption fell within the 30 s before or after **18 of the 43** harmful actions of V2 and V3
  (the window the watch compares; the 3 failed rollbacks are among them), so those labels are
  partly the fault's. It does not explain the misses: leaving them out, the twin still rejected
  only **2 of the 15** remaining harmful actions of V2. New numbers in Sec. VII-B. (A first
  version counted only watches that began before the onset: 4; the reviewer agent showed that
  the baseline window matters too.)
- **"Up to three actions in one tick make the watches unattributable" (I2.1, W4).** In the
  whole campaign only **2 ticks** applied more than one action (new number, Sec. V). Each
  action is watched and rolled back on its own measurement.
- **"Intent set not described" (I3.6).** Of the 30 intents, 17 ask for one objective in one
  class and 13 are compound (a second objective, a constraint or two classes). Both models
  translated all 17 simple ones; the cloud model all 13 compound ones and the local model 4.
  The 9 local misses are therefore all compound. Stated in Sec. VII-C.

## Per comment

| ID | Comment (short) | Result | Modification, and where | Files, experiments |
|---|---|---|---|---|
| W1, I3.1 | V2 vs V3 confounds twin and operator gate | Partly | Unchanged from round 2 (stated upfront; ablation named in Sec. VIII). **Not done:** running V3 auto-approving or V2 gated (about 2 h of VM time each) | none |
| W2 | Circular contention model; 15.8 ms cap; no latency/loss validation | Partly | Already stated in round 2; Sec. IV-A adds the 3.45 Mbit/s start of ap1 and ap4. **Not done:** physical contention, a learned surrogate, latency and loss validation | `main.tex` |
| W3, I3.3 | Seed reuse, n = 3, no finite V1 | Partly | Ranges (round 2). **Not done:** fresh seeds (about 6 h), a roaming V1 | none |
| W4, I3.2 | Rollbacks across a scheduled fault; permissive rule; same-tick states | Partly | Harmful actions counted by whether the disruption fell in their baseline or watch window (18 of 43), ticks with several actions counted (2); Sec. V states how each action is watched. **Not done:** the executor changes (re-check S1 on rollback, release the loop, re-verify approvals) and one action per tick | `paper_build.py` (`run_starts`, `_fault_numbers`), `main.tex` |
| W5, I3.6 | LLM scope; semantic misses | Partly | Sec. I: property of syntax and bounds; Sec. VII-C: simple vs compound split. **Not done:** a standard benchmark, adversarial intents, running the 9 misses through the verifier | `paper_build.py` (`_is_compound`), `main.tex` |
| M1.1 | Abstract: 4.5% | Fixed | Abstract gives 4.5% and 4.0% in steady state | `main.tex` |
| I2.1 | Same-tick proposals, bound, attribution | Partly | Sec. V: shared budget, no station twice, none below four clients, own watch per action, 2 multi-action ticks. **Not done:** verifying same-tick proposals jointly or one action per tick | `main.tex` |
| I2.2 | Rollback without S1; stale approvals | Partly | Already stated; the fixes (re-verify an approval, re-check S1, release the loop) are now listed together in Sec. VIII. **Not done:** implementing them | `main.tex` |
| I2.3 | Disjunction; Jain bypass; ±∞ sign | Partly | Sign written out. The rule is unchanged (a safety threshold: ADR and approval needed); Table IV already tests the conjunction (4 of 23 harmful stopped) and Jain's share is 1 of 41 | `main.tex` |
| I2.4 | Latency ceiling; cumulative load; fixed σ; station-level p95 | Partly | Ceiling and station-level p95 stated (round 2). **Not done:** a different delay model | none |
| I2.5 | Load-independent cap; 3.45 Mbit/s | Fixed | Sec. III-A: each of ap1 and ap4 starts at 3.45 Mbit/s | `paper_build.py` (`CfgSharedCapacity`), `main.tex` |
| I2.6 | reroute and tx-power mappings; 100% loss; parameters | Partly | Transmit power stated as invisible to the twin and reroute as always rejected; 100% loss fallback and cap; path-loss parameters; positions, demands and noise floors pointed to `config/`; channel set and tie-break. **Not expanded:** the policy compiler, the forecaster and detector hyperparameters | `main.tex` |
| M2.1 | ≺ defined late | Fixed | Eq. (2) text | `main.tex` |
| M2.2 | Symbol s twice | Fixed | Delay constant is σ | `main.tex` |
| M2.3 | Unrecovered run is T_end − t_d | Fixed | Sec. IV-B | `main.tex` |
| M2.4 | Index the scalar KPIs | Not done | Cosmetic; k is used for both the KPI and its index in the source of every equation, and changing it would touch all of Sec. IV | none |
| M2.5 | Channel sum over APs that are up | Fixed | Sec. V | `main.tex` |
| I3.4 | No roaming V1; decouple the two recovery conditions | Partly | As in round 2. **Not done:** a roaming V1; reporting the time to each condition separately (needs the recovery rule split in `experiments/analysis`) | none |
| I3.5 | Latency and loss not validated offline | Partly | As in round 2. **Not done:** extending the twin validation to latency and loss | none |
| M3.1 | Stress window | Fixed | Sec. VI: from t_d to the end of the run | `main.tex` |
| M3.2 | "Course problem statement" | Fixed | Rephrased | `main.tex` |
| M3.3 | Table III row for V2 | Fixed | Row now "Rejected, not applied"; the caption gives the partition | `paper_build.py`, `main.tex` |
| M3.4 | "a count" | Fixed | "a function of client counts" | `main.tex` |
| M3.5 | "1 kept ones" | Fixed | Grammar | `main.tex` |

## Not done, and what it needs (for the next paper)

1. A campaign on fresh seeds: about 6 hours of VM time.
2. An auto-approving V3 without delay, or a V2 that keeps the operator gate: a small executor
   and batch change plus one campaign each.
3. A V1 with native 802.11k/v/r steering, and recovery reported per condition.
4. The executor fixes: re-verify an approved action, re-check (S1) before a rollback, release
   the loop when a watch is cancelled by an AP going down, one action per tick.
5. Latency and loss validation of the twin, and a different delay model.

# Round 4 (final)

**Uploaded:** `paper_rev3.pdf` (the round-3 revision, 8 pages). **Revision:** `paper_rev4.pdf`,
the final draft (8 pages). The reviewed revision is kept unchanged in `round3_draft/`. The
comments are in `round4_deep_review.md` (30 of them, each given an ID). As in round 3, the
reviewer re-derived the numbers of Tables II to IV, H1's percentages and the Fisher p-value and
found them consistent, and the citation checker passed all 19 references. Every new number is
generated from the recorded runs (`make paper`), with new unit tests.

## What the review found that was right

- **A real error in Algorithm 1** (M2.5). Line 11 read "else if the verdict is accepted, queue
  for approval", so an accepted proposal that needs no approval, arriving after three actions
  had been applied in the tick, would have been queued for an operator. The code does not do
  that (`api/loop.py` applies, or skips when a rate limit stops it, and queues only what needs
  approval); the pseudocode did not match it. Corrected: queue if accepted and needs approval;
  else apply if accepted and under the per-tick limit.
- **The abstract and Section I still let a reader think the LLM drove the loop** (I1.1). Both
  now say that only the heuristic optimizer ran on the emulated network, that the LLM is
  evaluated offline, and that none of its actions was applied.
- **Several quantities were not defined well enough to reimplement** (I2.5):
  measured utilization (the bits the clients sent and received in the last interval, divided by
  C_i: at most about 1, uplink included); the configured demands (video 1.0, web 0.08, bulk
  0.394 Mbit/s); that the base loss is not subtracted when a video demand is inverted (a slight
  overestimate); the AP coordinates; the four noise floors (0.18 Mbit/s, 10.9 ms, 0.72 points,
  0.02); the flows compared for a channel change (those on the AP and on every AP sharing its
  old or new channel). All generated from the configuration.
- **The twin judged on the validated KPIs only** (I3.5). New row in Table IV: gating on
  throughput and Jain's index alone would have rejected 2 of 23 harmful and 3 of 38 kept
  actions: no better than the rule as written.
- **The disruption's share of the harm and error numbers** (I3.3). Of V2's 38 kept actions, 7
  were also judged across the disruption. Without all the tainted actions (87 remain) the
  closed-loop errors are 55.6%, 76.8% and 59.0% against 50.5%, 66.0% and 48.5% for "nothing
  changes": the same conclusion. The text also says that 43 = 23 + 20 and how it relates to
  41 = 21 + 20.
- **The seed split, the scoring rule, the 1000 ms value, the "(3 ignored)" cell, the
  event AP against the affected AP, "Four fixes"**, and the small wording points (M1.1, M2.1,
  M2.2, M2.4, M2.6, M3.1 to M3.4, M4.1) are fixed.

## What the data or the code answers

- **"Transmit power is accepted vacuously" (I2.3).** True, and now stated with the part the
  reviewer left out: it is a medium-impact action, so an operator still has to approve it; it
  is never applied on the twin's word alone.
- **"Jain's index bypasses the flow checks" (W3, I2.3).** Answered in round 2 and again here:
  1 of the 41 harmful actions applied after an accepted verdict was accepted on Jain's index
  alone, and the stricter rules, now including one on throughput and Jain alone, do no better.
- **M2.3 (parenthesis in Sec. IV-B)** reads cleanly; unchanged.
- **M2.5, bold k:** the source already writes the predicted vector in bold; no change. The
  scalar k is kept as the KPI's value and its index, as every equation of Sec. IV uses it.

## Per comment

| ID | Comment (short) | Result | Modification, and where | Files, experiments |
|---|---|---|---|---|
| W1, I3.1 | V2 vs V3 confounded; roaming V1; fresh seeds | Partly | Table I caption: V2 and V3 also differ in the operator gate, which no operator used. **Not done:** the auto-approving V3, a gated V2, a roaming V1, fresh seeds (about 2 to 6 h of VM time each) | `main.tex` |
| W2, I2.1 | Circular, load-independent contention model; 15.8 ms cap | Partly | Sec. II: the model is small on purpose, to test whether a minimal steady-state model suffices for 5 s control. **Not done:** load-dependent contention, a learned surrogate | `main.tex` |
| W3, I2.3, I2.4 | Disjunctive rule; blind rollback; paralysed loop; same-tick states | Partly | Transmit power stated as medium impact (operator approves). Rule and executor unchanged (a safety threshold and the executor are outside this task and need an ADR). The four fixes are listed together in Sec. VIII | `main.tex` |
| W4, I3.6 | LLM evaluated offline; twin not tried on the 9 misses; no adversarial intents | Partly | Sec. VI: the scoring criterion. Sec. VIII: the misses were not run through the verifier. **Not done:** categorising them and running them through the twin (needs the compiler's actions replayed on recorded states) | `main.tex` |
| I1.1 | Title and abstract frame a unified loop | Fixed | Abstract: only the heuristic optimizer ran on the network; the LLM is offline; none of its actions applied | `main.tex` |
| I1.2 | Thresholds 30% and 20 of 30 unjustified; why V1 | Fixed | Sec. I: the thresholds are targets we set, the second a low floor (H3 weak by design); V1 is the baseline without control; roaming not emulated | `main.tex` |
| I1.3 | Why a minimal model; verified-LLM literature | Partly | Sec. II as above. **Not added:** the verified-LLM references suggested (details could not be checked) | `main.tex` |
| M1.1 | Colons after H1 to H3 | Fixed | Sec. I | `main.tex` |
| I2.2 | Ceiling, priority starvation, station-level latency, transients | Partly | Station-level latency "understates the delay of a station's lower-priority flows" added; ceiling already stated. **Not done:** a different delay model | `main.tex` |
| I2.5 | Utilization, demands, coordinates, flow scope, parameters | Partly | All the quantities listed above stated. **Not expanded:** the policy compiler's mapping rules and the forecaster and detector hyperparameters (in `config/`) | `paper_build.py` (`CfgVideo`, `CfgWebRate`, `CfgApPlaces`, `CfgFloor*`), `main.tex` |
| M2.1, M2.2 | Unit; theta_q when demand fits | Fixed | Sec. III-A, IV-A | `main.tex` |
| M2.3 | Parenthesis in Sec. IV-B | Explained | Reads cleanly | none |
| M2.4 | Period after Eq. (6); k overloaded; capitals after (S3), (S4) | Fixed | The period and the capitals. The overloading of k is kept (see above) | `main.tex` |
| M2.5 | Algorithm 1 line 11 | Fixed | Pseudocode now matches `api/loop.py` | `main.tex` |
| M2.6 | Tie-break wording; long sentence; Policy | Fixed | Sec. V: tie-break rewritten, the sentence split; `Policy` is the schema's name, kept in code font | `main.tex` |
| I3.2 | Seed reuse; which seed is which split | Partly | Sec. VI: 42, 43 and 44 are the training, validation and test split. **Not done:** fresh seeds | `main.tex` |
| I3.3 | Disruption inside the watch; kept actions; errors without them | Fixed | Sec. VII-B: 7 of 38 kept actions tainted too; errors without the tainted actions; 43 = 23 + 20 against 41 = 21 + 20 | `paper_build.py` (`_fault_numbers`), `main.tex` |
| I3.4 | V1 AP failure scored unrecovered; report U | Partly | Sec. VI: event AP against affected AP. **Not done:** the utilization of the surviving AP and a QoS-only recovery time (needs the recovery rule split in `experiments/analysis`) | `main.tex` |
| I3.5 | Latency and loss unvalidated; rule on validated KPIs | Partly | New row in Table IV. **Not done:** held-out latency and loss error (the validation scores throughput only) | `paper_build.py` (`ThrJain`), `main.tex` |
| M3.1 to M3.4 | "of this section"; "0.8" twice; 1000 ms footnote; "(3 ignored)" | Fixed | Sec. VI, VII-A; Table II caption; Table III cell | `paper_build.py`, `main.tex` |
| M4.1 | "Two fixes" | Fixed | "Four fixes", split | `main.tex` |

## Not done, and what it needs (for the next paper)

1. A campaign on fresh seeds (about 6 hours of VM time).
2. An auto-approving V3 without delay, or a V2 that keeps the operator gate; a V1 with native
   802.11k/v/r steering.
3. The executor fixes: re-verify an approved action, re-check (S1) before a rollback, release
   the loop when a watch is cancelled by an AP going down.
4. Latency and loss validation of the twin, a different delay model, a load-dependent
   contention model.
5. Replaying the local model's semantic misses through the verifier.

# How a round is done

1. Compile the paper (`make paper`, or on Overleaf) and upload the PDF to
   <https://research.google/deepreview/>.
2. Paste each comment into `roundN_deep_review.md` and the table above.
3. For each comment: change `paper/main.tex`; if a number, table or figure must change, change the
   code or re-run the experiment, then `make results` and `make paper` (the numbers are never
   edited by hand); if a comment needs a new experiment, record it in the last column.
4. Save the PDF that was uploaded as `paper_revN.pdf` in this folder and fill in the round's table.
5. `make submission` rebuilds `dist/Revision_Report.docx` from this file.
