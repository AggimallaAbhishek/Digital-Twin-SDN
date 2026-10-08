# 2. Related Work

This chapter covers five lines of work that the system builds on: network digital twins, learned network performance models, LLM-based intent-based networking, programmable enterprise WLANs, and emulation of software-defined wireless networks. Each section says what we take from that work and where we differ. Section 2.6 places our system relative to all five.

<!-- Source: docs/literature/ (P0.4). Claims marked [check] are still to be confirmed against the full text by Abhishek before submission. -->

## 2.1 Network digital twins

Almasan et al. [1] present the network digital twin (NDT) as a modern form of classical network modelling tools: an accurate, data-driven model of a real network that runs in real time. They describe a general NDT architecture, argue that machine learning makes some of its core components practical, and discuss the uses an NDT opens up for network operation, chiefly answering "what if" questions about a change before it is made.

Our system follows the same split between a mirror of the live state and a performance model that predicts KPIs for a proposed change. It differs in two ways. First, our performance model is analytical (Wi-Fi airtime and queueing with a co-channel penalty), not learned. It needs no training data, its predictions can be explained, and it is fast enough for a control loop that runs every few seconds. Second, we use the twin as a **safety gate**, not only as an analysis tool: no action, including one proposed by an LLM, is applied without an accepted twin verdict.

## 2.2 Learned network performance models

RouteNet [2] is a graph neural network (GNN) that learns how topology, routing and traffic together determine the per-path delay, jitter and loss of a network. Because it works on graph-structured data, it generalises to topologies, routings and traffic loads not seen in training; the authors report a worst-case mean relative error of 15.4% on unseen scenarios [check]. They also use the model inside SDN optimisation, scoring candidate routing configurations without running them on the network.

We share the role of a fast performance model inside the control loop: score candidate actions in the twin, then apply only an accepted one. We also follow RouteNet's way of reporting accuracy, as relative error against measured KPIs on unseen scenarios, in our twin validation. We do not use a GNN. RouteNet models wired paths, while the bottleneck in our network is the shared Wi-Fi medium (per-AP airtime and co-channel interference), which we model explicitly. A RouteNet-style learned surrogate is left as future work.

## 2.3 LLM-based intent-based networking

Intent-based networking (IBN) lets operators state goals instead of low-level configuration, but most IBN systems still take intents in structured formats such as JSON or YAML. Mekrache et al. [3] propose an LLM-centric architecture that manages the whole intent life cycle (decomposition, translation, negotiation, activation and assurance) in natural language, and demonstrate it on a real 5G deployment at the EURECOM facility.

We adopt natural language as the operator interface and the life-cycle view: translating an intent is not the end, because the resulting policy stays active and is re-checked in every control loop. We differ in how much we trust the LLM. In our system its output must pass a JSON schema, is turned into actions by a deterministic compiler, and is simulated in the twin before an executor applies it; the LLM has no tool that changes the network. We target a Wi-Fi campus (traffic priority, client steering, channel changes) rather than 5G service deployment, and require the pipeline to work on a small local model as well as a cloud model.

## 2.4 Programmable enterprise WLANs and load balancing

Odin [4] makes enterprise WLANs programmable, so that mobility management, interference management and load balancing can be written as applications on a central SDN controller. Its central difficulty is that in Wi-Fi the client, not the infrastructure, chooses which AP to associate with. Odin addresses this with a light virtual AP (LVAP) per client, needs no changes on the client, and supports WPA2 Enterprise.

Our flash-crowd and AP-failure scenarios depend on the same observation: clients are "sticky" and do not rebalance on their own, so load balancing needs steering driven by the infrastructure. We also treat load balancing and channel management as controller applications. We steer clients by explicit re-association to a chosen AP instead of LVAPs, so a steer costs a reconnection that the twin has to account for, and every steer is checked in the twin first, within fixed bounds on how many clients may move at once and how weak their new signal may be.

## 2.5 Emulating software-defined wireless networks

Mininet-WiFi [5] extends the Mininet emulator with virtual Wi-Fi stations and APs while keeping Mininet's OpenFlow support and lightweight, process-based virtualisation. It was built to fill the lack of tools for prototyping and evaluating SDN in wireless settings, and the paper demonstrates it with two IEEE 802.11 use cases. It received the best paper award at the 2nd Workshop on Management of SDN and NFV Systems, held with CNSM 2015 [check].

Our entire testbed runs on Mininet-WiFi with the Ryu controller over OpenFlow 1.3. Building it showed two limits that matter for this project. On our virtual machine each emulated AP carries about 4.6 Mbit/s regardless of its configured bitrate, and APs on the same channel do not slow each other down. We therefore model co-channel interference explicitly, as a documented capacity reduction applied to each AP, and report the emulated radio as a limitation (Chapter 7). Emulated stations also never roam on their own, so re-association after an AP failure is scripted.

## 2.6 Positioning

| Work | Twin / model of the network | Wireless | Natural-language intents | Checked before applying |
|---|---|---|---|---|
| Almasan et al. [1] | Yes (general architecture) | Not specific | No | The NDT's purpose |
| RouteNet [2] | Learned GNN model | No (wired paths) | No | Scores candidate routings |
| Mekrache et al. [3] | No | 5G | Yes (LLM-centric life cycle) | [check] |
| Odin [4] | No | Yes (enterprise WLAN) | No | No |
| Mininet-WiFi [5] | Emulator (testbed) | Yes | No | Not applicable |
| **This work** | **Analytical twin** | **Yes (campus Wi-Fi)** | **Yes (LLM, schema-checked)** | **Every action, twin verdict required** |

None of the five works combines all four elements. Digital twins and learned models predict the effect of a change but are not tied to natural-language control. The LLM intent system translates natural language but does not, as far as its abstract shows, simulate each resulting action before activating it [check]. The wireless works make WLANs programmable and testable but have no predictive gate. Our system joins these elements: an LLM and an optimizer may propose, but only actions that a digital twin of the Wi-Fi network accepts are applied, and they are rolled back if the live network disagrees.
