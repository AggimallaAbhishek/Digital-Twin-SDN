---
title: "Revision Report: Google Deep Review rounds"
subtitle: "A Twin-Gated Control Loop for Campus Wi-Fi (IEEE conference paper)"
---

# How to read this report

For every round it lists **each review comment**, the **modification made** in response (with
the place in the paper and the files or experiments that changed), and the **PDF that was
uploaded**. A comment that was not acted on, or only partly, says why. The comments are kept
word for word in `roundN/review_comments.md` (each given an ID such as I2.1 there: W = weakness,
I = potential issue, M = minor correction); this report refers to those IDs.

| Round | Uploaded PDF | Comments | Fully addressed | Partly (the rest declined, with reason) |
|---|---|---|---|---|
| Draft (before review) | `round1/reviewed/paper_draft_v0.pdf` | n/a | n/a | n/a |
| Round 1 | `round1/reviewed/paper_draft_v0.pdf` (revised as `round1/paper_rev1.pdf`) | 27 | 15 | 12 |
| Round 2 | `round2/reviewed/paper_rev1.pdf` (revised as `round2/paper_rev2.pdf`) | 30 | 17 (+1 explained) | 12 |
| Round 3 | `round3/reviewed/paper_rev2.pdf` (revised as `round3/paper_rev3.pdf`) | 28 | 12 (+1 not done, cosmetic) | 15 |
| Round 4 (final) | `round4/reviewed/paper_rev3.pdf` (revised as `round4/paper_rev4.pdf`, the final draft) | 30 | 14 (+1 explained) | 15 |
| Round 5 (after the faculty guide's graphs) | `round5/reviewed/paper_final.pdf` (revised as `round5/paper_rev5.pdf`) | 39 | 22 | 17 |

Two complete review and revision rounds are required before submission; a third is recommended.
Each round has its own folder, `round1/` to `round5/`: `review_comments.md` (the comments, word
for word), `reviewed/` (the version that was uploaded, unchanged: source and PDF) and
`paper_revN.pdf` (the revision the round produced). The latest revision is also `paper_final.pdf`
next to this report, and its source is the current `paper/`.

# Round 1

**Uploaded:** `round1/reviewed/paper_draft_v0.pdf` (the draft). **Revision:** `round1/paper_rev1.pdf`
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

**Uploaded:** `round2/reviewed/paper_rev1.pdf` (the round-1 revision, 7 pages). **Revision:** `round2/paper_rev2.pdf`
(8 pages; the references take the last page). The reviewed revision is kept unchanged in
`round2/reviewed/`. The comments are in `round2/review_comments.md` (30 of them, each given an ID).
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

**Uploaded:** `round3/reviewed/paper_rev2.pdf` (the round-2 revision, 8 pages). **Revision:** `round3/paper_rev3.pdf`
(8 pages). The reviewed revision is kept unchanged in `round3/reviewed/`. The comments are in
`round3/review_comments.md` (28 of them, each given an ID). This round found no new problem with
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

**Uploaded:** `round4/reviewed/paper_rev3.pdf` (the round-3 revision, 8 pages). **Revision:** `round4/paper_rev4.pdf`,
the final draft (8 pages). The reviewed revision is kept unchanged in `round4/reviewed/`. The
comments are in `round4/review_comments.md` (30 of them, each given an ID). As in round 3, the
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

# Faculty guide's review (after round 4)

The faculty guide reviewed the project and `round4/paper_rev4.pdf` and asked: *"You need to add 12-14
significant graphs. That will enhance the quality."*

| Comment | Result | Modification, and where | Files, experiments |
|---|---|---|---|
| Add 12 to 14 significant graphs | Fixed | 14 graphs added (16 plots and the architecture diagram, 17 figures; 8 to 12 pages), each cited where its result is discussed. Sec. III: the campus with each scenario's event and the flash crowd's walkers (Fig. 1). Sec. IV: the twin's capacity and delay curves, drawn with its own code (Fig. 3). Sec. VII-A: the affected AP's utilization, the affected flows' p95 video latency and loss, and Jain's index over the run per variant (Figs. 6-9), and the clients per AP in the flash crowd (Fig. 10). Sec. VII-B: every action at the time it was proposed, by its fate (Fig. 11), the throughput change the twin predicted against the one measured (Fig. 12) and the closed-loop error distributions (Fig. 13). Sec. VII-C: the twin's offline error by case and its prediction time (Fig. 14), the intents by kind and their latency (Fig. 15), anomaly detection per scenario (Fig. 16) and forecast error per scenario (Fig. 17). No new experiment: every graph is drawn from the recorded evaluation, and every statement the new text makes about one was checked against the data | `experiments/paper_figures.py` (new), `experiments/paper_evidence.py` (new), `experiments/paper_build.py`, `paper/main.tex`, `paper/figures/`, `tests/unit/test_paper_figures.py` |

What the graphs show that the tables did not: in every flash-crowd run of V2 and V3 the first
steer, proposed at the onset, was rolled back, and every AP-failure and interference run began
with a steer that was rolled back before any disruption; the three failed rollbacks were steers
proposed shortly before the AP failure; in the flash crowd V2 and V3 bring Jain's index back to
about the 0.8 target within a few minutes (five of their six runs end above it), so their means
over the stress window miss it because of the first minutes after the onset; and the throughput
change the twin predicts bears no relation to the one measured. The revised paper is
`paper_final.pdf` (the paper as built by `make paper`).

# Round 5

**Uploaded:** `paper_final.pdf` (the 12-page paper with the guide's 14 graphs). **Revision:**
`round5/paper_rev5.pdf` (13 pages). The reviewed version is kept unchanged in `round5/reviewed/`. The
comments are in `round5/review_comments.md` (39 of them, each given an ID). The reviewer re-derived
the ledger counts of Tables III and IV, H1's percentages and the Fisher p-value and found them
exact. Every new number is generated from the recorded runs or the configuration (`make paper`),
with new unit tests; every new sentence about the data was checked against it.

## What the review found that was right

- **A wrong sentence about the flash crowd** (I4.4). The paper said that in two of the three
  seeds of V2 and of V3 the affected AP crosses 0.8 and stays below. The data: in each variant
  one seed never stays below 0.8 for more than a second; the other four cross it, some more than once; in V2's seed 42 the
  utilization never stays below 0.8 for the full 15 s hold of the recovery rule (at most 14 s in
  a row, checked per second as the rule does), and video latency spikes shorten those stretches
  further (Table II: two V2 runs and one V3 run unrecovered). Rewritten to say so. Fig. 7 draws
  the affected flows' latency, while Eq. (5) applies the limit to every video flow; the text now
  says which.
- **The H1 parenthesis was ambiguous** (I1.1): "which favours V3" now reads "the cap works
  against V3 wherever V3 recovers".
- **The 4.0% and 3.3% twin errors are for video flows only** (I4.3); the abstract and Sec. VII-C
  now say so, and why web flows, latency and loss are not scored offline.
- **The text promised traffic the scenarios do not have** (I1.2): no evaluation scenario carries
  bulk traffic (only the disruption-free calibration run does). Sec. III-A now gives the starting
  stations per AP (3, 5, 7, 5, from `config/campus_v1.yaml`) and each scenario's video
  (generated: `CfgStartClients`, `ScenVideo*`).
- **The state description was wrong in one detail** (M1.2): the twin does not read a flow's queue
  or rate limit back from telemetry; it rebuilds every flow as best effort and unlimited. Exact
  for this campaign (no QoS or rate-limit action was applied); now stated.
- **Which flows Eq. (5) uses was not stated** (I4.2): $L_{95}$ in the recovery rule covers every
  video flow in the network, per second (`experiments/analysis/time_to_recover.py`), not the
  affected flows of Table II. Now stated, as are the dead flow's latency (the probe's 1000 ms),
  the loss cap, the uncapped demand inversion, the web-fetch formula, the KPI aggregation and the
  per-AP index (I2.2, I2.3, M2.1 to M2.4).
- **The intent set is not held out from the prompt's design** (I3.4): the prompt (rules and five
  worked examples, none a test intent) was revised once after a run on the same 30 intents. Now
  stated, with how the intents were written, the compiler's mapping rules, the steering budget,
  the proposal order and that a proposal identical to one waiting for an operator is not queued twice.
