# Problem Statement, Objectives and KPIs (P0.5)

**Project:** GenAI-Driven Digital Twin for Intelligent SDN-Based Wireless Network Optimization
**Status:** draft for approval (Abhishek) · 2026-10-07 · scope = PHASE_PLAN v2.2

## 1. Problem

Wireless networks change all the time: users move, crowds form, access points fail and neighbouring APs interfere. Software-Defined Networking (SDN) gives one programmable controller that can react, by rerouting flows, steering clients or changing channels. But **applying a change directly to a live network is risky**. A wrong channel, an over-eager client steer, or a bad rule from an automated optimizer or an LLM can make performance worse or cut users off. Operators also have to translate goals ("video in the lab must stay smooth") into low-level rules by hand.

Two gaps follow:

1. **No safe place to try a change first.** SDN controllers apply actions without knowing their effect in advance.
2. **No natural-language path to network policy that is safe.** LLMs can turn intents into configurations, but their output can be wrong or unsafe, and nothing checks it before it reaches the network.

## 2. Proposed solution (one paragraph)

A **digital twin** of an emulated wireless SDN network (Mininet-WiFi + Ryu) mirrors live telemetry and **predicts the KPI effect of any candidate action before it is applied**. Candidate actions come from a heuristic optimizer (driven by load forecasts and anomaly detection) and from an **LLM served through Ollama** (a cloud model with an automatic local fallback, so it also works offline) that turns operator intents into structured policies. A verifier accepts an action only if the twin predicts no harmful KPI regression and no policy violation. An executor applies accepted actions through the SDN controller, watches live KPIs, and **rolls back automatically** if reality disagrees with the prediction. The LLM also explains anomalies and answers operator questions using live data.

## 3. Research question and hypotheses

**RQ:** Does verifying actions in a digital twin before applying them make an AI-driven SDN controller for Wi-Fi both *more effective* and *safer* than acting directly, and can an LLM safely drive it from natural-language intents?

| ID | Hypothesis | Tested by |
|---|---|---|
| H1 | The full system (V3) recovers from congestion faster than plain SDN (V1). | flash crowd, AP failure, interference scenarios |
| H2 | The twin blocks actions that would have hurt KPIs, which an optimizer acting directly (V2) would apply. | twin-blocking analysis (P6.5) |
| H3 | An LLM (cloud model, with a local fallback) with schema-constrained output + validation + twin check translates most intents correctly, and **no invalid configuration reaches the network**. | 30-intent test set (P5.4) |

## 4. Objectives

1. Build a reproducible, fully virtual wireless SDN testbed: campus of 4 APs, 2 switches, 20 stations (`docs/scenario.md`).
2. Stream telemetry (ports, flows, APs, stations, KPIs) into a time-series store and a live dashboard.
3. Build a digital twin that mirrors state and predicts throughput, latency, loss and fairness for a candidate action in under 1 s.
4. Close the loop: forecast → propose → verify in twin → apply → watch → roll back.
5. Add an LLM layer (local, Ollama): intent → policy → twin-verified actions; anomaly explanations; a copilot over live data.
6. Evaluate V1 (plain SDN) vs V2 (heuristics, no twin) vs V3 (full system) on 3 scenarios × 3 seeds, and present a live demonstration.

## 5. KPIs and targets

Targets are what we **aim for and test**. Results are reported honestly whether or not they are met.

### 5.1 Network performance (evaluation scenarios, V3 vs V1)

| KPI | Definition | Target | Source |
|---|---|---|---|
| **Time to recover** | Seconds from congestion onset until the affected AP's channel utilization is back under 80% *and* video flows meet their latency objective | V3 ≥ **30% faster** than V1 (H1) | AP stats + KPI probe |
| Throughput | Mean throughput of affected flows during the stress window (Mbps) | V3 ≥ V1 | KPI probe |
| Latency | p95 latency of video flows during the stress window (ms) | V3 < V1 | KPI probe |
| Packet loss | Mean loss of affected flows (%) | V3 ≤ V1 | KPI probe |
| Fairness | Jain's index of per-AP client load | V3 ≥ **0.8** during the flash crowd | AP stats |

### 5.2 Digital twin

| KPI | Target | Plan gate |
|---|---|---|
| Throughput prediction error (MAPE) on held-out runs | **< 15%** (acceptance < 20%) | P3.5 |
| State sync lag | < 3 s | P3.1 |
| Simulation time per candidate action | < 1 s | P3.3 |

### 5.3 Safety

| KPI | Target | Source |
|---|---|---|
| Applied actions without an accepted twin verdict | **0** (100% verified) | audit log |
| Harmful V2 actions blocked by the twin | reported (count and %); expected > 0 (H2) | P6.5 |
| Bad actions that slipped past the twin and were rolled back | reported; rollback restores the previous config in 100% of cases | executor log |
| High-impact actions applied without operator approval | **0** | audit log |

### 5.4 GenAI / LLM (cloud main model + local fallback)

| KPI | Target | Source |
|---|---|---|
| Intent → policy accuracy (30 intents) | **≥ 20/30** (stretch 25/30) (H3) | `genai/eval` |
| Invalid LLM outputs reaching the compiler or network | **0** | validation logs |
| Schema-valid output on first try | reported | LLM call log |
| Response time per intent | **< 10 s** (P0.7: `gpt-oss:120b-cloud` mean 1.6 s; local fallback `qwen2.5:3b` mean 3.0 s) | LLM call log |
| Intent accuracy on the local fallback alone | reported (30 intents) | `genai/eval` |
| Copilot diagnostic questions answered with live evidence | 5/5 | P5.5 |

### 5.5 Testbed sanity (already measured)

| KPI | Target | Status |
|---|---|---|
| Station association | 20/20 | ✅ 3/3 runs |
| Pair reachability | 100% | ✅ 420/420 |
| First-try single-ping loss (radio model) | ≤ 5% | ✅ 1.4–2.6% |

## 6. Scope and assumptions

- **In scope:** see PHASE_PLAN v2.3 §3. Fully virtual (no hardware); Ollama cloud LLM with local fallback; analytical twin; heuristic optimizer.
- **Assumptions:** wmediumd's log-distance + interference model is a reasonable proxy for 2.4 GHz behaviour; the campus is small (4 APs) but has the features that matter (overlap, channel reuse, crowd movement).
- **Limitations to state in the report:** emulated radio rather than RF measurements; small topology; heuristics instead of RL; one LLM family evaluated (cloud + local fallback); 3 seeds per configuration.
- **Future work:** GNN surrogate twin, RL optimizer, RAG copilot, real hardware, larger topologies, hosted LLM comparison.

## 7. Success criteria for submission (Oct 30)

1. A report covering problem, design, implementation, evaluation (with every number generated by script) and limitations.
2. A **live demonstration** that runs from a cold start (`make demo`): a flash crowd forms → the twin verifies a fix → it is applied and KPIs recover → an operator intent is typed and safely enforced → the copilot explains what happened.
