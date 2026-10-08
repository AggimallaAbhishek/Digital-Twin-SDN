# 1. Introduction

## 1.1 Motivation

Campus Wi-Fi is never still. Students move between rooms, a lecture fills a hall in a few minutes, an access point (AP) fails, and neighbouring APs on the same channel slow each other down. Software-Defined Networking (SDN) puts one programmable controller in charge of the network, so it can react to these events: it can steer clients to a less loaded AP, change an AP's channel, or give a traffic class a higher priority.

Reacting is risky, though. A controller that applies a change directly to the live network learns its effect only afterwards. A channel change that moves an AP onto a busy neighbour's channel, or a steer that pushes clients onto an AP they can barely hear, makes things worse for real users. The risk grows as more of the decisions are automated, whether by an optimizer or by a large language model (LLM) that turns an operator's request into network policy.

Operators also have to translate goals into rules by hand. A goal such as "video calls in the lab must stay smooth" becomes queue settings, rate limits and thresholds. LLMs can do that translation from natural language, but their output can be wrong, incomplete or unsafe, and nothing checks it before it takes effect.

## 1.2 Problem statement

Two gaps follow from this:

1. **No safe place to try a change first.** An SDN controller for Wi-Fi applies actions without knowing their effect in advance.
2. **No safe natural-language path to policy.** An LLM can turn an intent into a configuration, but nothing guarantees that its output is valid and harmless before it reaches the network.

## 1.3 Approach

We build a **digital twin** of an emulated campus Wi-Fi network and make it the gate that every change must pass. The network is emulated with Mininet-WiFi and controlled by the Ryu SDN controller: 4 APs, 2 switches and 20 stations in a lecture hall, a lab, a corridor and a library. Telemetry streams into a time-series store. The twin mirrors the live state and predicts the effect of a candidate action on throughput, latency, loss and fairness before it is applied.

Candidate actions come from two sources:

- a heuristic optimizer, driven by load forecasts and anomaly detection, that proposes client steering and channel changes;
- an LLM, served through Ollama (a cloud model with an automatic local fallback, so it also works offline), that turns operator intents into structured policies. A deterministic compiler, not the LLM, turns each policy into actions.

A verifier accepts an action only if the twin predicts no harmful KPI regression and no policy violation. An executor applies accepted actions through the controller, watches the live KPIs, and rolls the action back if reality disagrees with the prediction. The LLM never talks to the controller or the APs directly. It can only propose, through a fixed set of tools, and it cannot approve its own actions.

## 1.4 Research question and hypotheses

**Research question.** Does verifying actions in a digital twin before applying them make an AI-driven SDN controller for Wi-Fi both more effective and safer than acting directly? Can an LLM safely drive it from natural-language intents?

| ID | Hypothesis | Tested by |
|---|---|---|
| H1 | The full system (V3) recovers from congestion faster than plain SDN (V1). | Flash crowd, AP failure and interference scenarios |
| H2 | The twin blocks actions that would have hurt KPIs, which an optimizer acting directly (V2) would apply. | Twin-blocking analysis |
| H3 | An LLM with schema-constrained output, validation and a twin check translates most intents correctly, and no invalid configuration reaches the network. | A test set of 30 intents |

The three system variants are run on three scenarios with three random seeds each (Chapter 6).

## 1.5 Contributions

1. A **reproducible, fully virtual wireless SDN testbed** with four seeded campus scenarios (normal day, lecture flash crowd, AP failure, co-channel interference). It includes an explicit, documented model of co-channel interference, which the emulator does not produce on its own.
2. A **telemetry pipeline and labelled dataset**: 12 runs, 2 hours, split into training, validation and test sets by seed, with phase and event labels for evaluating anomaly detection and recovery.
3. A **digital twin** that mirrors the live network state and predicts the KPI effect of a candidate action with an analytical model of Wi-Fi airtime and co-channel interference.
4. A **closed control loop** (forecast, propose, verify, apply, watch, roll back) in which no action reaches the network without an accepted twin verdict.
5. An **LLM intent pipeline** in which natural language becomes a validated policy and then twin-verified actions, evaluated on a 30-intent test set on both the cloud model and the offline fallback.

## 1.6 Report organisation

Chapter 2 reviews related work on network digital twins, learned performance models, LLM-based intent networking, programmable WLANs and wireless SDN emulation. Chapter 3 describes the system architecture and Chapter 4 the method: the twin model, the heuristics, the intent pipeline and the safety model. Chapter 5 covers the implementation and the testbed. Chapter 6 presents the evaluation results, and Chapter 7 discusses them with the limitations. Chapter 8 concludes and outlines future work.
