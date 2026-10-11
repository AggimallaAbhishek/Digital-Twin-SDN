# 4. Method

<!-- Drafted in P7.1c (2026-10-10). Describes how each part works; every result is in Chapter 6. Sources: the module docstrings named in each section, config/*.yaml, docs/decisions.md. -->

This chapter explains how the system decides what to do and how it decides whether a change is safe. Section 4.1 covers the twin's view of the network and 4.2 the model that predicts the effect of a change. Section 4.3 covers forecasting and anomaly detection, and 4.4 the heuristics that propose changes. Section 4.5 covers the three uses of the language model, and 4.6 the safety model that ties them together.

## 4.1 Twin state and synchronisation

The twin's view of the network is a `TwinState`: every AP (position, channel, whether it is up, utilisation, transmit power), every station (position, the AP it is associated with, its zone), and every traffic flow (its latest measured throughput, latency and loss, its QoS queue and any rate limit). The state is immutable. A simulation always works on a modified copy, never on the state other components are reading.

The state is rebuilt from telemetry rather than updated by events. On every refresh the twin reads the last 10 s of one run's AP, station and KPI records from InfluxDB and keeps the newest record of each AP, station and flow (`twin/state/sync.py`, `config/twin.yaml`). Rebuilding avoids drift between the twin and the network: there is no accumulated state that could disagree with what was last measured. Three rules handle imperfect telemetry:

- An AP with no statistics for **5 s** (the collector's allowed gap) is down. A disabled AP stops reporting rather than reporting itself as down, so silence is the signal.
- A record with an empty field the twin needs is ignored, and the AP's last complete record is used (decision P3.1-A).
- Before the run's first record there is no state at all. The API then answers "not yet" (503) rather than inventing one.

The twin's **lag** is the time from the newest record it used to the moment the state is used. The lag includes the query time itself (`builder.lag_s`), so the twin is never more current than it claims to be.

## 4.2 Analytical performance model

The simulator (`twin/sim/analytical.py`) maps a state to predicted KPIs for every flow and for the network. The verifier runs it twice, on the current state and on the state with the proposed actions applied, and compares the two. It is analytical rather than learned (deviation #2), so a prediction takes milliseconds and every number can be traced to a formula.

**Capacity.** Each AP that is up offers its measured downlink capacity $C = 4.6$ Mbit/s. A same-channel AP nearby reduces it (§5.2):

$$ C_i = \frac{C}{1 + \sum_{j \ne i} w(d_{ij})}, $$

summed over the APs $j$ that are up on AP $i$'s channel, with $w(d) = 1$ up to 30 m, falling linearly to 0 at 60 m. This is the same model the testbed emulates, so a channel change in the twin and on the testbed moves capacity the same way. The AP's downlink is the only bottleneck the model represents. The wired links run at 100 Mbit/s against 4.6 Mbit/s per AP, so their load stays below 5% (deviation #12).

**Demand.** Each flow offers what its source sends, cut to its rate limit if it has one. A measured video flow sends what it received divided by $(1 - \text{loss})$; any other flow sends its application class's configured rate (`config/sim.yaml`).

**Sharing.** The AP serves its three QoS queues in strict priority: priority, then best effort, then background. Within a queue, the capacity left over is shared max-min fairly by water-filling: no flow gets more than it asks for, and what one does not need goes to the others.

**Loss.** An inelastic flow (video) loses what it cannot send. An elastic flow (TCP bulk transfer) slows down instead, and sees only the base loss.

**Latency.** Each queue is modelled as an M/M/1/K queue at load

$$ \rho = \frac{\text{demand of the queue and of the queues served before it}}{C_i}, $$

and the latency is a base delay plus a service time multiplied by the mean number in the queue, $L(\rho, K)$. The bounded queue length $K$ makes the predicted latency level off at saturation, as the testbed measured, instead of growing without limit. The KPI probe measures one ping per station, and that ping travels in the station's highest-priority queue (decision P4.4a-A). So every flow of a station reports that queue's latency, and the model does the same.

**Web fetches** report the rate of a single page fetch, a fraction of the capacity that the other traffic in the same or a higher queue leaves free.

**Network KPIs** are the total traffic carried, the mean latency and mean loss over all flows, and Jain's fairness index over the client counts of the APs that are up:

$$ J = \frac{(\sum_i n_i)^2}{N \sum_i n_i^2}. $$

A flow whose station has no AP, or whose AP is down, is dead: no throughput, 100% loss, and the probe's timeout as latency.

## 4.3 Forecasting and anomaly detection

**Load forecasting** (`ml/forecast/`) predicts each AP's utilisation 1 and 3 minutes ahead from its 5-second series. Two models are compared: a moving average over the last $w$ steps (the baseline), and Holt's linear-trend smoothing,

$$ L_t = \alpha y_t + (1-\alpha)(L_{t-1} + T_{t-1}), \quad T_t = \beta (L_t - L_{t-1}) + (1-\beta) T_{t-1}, \quad \hat y_{t+h} = L_n + h\,T_n. $$

There is no seasonal term, because a 10-minute run has no season (decision P4.1-A). The parameters $w$, $\alpha$ and $\beta$ are tuned on the training split only, with rolling-origin evaluation. A gap in a series restarts the history instead of joining the values on either side of it.

**Anomaly detection** (`ml/anomaly/`) looks at the whole network, not at one metric at a time. Every 5 s a feature vector summarises the last 30 s:

- per AP: mean and maximum utilisation, mean client count, the change in client count, and the share of the window in which it did not report;
- for the network: stations without an AP, the mean loss of the flows, and the 95th-percentile latency.

An Isolation Forest is fitted on windows of normal operation only: the training split's normal runs, and the windows of disrupted runs that end before the disruption. Anything unlike normal operation therefore scores high. The alert threshold is chosen on the validation split. Each alert names the entity whose features deviate most from normal (largest $|z|$ against the training windows): one AP, or "network".

The live monitor (`api/alerts.py`) runs exactly this pipeline on live telemetry. It refits the detector from the dataset when it starts, using the same training code as the offline evaluation (`ml/anomaly/training.py`), so the deployed detector is the evaluated one and no serialised model has to be trusted.

## 4.4 Heuristic optimizer

The optimizer (`ml/optimizer/heuristics.py`) proposes changes for an overloaded network. It is a pure function of the twin state, and its proposals are only candidates: the verifier checks every one. The campus is a tree, so every pair of nodes has exactly one path between them. A rerouting heuristic could therefore never propose anything, and there are two heuristics instead (deviation #9).

- **Client steering.** An AP at or above a high-utilisation threshold sheds up to a fixed fraction of its clients to APs below a target utilisation, least-loaded first. A station only moves to an AP where its predicted signal is at least −75 dBm, the steering bound fixed in the shared schemas (ADR-004). Stations with the strongest predicted signal go first.
- **Channel change.** A congested AP that shares its channel with nearby APs moves to the channel with the least co-channel load, if that is strictly better. APs are handled from the most to the least loaded, each decision seeing the earlier ones, so two APs never jump onto the same free channel together. A channel change is high impact, so it always waits for an operator (§4.6).

**The control loop** (`api/loop.py`) runs every 5 s:

1. Finish the watches that are due.
2. Unless an earlier change is still being watched, refresh the twin.
3. Ask the heuristics for proposals.
4. Verify each proposal and record its verdict.
5. Apply the accepted ones that need no approval.

The loop makes one change at a time, so the effect of each change can be measured on its own. A proposal identical to one that was just rolled back is not tried again for 120 s (decision P4.5-C). Without that rule, the heuristics would keep proposing the same rolled-back change.

## 4.5 The language model's three roles

All three uses of the language model share one client (`genai/llm/client.py`). The main model is a cloud model with a local model as automatic fallback (ADR-001). The temperature is 0, every reply is validated against a schema with at most two repair attempts, and every call is logged with its model, prompt version, token counts, latency and tool calls. **None of the three can change the network.** They read through validated tools, and they can ask the twin about a change. Applying one takes an operator.

**Intents** (`genai/intent/`). The operator's text is parsed into a `Policy` under a JSON schema: scope (zone, application classes), objectives (KPI targets or a priority), and hard constraints. The model's only job is this translation. Turning the policy into actions is done by a **deterministic compiler**:

- a priority becomes a QoS-queue action;
- a throughput cap becomes per-flow rate limits;
- KPI targets and constraints stay as standing objectives that the verifier enforces on every later change.

Output that fails validation never reaches the compiler. The compiled actions are verified like any other proposal.

**The copilot** (`genai/agent/`) answers an operator's question by calling tools: the topology, a metric series, the recent alerts, and a twin simulation. It then answers in a few sentences that name the entity, the cause and the numbers. The prompt asks it to rule out an AP failure, a channel change and a crowd before naming a cause, because a busy AP is a symptom, not a cause (prompt `copilot_v2`, decision P5.5-D). For a proposal, the model names only the action's type, parameters and reason. The code stamps the identifier, source and time, and the twin's verdict is recorded in the audit log. The copilot is never given the tool that applies an action.

**The root-cause explainer** (`genai/rca/`) turns an alert into a diagnosis. The model reads a small, deterministic evidence summary, not raw telemetry:

- for each AP over the 5 minutes before the alert: utilisation, clients and channel before versus during the last minute, whether it still reports, and its stations;
- the stations without an AP;
- the worst flows;
- the latest actions in the audit log.

It answers in a fixed schema. Each likely cause carries a category (AP down, co-channel interference, congestion, a bad action, other), the entity, the evidence and a confidence. Each suggested fix is checked in the twin before the operator sees it.

## 4.6 Safety model

Safety rests on one rule, **nothing reaches the network without an accepted twin verdict**, and on four mechanisms that enforce it. The rule is enforced in the code that applies changes, not only stated in the design.

**1. Verification.** The verifier (`twin/verify/verifier.py`) checks a set of actions together, so an intent's actions are all-or-nothing:

- **Hard bounds** are checked on the state as the earlier actions in the set leave it:
  - a steer may move at most a fixed fraction of an AP's clients, only stations actually on that AP, and only to a predicted signal of at least −75 dBm;
  - a transmit-power change may step by at most 3 dB;
  - the last AP serving a zone may never be taken down.
- **KPIs** are compared on the flows the action affects, using the problem statement's definitions: mean throughput, 95th-percentile video latency, mean loss, and network-wide Jain's index.
- **Acceptance rule:** an action is rejected if any of these gets worse by more than 5% while none improves by more than 5%.
- **Policies:** a hard constraint may not be broken, or made worse if it already is, and an objective that was met may not become missed.

**2. Impact and approval.** Every action type has a fixed impact class (Table 3.2). A low-impact action applies when the twin accepts it. A high-impact action (a channel change, taking an AP down) always waits for an operator. A medium-impact action waits until the twin's predictions for that type have been validated against the testbed; so far only client steering qualifies (decision P3.4-C).

**3. The executor** (`controller/executor/`) is the only component that changes the network. It applies an action only if:

- the action is in its ledger with an accepted verdict;
- it has an operator's approval where one is needed;
- it has not already been applied;
- it is within the rate limits.

It applies a verified set as a whole or not at all. A denied action can never be applied, even in evaluation runs.

**4. Watch and rollback.** For 30 s after a change the executor measures the live KPIs, ignoring the first 10 s of the action's own transient (such as a steered station re-associating). If any KPI is worse than before, by more than 10% *and* by more than that KPI's measured noise floor, the change is reverted. The noise floors are the 95th percentile of natural worsening in windows with no action, measured on the training data (decision P4.4-B). Without them, ordinary fluctuation would roll back good changes. The measured KPIs are stored next to the twin's prediction, so every change also tests the twin.

Every step is recorded in an append-only audit log: the verdict, the approval and who gave it, the application, the outcome and the reason. One exception to the safety rule is written down. Evaluation runs of the "V2" variant apply actions without the twin, to measure what the twin prevents (ADR-005). The executor allows this only under a switch that the API never sets. Even then, operator denials, the rate limits and the rollback still apply.