- **New analyses on the recorded data** (I4.3, I4.1): Table IV gains the counts on the actions
  the disruption did not taint (15 harmful, 31 kept: rejecting every predicted regression stops 3
  of 15) and a rule in which Jain's index cannot pass the second clause alone (2 of 23 harmful,
  the same as written); the closed-loop errors are given per variant (the twin is no closer than
  "nothing changes" in V2 or in V3).
- **The small points**: seed reuse and seed 44 as the only out-of-sample seed (I3.2), the explicit
  channel-load sum, $f(s,\{p\})$, the seed sentences, the model identities, $L_{95}$, tense,
  "percentage points", the Fig. 1, 11 and 13 captions, Fig. 13's decade labels (each panel now as
  wide as the decades it spans), Fig. 14's labels grouped by class, the 129 verdicts against the 6
  LLM actions, the pooled detector precision and its 12 false alarms, references [13] and [19].

## What the data or the code answers

- **"Stranding a station on the dead AP helps recovery"** (I4.2). It lowers the surviving AP's
  utilization, but the stranded video's 1000 ms keeps $L_{95}$ above 50 ms: none of the three runs
  with a failed rollback recovered. Now stated in Sec. VII-A.
- **"Forward loss can exceed 100%"** (I2.2): the code caps it (`min(100, ...)`); the formula in
  the text now shows the cap.
