# 6. Evaluation and Results

<!-- P7.1d. Drafted 2026-10-12: 6.1, 6.3 (twin accuracy), 6.4, 6.5 from finished tasks; 6.2 and the H2 part of 6.3 wait for the P6.4 campaign and come from `make results` only (experiments/results/results.md). Sources: models/twin/v1/validation.json, models/forecast/v1/metrics.json, models/anomaly/v1/metrics.json, models/genai/v1/live.json and rca_replay.json, docs/PHASE_PLAN.md task notes, docs/decisions.md. -->

This chapter tests the three hypotheses of Section 1 against measurements. Every number comes from a script run on recorded data (`make results`, and the evaluation scripts named in each section); none is copied by hand.

## 6.1 Setup: variants, scenarios, seeds

**Variants.** The same testbed runs under three controllers:

| Variant | What acts on the network |
|---|---|
| **V1** plain SDN | Nothing but the controller's L2 learning; stations re-associate by themselves |
| **V2** heuristics without the twin | The heuristic optimiser's proposals are applied directly. The twin's verdict is still computed and recorded, but ignored (evaluation runs only, ADR-005) |
| **V3** full system | Proposals are verified in the twin; only accepted ones are applied, high-impact ones only after an operator's approval, and every change is watched and rolled back on a regression |

**Scenarios.** Three 10-minute scenarios on the 4-AP, 20-station campus (`docs/scenario.md`), each with one disruption:

| Scenario | Disruption (scenario time) | Event AP |
|---|---|---|
| `lecture_flash_crowd` | 10 students walk into the lecture hall from 120 s; video starts at 210 s | (the busiest AP) |
| `ap_failure` | ap2 goes down at 240 s | ap2 |
| `cochannel_interference` | ap3 is forced onto channel 1 at 180 s | ap3 |

**Seeds and runs.** Every variant runs every scenario with seeds 42, 43 and 44: 27 runs in all, at one frozen code version (`eval-v1`, decision P6.4-A). A run that fails is re-run, and the failed attempt is kept and logged.

**KPIs** (problem statement §5.1, defined in decision P6.6-A). Each is computed per run over the *stress window*, from the disruption to the run's end:

- **Time to recover**: seconds from the disruption until the affected AP is under 80% utilisation *and* video p95 latency is at most 50 ms, both holding for 15 s (P4.5-A). A run that never recovers is counted at its run end.
- **Throughput** and **loss**: means over the *affected flows*. These are the flows of the stations on the event's AP in the 30 s before the event, or, in the flash crowd, of the stations on the busiest AP in the 30 s after the onset. They stay affected if they are steered away.
- **Latency**: p95 of the affected video flows.
- **Fairness**: Jain's index of the APs' client counts, per 5 s, averaged over the window.

**Statistics.** Each KPI is reported as the mean over the three seeds with a 95% confidence interval, $\bar x \pm t_{0.975,\,n-1}\, s/\sqrt n$. With $n = 3$ the interval is wide ($t = 4.30$), so differences are claimed only where the intervals do not overlap. A run that never recovers makes its variant's mean time to recover a lower bound. H1 is therefore reported as *met*, *not met* or *inconclusive*, the last where such runs could change the answer.

## 6.2 Recovery and network KPIs (H1)

_Waits for the P6.4 campaign (`make campaign`, then `make results`)._ To report per scenario, from `experiments/results/results.md`: the KPI table (V1/V2/V3, mean ± 95% CI), the H1 verdict against the 30% target, fairness in the flash crowd against 0.8, and the per-scenario figure.

Before the campaign, the P4.5 loop batch gave a first look at the flash crowd (3 seeds, V3 against the V1 runs of `data/v1`). V3 recovered in 2 of 3 seeds (367 s and 143 s), and V1 in none (the run ended 390 s after the onset). V3 carried 0.54 Mbit/s per affected flow against 0.20, and lost 8% of packets against 44%. That result is recorded as a limitation (decision P4.5-D) and is superseded by the campaign.

