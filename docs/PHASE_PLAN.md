# Phase Plan: Execution Guide

**Project:** GenAI-Driven Digital Twin for Intelligent SDN-Based Wireless Network Optimization
**Companion to:** [`PROJECT_PLAN.md`](PROJECT_PLAN.md), which covers the *what* and *why*. This file covers *how and in what order*.
**Version:** **v2.3** · 2026-10-07 · **25 days (Oct 6 → submit Oct 30, deadline Oct 31)** · **built by 1 person + Claude Code** (5 names on the report) · fully virtual · Ollama (cloud model + local fallback) · deliverables: **report + live demonstration** (see [Deviation log](#deviation-log) #2–6)

> **This file is the single source of truth for execution.** Work happens in the order and on the dates written here. Anything not in this file is out of scope until it passes the [change control process](#2-change-control).
>
> **v2.0 compresses the 16-week v1.1 plan into 25 days**, and the scope was cut using the v1.1 cut lists. **v2.2:** all work is done by Abhishek with Claude Code. The role tags (NET, TWIN, ML, GENAI, DOC) now just label *kinds of work*; the tracks run **one after another in calendar order**, with Claude Code implementing and Abhishek reviewing and approving each task. Where this file and `PROJECT_PLAN.md` disagree on scope, this file wins.

---

## Contents

1. [Rules for staying on plan](#1-rules-for-staying-on-plan)
2. [Change control](#2-change-control)
3. [Scope lock (v2.0)](#3-scope-lock-v20)
4. [How to read a phase](#4-how-to-read-a-phase)
5. [Calendar and milestones](#5-calendar-and-milestones)
6. [Status board](#6-status-board)
7. [Phase 0: Setup and contracts (Oct 6–8)](#phase-0-setup-and-contracts-oct-68)
8. [Phase 1: Wireless SDN testbed (Oct 7–12) · NET](#phase-1-wireless-sdn-testbed-oct-712--net)
9. [Phase 2: Telemetry and dataset (Oct 8–14) · TWIN](#phase-2-telemetry-and-dataset-oct-814--twin)
10. [Phase 3: Digital twin core (Oct 13–19) · TWIN](#phase-3-digital-twin-core-oct-1319--twin)
11. [Phase 4: Intelligence and executor (Oct 9–19) · ML](#phase-4-intelligence-and-executor-oct-919--ml)
12. [Phase 5: GenAI layer (Oct 8–22) · GENAI](#phase-5-genai-layer-oct-822--genai)
13. [Phase 6: Integration, dashboard, evaluation (Oct 20–28) · all](#phase-6-integration-dashboard-evaluation-oct-2028--all)
14. [Phase 7: Report and submission (Oct 13–30) · all](#phase-7-report-and-submission-oct-1330--all)
15. [Daily stand-up template](#daily-stand-up-template)
16. [Deviation log](#deviation-log)

---

## 1. Rules for staying on plan

1. **Calendar order, dates are hard.** Work the tasks in the order of their due dates. A phase may start only if its **entry criteria** are met. Claude Code implements, and Abhishek reviews, approves and commits each task.
2. **Build against contracts, not against each other.** From **Oct 8** everyone codes against the frozen `common/schemas.py`, and uses **fixtures or mocks** until the real upstream piece lands. Nobody waits idle.
3. **Tasks in order** within a track, unless a task is marked `∥` (can run in parallel).
4. **Done means the Definition of Done.** A task isn't done until every bullet in its *Done when* list is true and the change is merged to `main` (RULEBOOK §16).
5. **No unplanned work.** If an idea isn't a task in this file, write it in the [Parking lot](#parking-lot) and keep going.
6. **Behind schedule? Cut, don't extend.** Use the phase's **cut list** the same day a task slips by more than one day. **The Oct 30 submission date never moves.**
7. **Integrate every day.** `main` must run end to end (`make up` + `make smoke-vm`, and later the full loop) at the end of every day. No integration crunch at the end.
8. **Daily progress note** using the [template](#daily-stand-up-template). Milestone demos happen on M1, M2, M3 and M4. Every milestone demo is also a rehearsal for the **final live demonstration**.
9. **The report is written continuously** (Phase 7 starts Oct 13), not in the last week.

---

## 2. Change control

Use this process for any change to scope, schedule, contracts or technology choices.

1. **Write it down.** Add a row to the [Deviation log](#deviation-log) saying what changes, why, and the impact.
2. **Write an ADR** if it changes a technology, schema or architecture decision: `docs/adr/NNN-title.md`.
3. **Abhishek approves** (sole decision-maker, decisions Q6).
4. **Update this file** and bump the version.
5. **Only then** start the work.

**Doesn't need change control:** bug fixes, refactors inside one module that keep its interface, tests, docs, and using a cut-list item (just log it in the stand-up).

---

## 3. Scope lock (v2.0)

### In scope

| Area | v2.0 scope |
|---|---|
| Network | **Fully virtual** (decisions Q2): Mininet-WiFi + wmediumd + Open vSwitch + Ryu 4.34 on the Ubuntu 20.04 VM |
| Topology | One campus: **4 APs, 2 switches, 20 stations**, 4 zones |
| Scenarios | `normal` (training data), and for evaluation: `lecture_flash_crowd`, `ap_failure`, `cochannel_interference` |
| Telemetry | Collector → **InfluxDB directly** (MQTT optional), Grafana |
| Twin | State sync, **analytical simulator**, verifier, `/twin/simulate` API |
| ML | Baseline + Holt-Winters forecaster, Isolation Forest anomaly detector, **heuristic optimizer**, executor with rollback, loop orchestrator |
| GenAI | **Ollama: `gpt-oss:120b-cloud` with automatic local fallback `qwen2.5:3b`** (decisions Q3, ADR-001): intent → policy → compiler → twin check; copilot with tools; root-cause explanations |
| UI | **Streamlit** dashboard + Grafana |
| Evaluation | **3 variants** (V1 baseline, V2 heuristics without twin, V3 full system) × **3 scenarios** × **3 seeds** = 27 runs; intent accuracy on 30 intents |
| Deliverables | **Report** + **live demonstration** (a backup screen recording is kept in case the live demo fails). No slides required. |

### Out of scope (parking lot / future work)

- Real hardware (decided: fully virtual)
- GNN surrogate, cloned-emulation twin
- LSTM / TFT forecasting, **RL (PPO)**, TimeGAN synthetic data
- RAG vector database (the copilot uses tools only), what-if scenario generator, config synthesis
- Paid hosted LLM APIs (Claude / GPT / Gemini API keys), LLM fine-tuning
- React dashboard, random-waypoint mobility, voip profile, mixed video + bulk scenario
- ns-3, OMNeT++, P4, ONOS/ODL, Kubernetes, 5G/LTE, multi-controller, mobile app

### Parking lot

| Date | Idea | Raised by | Notes |
|---|---|---|---|
| | | | |

---

## 4. How to read a phase

| Section | Meaning |
|---|---|
| **Objective** | One sentence. If a task doesn't serve it, it doesn't belong. |
| **Entry criteria** | Must be true before starting. |
| **Tasks** | `Px.y` · owner role · **due date** · files produced · *Done when* checklist. `∥` = parallel. |
| **Exit gate** | Checklist. All items ticked closes the phase. |
| **Cut list** | What to drop, in order, if the phase is behind. |
| **Do not** | Common diversions to avoid. |

**Roles:** NET = Network engineer · TWIN = Twin and data engineer · ML = ML engineer · GENAI = GenAI and full-stack · **DOC = Report, evaluation and QA lead** (owns the report, literature review, test/demo runbooks and evaluation runs; acts as the independent tester). Names go in [§6](#6-status-board).

---

## 5. Calendar and milestones

```text
            Oct  6  7  8  9 10 11 12 | 13 14 15 16 17 18 19 | 20 21 22 23 24 25 26 | 27 28 29 30 31
P0 setup         ■  ■  ■             |                      |                      |
P1 testbed  NET     ■  ■  ■  ■  ■  ■ |                      |                      |
P2 telemetry TWIN      ■  ■  ■  ■  ■ | ■  ■                 |                      |
P3 twin     TWIN                     | ■  ■  ■  ■  ■  ■  ■  |                      |
P4 ML/exec  ML            ■  ■  ■  ■ | ■  ■  ■  ■  ■  ■  ■  |                      |
P5 GenAI    GENAI      ■  ■  ■  ■  ■ | ■  ■  ■  ■  ■  ■  ■  | ■  ■  ■              |
P6 integ+eval all                    |                      | ■  ■  ■  ■  ■  ■  ■  | ■  ■
P7 report   all                      | ■  ■  ■  ■  ■  ■  ■  | ■  ■  ■  ■  ■  ■  ■  | ■  ■  ■  ■
Milestones          M0          M1   |                   M2 |             M3       |    M4    ★ submit Oct 30
```

| ID | Date | Milestone | Demo |
|---|---|---|---|
| M0 | **Oct 8** | Contracts frozen, campus layout fixed, LLM model chosen | schemas PR merged |
| M1 | **Oct 12** | A scenario runs on the campus topology and telemetry lands in InfluxDB/Grafana | flash crowd visible in Grafana |
| M2 | **Oct 19** | Closed loop applies a **twin-verified** action, and rollback works | loop on vs off during a flash crowd |
| M3 | **Oct 24** | LLM intents + copilot through the twin, dashboard works, **code freeze `eval-v1`** | full demo from the dashboard |
| M4 | **Oct 28** | Evaluation done, figures generated, backup demo recording made | results tables |
| ★ | **Oct 30** | **Report submitted + live demonstration ready** (Oct 31 is the spare day) | full live demo |

---

## 6. Status board

**Team** *(report authors; all development by Aggimalla Abhishek with Claude Code, decisions Q6)*

| Name | Roll no. | Role | Track |
|---|---|---|---|
| Aggimalla Abhishek | 23BDS004 | | |
| N. Likhith Naik | 23BDS037 | | |
| Sundaram | 23BDS060 | | |
| Sambhav Mishra | 23BDS050 | | |
| Bikram Hawaldar | 23BCS033 | | |

| Role | Track |
|---|---|
| NET | Phase 1, then P4.4 executor support, then P6.2 demo setup |
| TWIN | Phase 2 → Phase 3, then the loop |
| ML | Phase 4, then evaluation analysis (P6.6) |
| GENAI | Phase 5 → Streamlit dashboard |
| DOC | P0.4 literature, Phase 7 report, test runbooks, P6.4 evaluation runs, independent testing of every milestone |

**Phases**

| Phase | Dates | Status | Exit gate | Notes |
|---|---|---|---|---|
| 0 Setup & contracts | Oct 6–8 | 🟦 In progress | | P0.2 ✅, P0.3 ✅, P0.5 ✅, P0.7 ✅ (gpt-oss:120b-cloud + local qwen2.5:3b); open: P0.6 approval (Abhishek), P0.1 Q4b template, P0.4 literature (Oct 12), VM RAM → 6 GB |
| 1 Testbed | Oct 7–12 | 🟦 In progress | | P1.1 ✅ (2026-10-06) |
| 2 Telemetry | Oct 8–14 | ⬜ | | |
| 3 Twin | Oct 13–19 | ⬜ | | critical path |
| 4 ML + executor | Oct 9–19 | ⬜ | | |
| 5 GenAI | Oct 8–22 | ⬜ | | |
| 6 Integration + eval | Oct 20–28 | ⬜ | | |
| 7 Report + live demo prep | Oct 13–30 | ⬜ | | DOC leads |

Status values: ⬜ Not started · 🟦 In progress · 🟨 At risk · 🟥 Blocked · ✅ Done

---

## Phase 0: Setup and contracts (Oct 6–8)

**Objective:** a working toolchain, fixed decisions, and frozen contracts, so all four tracks can build in parallel from Oct 8.

**Entry criteria:** none.

#### P0.1: Answer the open questions · all · **Oct 6**
- **Produces:** `docs/decisions.md`
- **Done when:**
  - [x] Q1 team and timeline: **5 people**, deadline Oct 31 → this v2.x plan.
  - [x] Q2 hardware: fully virtual.
  - [x] Q3 LLM: Ollama, no paid API budget; cloud model + local fallback (revised 2026-10-07).
  - [x] Q4 deliverables: **report + live demonstration**.
  - [ ] Q4b report template/format: department template if one exists, otherwise our own (P7.1a).
  - [ ] Team confirms ADR-002 (Ryu) and ADR-003 (Ubuntu 20.04).

#### P0.2: Shared testbed VM · NET · **Oct 8**
- **Produces:** VM, `docs/setup.md`, ADR-002, ADR-003
- **Done when:**
  - [x] A 2-AP, 4-station topology with Ryu `simple_switch_13` passes `pingall`. *(2026-10-06: 3 of 3 runs PASS, `testbed/smoke/`)*
  - [ ] VM RAM raised to 6 GB in UTM (shut down first).
  - [x] `make smoke-vm` works from the Mac over `ssh sdnvm`. *(Per-member keys not needed: solo, decisions Q6)*

#### P0.3: Repo skeleton · GENAI · **Oct 6**
- **Done when:**
  - [x] `docker compose up` starts all three services and they are healthy. *(2026-10-06: MQTT round trip, InfluxDB bucket and Grafana data source verified)*
  - [x] CI runs green. *(2026-10-06: run 37425770707 on `3ca050b`)*
  - [x] ~~`main` is branch-protected; PRs need 1 review~~ → **solo workflow** (deviation #5): direct commits to `main` are allowed because pre-commit runs `make check` locally and CI runs on every push. A red CI on `main` is fixed or reverted immediately (RULEBOOK B-10).

#### P0.4: Literature review (5 papers) · all (1 each), DOC edits · **Oct 12** · ∥
- **Produces:** `docs/literature/<topic>.md` with summary, what we reuse, and citation (digital twin networks · RouteNet/GNN performance models · LLM intent-based networking · Wi-Fi channel/load-balancing optimization)
- **Done when:**
  - [ ] 5 summaries exist (the 5th topic is SDN for wireless / Mininet-WiFi). They feed the report's Related Work section (P7.1).
- *Does not block M0.*

#### P0.5: Problem statement, KPIs, campus layout · all · **Oct 7**
- **Produces:** `docs/problem_statement.md`, `docs/scenario.md`
- **Done when:**
  - [x] KPIs with targets: throughput, latency, loss, Jain fairness, time to recover, twin MAPE, intent accuracy. *(2026-10-07: `docs/problem_statement.md`)*
  - [x] Campus fixed: 4 APs (positions, channels), 2 switches, 20 stations, 4 zones, and the 4 scenario definitions. *(2026-10-06: `docs/scenario.md`, `config/campus_v1.yaml`)*

#### P0.6: Freeze data contracts · TWIN + GENAI · **Oct 8**
- **Produces:** `common/schemas.py`, `common/config.py`, `config/*.yaml`, `tests/unit/test_schemas.py`
- **Done when:**
  - [x] Telemetry records, `Action` (allow-list + bounds), `Policy`, `Verdict` (with `KPIValues`), `Scenario` are implemented as Pydantic models (PROJECT_PLAN §7). *(2026-10-06: `common/schemas.py`; static bounds in schemas, state-dependent bounds documented for the verifier P3.4)*
  - [x] Every schema has valid and invalid examples in tests. Bounds are enforced by validators (100% branch coverage). *(2026-10-06: `tests/unit/test_schemas.py`, 82 tests incl. hypothesis; `common/schemas.py` 100% statements + branches)*
  - [ ] Abhishek approves `common/schemas.py` + `docs/scenario.md`. **Contracts are then frozen.**

#### P0.7: Local LLM setup · GENAI · **Oct 8** · ∥
- **Produces:** `docs/adr/001-llm-provider.md`, a model choice in `config/llm.yaml`
- **Done when:**
  - [x] 2–3 local models are compared on 5 sample intents for valid JSON and correct fields, then one is picked. *(2026-10-07: phi3 / qwen2.5:3b / qwen2.5:7b → **qwen2.5:3b**, 5/5, ADR-001)*
  - [x] It fits in memory alongside Docker and the VM (16 GB Mac). Record peak RAM. *(2.2 GB resident)*
  - [x] A one-line script gets a schema-valid JSON reply from the chosen model. *(`make llm-check`)*
  - [x] Cloud models compared too (round 3): **gpt-oss:120b-cloud** 5/5, 1.6 s → main model, qwen2.5:3b → local fallback; 2 cloud models found retired (deviation #6).

### Exit gate (M0, Oct 8)
- [ ] P0.1, P0.3, P0.5, P0.6, P0.7 done (P0.4 continues to Oct 12; P0.2 RAM and access by Oct 8)
- [ ] Status board names filled in

**Cut list:** (1) compare only 2 LLMs; (2) literature review becomes 1 combined page.
**Do not:** start building features before schemas are frozen, except throwaway spikes.

---

## Phase 1: Wireless SDN testbed (Oct 7–12) · NET

**Objective:** a reproducible campus network we can run from a scenario file, observe through REST, and control through an AP agent.

**Entry criteria:** P0.2 smoke passing ✅. Uses `docs/scenario.md` (P0.5, Oct 7).

| ID | Task | Due | Produces | Done when |
|---|---|---|---|---|
| P1.1 ✅ | Campus topology (4 APs, 2 switches, 20 stations, wmediumd), using `ensure_associated()` | Oct 8 | `testbed/topologies/campus_v1.py`, `testbed/layout.py`, `testbed/connectivity.py`, `config/campus_v1.yaml` | All 20 stations associate; **every pair reachable (retry up to 3 pings) and first-try single-ping loss ≤ 5%** (changed from "0% pingall", deviation #4), 3/3 runs. *(2026-10-06: `make campus-vm` 3/3 PASS, 420/420 reachable, loss 1.4–2.6%)* |
| P1.2 | Ryu app: L2 forwarding, port/flow stats every 1 s, REST `GET /stats/ports`, `/stats/flows`, `/topology`, `POST/DELETE /flows`, `POST /qos/queue` | Oct 9 | `controller/apps/twin_controller.py` | Responses validate against schemas; an installed flow changes the path (`ovs-ofctl dump-flows`) |
| P1.3 | AP agent inside the topology process: `GET /aps`, `/aps/{id}/stats`, `/stations`; `POST /aps/{id}/channel`, `/txpower`, `/stations/{id}/associate` | Oct 10 | `testbed/ap_agent.py` | POSTs change state; out-of-bounds values return 422 |
| P1.4 | Scheduled-crowd mobility (group moves zone A → B over a time window) | Oct 10 ∥ | `testbed/mobility/` | 10 stations move to the lecture hall and re-associate |
| P1.5 | Traffic profiles (video, web, bulk) + KPI probe (throughput, latency, jitter, loss per flow) | Oct 11 ∥ | `testbed/traffic/` | Probe outputs schema-valid KPI records |
| P1.6 | Scenario runner + 4 scenario YAMLs | Oct 12 | `testbed/run_scenario.py`, `experiments/scenarios/*.yaml` | 10-minute run without manual steps; same seed ×3 gives throughput within ±5% |

**Exit gate (part of M1, Oct 12):** P1.1–P1.6 done · REST + AP agent live · `lecture_flash_crowd` reproducible · `docs/setup.md` explains how to run a scenario.

**Cut list:** (1) 15 stations instead of 20; (2) drop P1.4 and use scripted re-association instead of movement; (3) bulk + video profiles only.
**Do not:** add topologies, tune radio realism, or build the collector (that's TWIN's job).

---

## Phase 2: Telemetry and dataset (Oct 8–14) · TWIN

**Objective:** live telemetry in InfluxDB on schema, plus a labelled dataset for the forecaster, anomaly detector and twin validation.

**Entry criteria:** schemas (P0.6). Until P1.2/P1.3 land (Oct 9–10), develop against **recorded fixtures** of their JSON responses.

| ID | Task | Due | Produces | Done when |
|---|---|---|---|---|
| P2.1 | Collector: polls Ryu REST + AP agent every 1–2 s, validates against schemas, writes to InfluxDB (measurements from PROJECT_PLAN §7.1, tagged `scenario_id`, `run_id`) | Oct 11 | `telemetry/collector/` | Lag < 2 s; no gaps > 5 s in a 30-minute run; invalid data logged and dropped |
| P2.2 | Grafana dashboard (provisioned): per-AP load, link utilization, per-flow KPIs | Oct 12 ∥ | `telemetry/grafana/dashboards/raw_kpis.json` | Flash crowd is visible live |
| P2.3 | Batch runner (N scenarios × M seeds, resets the network between runs) + dataset export to Parquet | Oct 14 | `experiments/run_batch.py`, `experiments/export_dataset.py`, `docs/dataset.md` | **≥ 1 hour** of labelled telemetry across 4 scenarios; split by run |

**Exit gate (part of M1 for P2.1–P2.2; P2.3 by Oct 14).**

**Cut list:** (1) 40 minutes of data; (2) Grafana shows APs only.
**Do not:** add Kafka, or route through MQTT unless it's free (optional).

---

## Phase 3: Digital twin core (Oct 13–19) · TWIN

> ⚠ **Critical path.** If it's behind on Oct 16, apply the cut list immediately.

**Objective:** a twin that mirrors live state and predicts the KPI effect of an action fast enough for the loop.

**Entry criteria:** P2.1 done (live telemetry). P2.3 is needed for P3.5 validation.

| ID | Task | Due | Produces | Done when |
|---|---|---|---|---|
| P3.1 | `TwinState` builder + incremental sync from InfluxDB | Oct 14 | `twin/state/` | Matches the controller/AP agent view; lag < 3 s; replay test with recorded telemetry |
| P3.2 | Apply each allow-listed `Action` to a **copy** of the state | Oct 15 | `twin/sim/apply.py` | Unit test per action type; the original state is never mutated |
| P3.3 | Analytical simulator: link queueing delay + Wi-Fi airtime model with a co-channel overlap penalty → throughput, latency, loss, AP utilization, Jain | Oct 16 | `twin/sim/analytical.py` | < 1 s per simulation; property tests (`hypothesis`) for invariants |
| P3.4 | Verifier: acceptance rule (PROJECT_PLAN §7.5), policy checks, impact class | Oct 17 | `twin/verify/` | **100% branch coverage**: accept, reject-regression, reject-policy, needs-approval |
| P3.5 | Validation: predicted vs measured on real actions | Oct 18 | `twin/validation/`, `experiments/notebooks/02_twin_validation.ipynb` | MAPE reported; **throughput MAPE < 20%** (target < 15%) |
| P3.6 | `POST /twin/simulate`, `GET /topology`, `GET /metrics` (FastAPI) | Oct 17 ∥ (GENAI helps) | `api/` | Schema-valid `Verdict` for every action type |

**Exit gate (part of M2, Oct 19):** P3.1–P3.6 done · twin services run in Docker Compose.

**Cut list:** (1) MAPE < 25%, stated as a limitation; (2) load-only airtime model; (3) verifier only checks KPI deltas, with policy checks moved to the intent compiler.
**Do not:** start a GNN, add action types, or build UI.

---

## Phase 4: Intelligence and executor (Oct 9–19) · ML

**Objective:** a closed loop that only ever applies **verified** actions, rolls back bad ones, and beats the baseline on at least one KPI.

**Entry criteria:** schemas (P0.6). Before the real dataset (Oct 14), use **synthetic series and fixture states**.

| ID | Task | Due | Produces | Done when |
|---|---|---|---|---|
| P4.1 | Forecaster: moving-average baseline + Holt-Winters, per-AP load at t+1/t+3 min | Oct 15 | `ml/forecast/` | Beats the baseline on RMSE on the test split (or is reported honestly) |
| P4.2 | Anomaly detector: Isolation Forest on windowed AP/link features | Oct 15 ∥ | `ml/anomaly/` | Precision/recall/F1 on labelled events; alerts fire in `ap_failure` |
| P4.3 | Heuristic optimizer: least-loaded AP steering, non-overlapping channel choice, shortest-delay reroute → `Action[]` | Oct 13 | `ml/optimizer/heuristics.py` | Sensible candidates for each scenario (fixture-state unit tests) |
| P4.4 | Action executor: applies only actions with an accepted `Verdict`, stores the previous config, watches KPIs 30 s, rolls back on > 10% regression, rate-limits, writes an audit log | Oct 17 (NET helps with the AP agent/Ryu calls) | `controller/executor/` | **100% branch coverage**; unverified action refused; deliberate bad action rolled back |
| P4.5 | Loop orchestrator (5 s period), `--mode V1/V2/V3` for evaluation | Oct 19 (with TWIN) | `twin/loop.py`, `config/loop.yaml` | Runs a full flash crowd unattended; V3 beats V1 on time to recover (3 seeds) |

**Exit gate (M2, Oct 19):** P4.1–P4.5 done · audit log shows every applied action has an accepted verdict · rollback demonstrated.

**Cut list:** (1) forecaster = moving average only; (2) anomaly = static thresholds; (3) heuristics = AP steering + channel only.
**Do not:** start RL; tune hyperparameters past Oct 17.

---

## Phase 5: GenAI layer (Oct 8–22) · GENAI

**Objective:** natural-language control and explanation using a **local Ollama model**, where every LLM-originated action goes through the twin.

**Entry criteria:** P0.7 model chosen. Tools use **mocks** until P3.6 lands (Oct 17).

| ID | Task | Due | Produces | Done when |
|---|---|---|---|---|
| P5.1 | LLM client for Ollama (structured JSON output, timeout, retries) with **automatic fallback from the cloud model to the local model** on error/timeout; logs model used, tokens, latency and validity | Oct 9 | `genai/llm/client.py` | Schema-valid output on test prompts; every call logged |
| P5.2 | Tool layer: `get_topology`, `get_metrics`, `get_alerts`, `simulate_in_twin`, `apply_action` (verified IDs only) | Oct 13 (mocks) → Oct 20 (live) | `genai/tools/` | Live data by Oct 20; `apply_action` refuses unverified IDs |
| P5.3 | Intent engine: prompt + few-shot → `Policy` JSON → validation and repair (≤ 2 retries) → **deterministic compiler** → twin verify → `POST /intents` | Oct 16 | `genai/intent/`, `genai/prompts/` | Compiler at 100% branch coverage; invalid LLM output never reaches it |
| P5.4 | Intent test set: **30 intents** with expected policies (Claude drafts, Abhishek checks) + eval script | Oct 15 ∥ | `genai/eval/intents.jsonl`, `genai/eval/run_intents.py` | Script reports accuracy |
| P5.5 | Copilot: tool-using agent, `POST /chat` | Oct 20 | `genai/agent/` | Answers 5 diagnostic questions with live evidence; proposed actions go through `simulate_in_twin` |
| P5.6 | Root-cause explainer on anomaly alerts | Oct 22 | `genai/rca/` | Correct diagnosis for `ap_failure` and `cochannel_interference` runs |

**Exit gate (part of M3, Oct 24):** P5.1–P5.6 done · ≥ 20 of 30 intents correct · 100% of LLM actions have a twin verdict in the audit log.

**Cut list:** (1) drop P5.6 and show anomaly details in the dashboard instead; (2) intents limited to QoS priority + AP steering + channel; (3) copilot answers only, without proposing actions.
**Do not:** add RAG or a vector DB, call paid hosted APIs, or let the LLM touch the controller or AP agent directly.

---

## Phase 6: Integration, dashboard, evaluation (Oct 20–28) · all

**Objective:** the whole system runs from one command, and the evaluation results are generated by script.

**Entry criteria:** M2 passed (Oct 19).

| ID | Task | Owner | Due | Done when |
|---|---|---|---|---|
| P6.1 | Streamlit dashboard: topology with AP load colours, KPI charts, twin vs live, action log with approve/deny, chat | GENAI | Oct 23 | All panels work during a live scenario; high-impact actions can be approved |
| P6.2 | One-command demo (`make demo`) + **live demo script** `docs/runbooks/demo.md` (steps, talking points, fallback for each step) | NET + DOC | Oct 23 ∥ | Abhishek runs the full demo from the runbook alone, from a cold start |
| P6.3 | **Code freeze: tag `eval-v1`** | all | **Oct 24** | Only evaluation-blocking fixes after this |
| P6.4 | Experiment campaign: V1/V2/V3 × 3 scenarios × 3 seeds (27 runs) | DOC + NET | Oct 26 | All runs complete; failed runs re-run and logged |
| P6.5 | Twin-blocking analysis (V2 actions the twin would reject) + intent eval (30) + LLM latency | TWIN + GENAI | Oct 27 ∥ | Numbers in `experiments/results/` |
| P6.6 | Analysis scripts → all tables and figures (mean ± 95% CI) | ML | Oct 28 | One command regenerates every figure; nothing made by hand |

**Exit gate (M4, Oct 28):** P6.1–P6.6 done · headline claim tested, with the result written down whether it holds or not.

**Cut list:** (1) 2 seeds instead of 3, stated in the report; (2) drop `cochannel_interference` from the evaluation; (3) dashboard without the chat panel (use the API).
**Do not:** add features after `eval-v1`, re-tune to improve results, or change scenarios mid-campaign.

---

## Phase 7: Report and submission (Oct 13–30) · all

**Objective:** a complete, honest report submitted on **Oct 30**, and a **live demonstration** that runs reliably from a cold start.

| ID | Task | Owner | Due | Done when |
|---|---|---|---|---|
| P7.1a | Report skeleton + title page + Introduction + Related Work (from P0.4) | **DOC** | Oct 15 | Sections drafted in `docs/report/` |
| P7.1b | System architecture + design sections | TWIN + NET | Oct 20 | Drafted with diagrams |
| P7.1c | Method: twin model, heuristics, intent pipeline, safety model | ML + GENAI | Oct 25 | Drafted |
| P7.1d | Results + discussion + limitations + future work (GNN, RL, RAG, hardware) | ML + all | Oct 28 | Drafted from P6.6 figures only |
| P7.2 | Full draft reviewed end to end by Abhishek | DOC | **Oct 29** | Every section read and approved |
| P7.3 | **Backup demo recording** (5–8 min screen capture of the live demo script), used only if the live demo fails | GENAI + DOC | Oct 28 | Stored locally + link in README |
| P7.4 | **Live demonstration rehearsal** ×2 on the actual demo machine, from a cold start (`make demo`), including the failure fallbacks, **one of them with internet off** (LLM falls back to local) | all | Oct 29 | Two clean end-to-end runs; talking points rehearsed |
| P7.5 | Repo clean-up: README, setup, runbooks; fresh clone → demo works | DOC | Oct 29 | Verified from a fresh clone |
| ★ | **Submit** | all | **Oct 30** | Submitted; Oct 31 is spare |

---

## Daily stand-up template

Append to `docs/progress.md` every day (5 minutes).

```markdown
### YYYY-MM-DD (day N/25) · next milestone: Mx on <date>

| Role | Yesterday (task IDs) | Today (task IDs) | Blocked by |
|---|---|---|---|
| NET | | | |
| TWIN | | | |
| ML | | | |
| GENAI | | | |
| DOC | | | |

**main runs end to end today?** yes / no
**Cut-list items used:**
**Change requests (see deviation log):**
```

---

## Deviation log

Every change to this plan goes here **before** the work starts.

| # | Date | Version | Change | Reason | Impact | ADR | Agreed by |
|---|---|---|---|---|---|---|---|
| 0 | 2026-10-06 | v1.0 | Baseline plan created | — | — | — | — |
| 1 | 2026-10-06 | v1.1 | Testbed VM: Ubuntu 20.04 (not 22.04), ~4 GB RAM (raise to 6 GB), 21 GB root | Existing VM already works (`mac80211_hwsim` loads on arm64); Ryu runs natively on Python 3.8; no rebuild time | None on schedule. VM-side code must stay Python 3.8-compatible | [ADR-003](adr/003-vm-ubuntu-20-04.md) | Abhishek (team to confirm) |
| 2 | 2026-10-06 | **v2.0** | **Timeline 16 weeks → 25 days (submit Oct 30, deadline Oct 31)**; parallel tracks; scope cut: analytical twin only (no GNN/emulation twin), heuristics only (no RL), no LSTM/TimeGAN, copilot without RAG, Streamlit instead of React, evaluation 3 variants × 3 scenarios × 3 seeds; **LLM = Ollama only**; fully virtual | P0.1 answers: 4 people, deadline end of October, no API budget, no hardware | Whole plan rewritten. Removed items become future work in the report | ADR-001 (P0.7) | Abhishek (team to confirm) |
| 3 | 2026-10-06 | **v2.1** | Team is **5 people** (new DOC role: report, evaluation and QA lead); deliverables are **report + live demonstration** (no slides; demo video becomes a backup recording only); P0.4 → 5 papers; P7.4 → live demo rehearsals | Team confirmed names; project requirements are a report and a live demo | Load per person drops; DOC frees the engineers from report writing | — | Abhishek (team to confirm) |
| 4 | 2026-10-06 | v2.1 | P1.1 criterion: "pingall 0% loss" → **100% pair reachability (≤ 3 pings per failed pair) + first-try single-ping loss ≤ 5%** | wmediumd interference mode drops frames like real Wi-Fi. Without interference: 0% loss (2/2 runs). With it: 0.5–2.6% loss over 8 runs, always on 2-radio-hop station↔station pairs, all recovered on retry. A 0% (or 2%) criterion would be flaky (RULEBOOK T-4) | None on schedule; loss is reported in every run and in the report | — | Abhishek |
| 5 | 2026-10-07 | **v2.2** | **Solo build:** all work by Abhishek with Claude Code; the other 4 members are report authors only. Approvals = Abhishek; tracks run sequentially in due-date order; stand-up → daily note; branch protection/PR review dropped (direct commits to `main`, guarded by pre-commit + CI). Ryu (ADR-002) and Ubuntu 20.04 (ADR-003) confirmed | Decisions Q5, Q6 | Milestone dates unchanged; more work per day, so cut lists are applied earlier if a milestone slips | ADR-002, ADR-003 | Abhishek |
| 6 | 2026-10-07 | **v2.3** | **LLM: Ollama cloud `gpt-oss:120b-cloud` as main model, automatic fallback to local `qwen2.5:3b`** (was: local only). `qwen2.5:7b` removed | Round 3 of P0.7: all available models 5/5; 120b fastest (1.6 s) and largest; no local RAM. 2 cloud models found retired | Live demo gains an internet dependency → mitigated by automatic local fallback + one offline rehearsal (P7.4); P5.1 must implement the fallback | ADR-001 (revised) | Abhishek |
