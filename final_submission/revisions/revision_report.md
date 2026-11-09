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
| Round 1 | `paper_rev1.pdf` (this revision; upload it for round 2) | 27 | 15 | 12 |
| Round 2 | `paper_rev2.pdf` | (fill in) | (fill in) | (fill in) |
| Round 3 (recommended) | `paper_rev3.pdf` | (fill in) | (fill in) | (fill in) |

Two complete review and revision rounds are required before submission; a third is recommended.
The reviewed draft is kept unchanged in `round0_draft/` (source and PDF); the revision is the
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

**Uploaded:** `paper_rev2.pdf` (date: ____)

| # | Review comment (verbatim) | Modification made | Where | Files or experiments changed |
|---|---|---|---|---|
| 2.1 | (paste the comment) | | | |

# Round 3 (recommended)

**Uploaded:** `paper_rev3.pdf` (date: ____)

| # | Review comment (verbatim) | Modification made | Where | Files or experiments changed |
|---|---|---|---|---|
| 3.1 | (paste the comment) | | | |

# How a round is done

1. Compile the paper (`make paper`, or on Overleaf) and upload the PDF to
   <https://research.google/deepreview/>.
2. Paste each comment into `roundN_deep_review.md` and the table above.
3. For each comment: change `paper/main.tex`; if a number, table or figure must change, change the
   code or re-run the experiment, then `make results` and `make paper` (the numbers are never
   edited by hand); if a comment needs a new experiment, record it in the last column.
4. Save the PDF that was uploaded as `paper_revN.pdf` in this folder and fill in the round's table.
5. `make submission` rebuilds `dist/Revision_Report.docx` from this file.