- **"The first-minute steers are start-up bursts"** (I4.3): confirmed on the ledgers. All twelve
  were proposed 11 to 36 s into the run, when the video starting at 10 s briefly took the source AP
  to 0.8 to 1.0 before it settled near 0.5 to 0.65; now stated.
- **"Fig. 10 starts below 20 clients"** (I1.2): the AP rows sum to 20 at the start of every run
  (3 + 5 + 7 + 5).
- **Jain's index alone** (I2.4, W3): the new Table IV row shows that taking it out of the second
  clause changes nothing for V2.

## Per comment

| ID | Comment (short) | Result | Modification, and where | Files, experiments |
|---|---|---|---|---|
| W1, I4.1 | V2 vs V3 confounded by the operator gate | Partly | Closed-loop errors per variant (Sec. VII-B). **Not done:** an auto-approving V3 or gated V2 (about 2 h of VM time per variant) | `paper_build.py` (`LiveVtwo*`, `LiveVthree*`), `main.tex` |
| W2, I2.1 | Load-independent capacity; 15.8 ms cap; rho_q on offered demand; sigma fixed | Partly | Sec. IV-A states the two further simplifications. **Not done:** a transient-aware or learned surrogate (twin code, needs an ADR) | `main.tex` |
| W3 | Incremental novelty | Partly | Sec. II: the parts are known; the contribution is their combination for Wi-Fi and its measurement. **Not added:** the references we could not check | `main.tex` |
| W4, I4.5 | LLM offline; 9 misses not verified | Partly | Sec. I: H3 tests translation, not the twin's verdict. **Not done:** replaying the misses through the verifier | `main.tex` |
| W5, I3.2, I3.3 | Seed reuse; three seeds; no roaming V1 | Partly | Sec. VI: the seed reuse and seed 44. **Not done:** fresh seeds, a roaming V1 | `main.tex` |
| I1.1 | H1 censoring wording | Fixed | Sec. I | `main.tex` |
| I1.2 | Starting stations and traffic | Fixed | Sec. III-A, generated from the configuration; "bulk" removed from the scenario description | `paper_build.py` (`CfgStartClients`, `ScenVideo*`), `main.tex` |
| I1.3 | Seven types vs two proposed; gate rule | Fixed | Sec. III-B | `main.tex` |
| M1.1 to M1.3 | Fig. 1 dashed line; state read-back; fairness definition | Fixed | Fig. 1 caption; Sec. III-B (queue and rate limit not read back); Sec. I | `main.tex` |
| I2.2 | Demand inversion, loss cap, baseline offset | Partly | Sec. IV-A states the cap, the uncapped inversion and the offset (shared by baseline and prediction). **Not changed:** the twin's estimator | `main.tex` |
| I2.3 | Web-flow rate and T | Fixed | Sec. IV-A: the formula, and that the probe measures web the same way | `main.tex` |
| I2.4 | No noise floor in Eq. (6); U not compared; J clause | Partly | Sec. IV-B states both; Table IV row without Jain's index. **Not changed:** the rule (a safety threshold, needs an ADR) | `paper_build.py` (`NoJain`), `main.tex` |
| M2.1 to M2.4 | Per-AP index, mean loss, station delay, Eq. (4) index, t_d names, uplink | Fixed | Sec. IV-A, IV-B | `main.tex` |
| M2.5 | k overloaded; "points" | Partly | "percentage points". The overloading of k kept, as in round 4 | `main.tex` |
| I3.1 | Rollback, approval and watch preconditions; same-tick states | Partly | (S1) says a steer's target AP being up is left to the prediction. **Not done:** the executor fixes (listed in Sec. VIII; need an ADR) | `main.tex` |
| I3.4 | Budget, order, compiler, intents | Partly | Sec. V and VI. **Not done:** an external intent benchmark | `main.tex` |
| M3.1 to M3.5 | Channel sum, f(s,{p}), seeds, model names, L95, tense | Fixed | Sec. V, VI, Algorithm 1 | `main.tex` |
| I4.2 | Cohort scopes; stranding; 1000 ms means | Partly | Eq. (5)'s flow set and the stranding stated. **Not done:** a QoS-only recovery time | `main.tex` |
| I4.3 | Video-only errors; taint in Table IV; start-up; later window | Partly | Video only stated; Table IV brackets; start-up stated. **Not done:** offline latency and loss validation, a later comparison window | `paper_build.py` (`tainted_actions`, `Rule*Clear`), `main.tex` |
| I4.4 | Flash-crowd recovery narrative | Fixed | Sec. VII-A rewritten from the data | `main.tex` |
| M4.1 to M4.5 | Fig. 11, 13, 14; 129 vs 6; precision; references | Fixed | Captions, Fig. 13 axes, Fig. 14 labels, Sec. VII-C, `references.bib` | `paper_figures.py`, `paper_build.py` (`AnoFalseFlash`), `main.tex`, `references.bib` |

