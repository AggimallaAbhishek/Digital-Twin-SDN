# 7. Discussion and Limitations

<!-- P7.1d. Drafted 2026-10-12: 7.2 and 7.3 from what is already known; 7.1 is completed after the P6.4 campaign (H1, H2). Sources: Chapter 6, docs/decisions.md, docs/PHASE_PLAN.md (deviation log, parking lot). -->

## 7.1 What the results show

_The answers to H1 (recovery) and H2 (blocked actions) are written from the campaign's results (Section 6.2, 6.3), whatever they show._

What already holds before the campaign:

- **A simple, analytical twin is accurate enough to act on.** It predicts per-flow throughput within 4.5% (video within 4.5% in every case but a channel change), in well under a millisecond. Verifying a change before applying it costs nothing a person would notice, so there is no speed argument for acting without the twin.
- **The language model is useful as a translator and an explainer, not as a controller.** It translated 30 of 30 intents and explained 3 of 3 live faults, but it is never trusted directly: its output is validated, compiled by deterministic code into bounded actions, and checked in the twin.
- **A forecast did not help.** On this campus, load changes in steps (an AP fails, a crowd arrives), and trend extrapolation overshoots more often than it anticipates. Reacting to measured load, checked in the twin, proved the more reliable design.

## 7.2 Limitations

- **Virtual network.** Mininet-WiFi emulates the radio with a fixed propagation model, on one machine. Real radios add fading, interference from devices outside the network, and client behaviour the model does not have. The numbers are about this emulation, not about a real campus.
- **An analytical twin.** The twin's model is calibrated on this testbed. Bulk TCP flows are its weakest case (12–21% error), and it would need recalibrating for other hardware or traffic. It predicts the steady state after a change, not the transient while clients move.
- **A narrow action set.** The heuristics can steer clients, change a channel or transmit power, set QoS queues and rate limits, all within fixed bounds. When no allowed move is left, the loop does nothing. This happened in one of the three flash-crowd seeds of the loop batch: V3 steered 4 of 11 clients away and then had no target within the signal bound (decision P4.5-D).
- **Three seeds.** With three seeds per variant and scenario, the 95% intervals are wide ($t = 4.30$), and only large differences are distinguishable. Rare behaviours may not appear at all.
- **Censored recovery times.** A run that does not recover before it ends is counted at its run end. Means of time to recover are then lower bounds, and some H1 comparisons can only be called inconclusive (Section 6.1).
- **The local model is weaker.** Without internet the fallback model translated 21 of 30 intents and explained 2 of 9 replayed faults. The system stays safe, because invalid or unhelpful output is refused or harmless, but less useful offline.
- **One operator, one building.** Approvals, the dashboard and the copilot were designed for a single operator watching one campus.

## 7.3 Threats to validity

- **Internal.** The same team built the system and the evaluation. To limit this, the KPI definitions, the harm rule for H2 and the H1 verdict rule were fixed in recorded decisions (P4.5-A, P6.5-A, P6.6-A) *before* the campaign was run. The code was frozen (`eval-v1`) before the campaign, and every number in Chapter 6 is produced by a script from recorded data.
- **Construct.** "Recovered" combines utilisation under 80% with video p95 latency under 50 ms for 15 s. A different threshold would move the recovery times. The 50 ms figure is the project plan's video example, not a measured user requirement. "Harmful" means the executor measured a regression of more than 10% and rolled the action back. Smaller harms are not counted, which makes H2 conservative.
- **Conclusion.** Three seeds give low statistical power. Differences inside the confidence intervals are reported as not shown, not as no difference.
- **External.** One emulated campus layout, three scenario types and one traffic mix. Other layouts, more APs or real devices could behave differently. The variants differ only in the controller, so the comparison between them is fair, but the absolute numbers do not transfer.