## 6.3 Twin accuracy and blocked actions (H2)

**Prediction accuracy** (P3.5, `models/twin/v1/validation.json`). The twin predicted the per-flow throughput after 586 real situations in the held-out test split: steady state, and actions applied by the executor. Its error is a **mean absolute percentage error of 4.5%**, against a target of under 15%.

| Case (test split) | MAPE | n |
|---|---|---|
| All | 4.5% | 586 |
| Steady state, video | 4.0% | 495 |
| Client steering, video | 3.3% | 39 |
| AP down, video | 1.7% | 8 |
| Channel change, video | 8.1% | 10 |
| Rate limit / tx power / QoS, video | 0.4–0.9% | 3 each |
| Bulk flows (all cases) | 12–21% | 1–20 |

Bulk transfers are predicted least well. Their sending rate depends on TCP's reaction to loss, which the analytical model only approximates, and there are few bulk cases in the data. Video, the traffic the objectives are about, is predicted within 4.5% in every case but the channel change. One simulation takes **0.09 ms** for 60 flows, far under the 1 s budget. The twin stays within **1.04 s** of the network (P3.1: 98.7% agreement with the AP agent over 32 refreshes), against a target of under 3 s.

**Blocked actions (H2).** _Waits for the campaign's V2 runs._ To report, from the executor ledgers: the actions V2 applied that the twin had rejected, how many of those were then rolled back for a measured regression (decision P6.5-A, count and %), the accepted actions that slipped past the twin, and the safety counts of §5.3 for every variant.

## 6.4 Intent accuracy and LLM safety (H3)

**Intents.** On the 30-intent test set (P5.4, scored as schema-valid and equal scope, objectives and constraints), the main model **gpt-oss:120b-cloud** translated **30 of 30** intents correctly with the current prompt (`intent_v2`). The local fallback **qwen2.5:3b** alone translated **21 of 30** (P5.3), against a target of at least 20. The local model's misses were constraints and dropped priorities. _Both are re-measured at `eval-v1` (`make intent-eval`), with response time per intent._

**No invalid output reaches the network.** Every LLM output is validated against the `Policy` schema before the deterministic compiler sees it. An invalid output is repaired at most twice and is otherwise refused (tested). The compiler can only emit bounded actions, and every action goes to the twin. Nothing the LLM produces is applied without an accepted verdict, and high-impact changes also need an operator.

**Copilot and root-cause explainer** (P5.5, P5.6, `models/genai/v1/live.json`). On live runs (seed 44) the copilot answered **5 of 5** diagnostic questions correctly, with evidence from the live tools. The root-cause explainer diagnosed **3 of 3** live faults, each from the first alert, 5 s after the fault. **All 6** actions the LLM proposed have their twin verdict in the audit log, and none was refused as invalid. On replayed data the explainer scored 9/9, 9/9 and 8/9 over three runs of the same input with the cloud model. The local model alone scored 2/9.

## 6.5 Forecasting and anomaly detection

**Forecasting** (P4.1, `models/forecast/v1/metrics.json`). Holt's linear method was compared with a moving-average baseline on per-AP utilisation, rolling-origin, test split. **Holt does not beat the baseline overall**: RMSE at 1 min 0.129 against 0.117, and at 3 min 0.256 against 0.212. It wins only in the flash crowd at 1 min (0.125 against 0.147), the one gradual ramp. In step-like scenarios (an AP going down, a forced channel) extrapolating the trend overshoots. The loop therefore reacts to measured load, not to the forecast.

**Anomaly detection** (P4.2, `models/anomaly/v1/metrics.json`). An Isolation Forest on 30 s whole-network windows, with its threshold chosen on the validation split, scored **precision 0.950, recall 0.979 and F1 0.964** on the test split, with no alert in the normal run. It flagged the AP failure **5 s** after ap2 went down (69 of 72 alerts name ap2) and the forced channel after 25 s. In the flash crowd its precision is 0.867, because it also alerts while the crowd walks in, before the video onset that starts the labelled stress.