## Not done, and what it needs (for the next paper)

1. A campaign on fresh seeds; an auto-approving V3 or a gated V2; a V1 with native 802.11k/v/r
   roaming (about 2 to 6 hours of VM time each).
2. The executor fixes of Sec. VIII and a noise floor in Eq. (6) (safety logic: an ADR first).
3. Offline validation of latency and loss, a transient-aware delay model, a later comparison
   window for kept actions, a QoS-only recovery time.
4. Replaying the local model's semantic misses through the verifier; an external intent benchmark.

# How a round is done

1. Compile the paper (`make paper`, or on Overleaf) and upload the PDF to
   <https://research.google/deepreview/>.
2. Make `roundN/`: copy the uploaded version (`paper/main.tex`, `references.bib`, `figures/`, `generated/` and the PDF) into `roundN/reviewed/` unchanged, and paste the comments into `roundN/review_comments.md`, giving each an ID.
3. For each comment: change `paper/main.tex`; if a number, table or figure must change, change the
   code or re-run the experiment, then `make results` and `make paper` (the numbers are never
   edited by hand); if a comment needs a new experiment, record it in the last column.
4. Save the revised PDF as `roundN/paper_revN.pdf` and as `paper_final.pdf` next to this report, and fill in the round's table.
5. `make submission` rebuilds `dist/Revision_Report.docx` from this file.
