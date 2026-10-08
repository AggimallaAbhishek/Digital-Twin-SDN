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

- **MCP server for the P5.2 tools** (2026-10-08): the plan allows MCP and/or plain tools; plain Python tools are enough for the agent. Add an MCP server only if the dashboard or Claude Code needs the tools.
- **Scope-level rate limits** (2026-10-08, P5.3 review): a throughput cap compiles to per-flow `rate_limit_flow` actions, so a flow that starts later is not capped. A rate limit that matches by zone/app class (like `QosMatch`) needs a `common/schemas.py` change → ADR + Abhishek's approval.
- **One action-id helper in `common/`** (2026-10-08, P5.3 review): `genai/intent/compiler.py` and `ml/optimizer/heuristics.py` build `act_<ts>_<n>_<hash>` ids the same way; genai and ml can't import each other. Moving it to `common/` needs an ADR.

| Date | Idea | Raised by | Notes |
|---|---|---|---|
| 2026-10-07 | RSSI-threshold roaming during crowd walks (roam to the strongest AP when the signal drops below −75 dBm) instead of joining the nearest AP on arrival | Claude (P1.4 design, option B) | More realistic, but weakens the flash crowd on ap1. P1.4 uses nearest-AP-on-arrival (decision A). Revisit only if evaluation needs mid-walk roaming |

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
| Aggimalla Abhishek | 23BDS004 | NET, TWIN, ML, GENAI, DOC (all development and approvals) | all |
| N. Likhith Naik | 23BDS037 | report author | — |
| Sundaram | 23BDS060 | report author | — |
| Sambhav Mishra | 23BDS050 | report author | — |
| Bikram Hawaldar | 23BCS033 | report author | — |

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
| 1 Testbed | Oct 7–12 | ✅ Done (Oct 8) | M1 testbed part met | P1.1–P1.5 ✅ (Oct 6–7), P1.6 ✅ (Oct 8) |
| 2 Telemetry | Oct 8–14 | ✅ Done (Oct 8) | met | P2.1 ✅, P2.2 ✅, P2.3 ✅ (all Oct 8); dataset `data/v1/` (2 h) |
| 3 Twin | Oct 13–19 | 🟦 In progress | | critical path; P3.1 ✅, P3.2 ✅, P3.3 ✅ (Oct 8) |
| 4 ML + executor | Oct 9–19 | 🟦 In progress | | P4.1 ✅ (honest negative), P4.2 ✅, P4.3 ✅ (Oct 8) |
| 5 GenAI | Oct 8–22 | 🟦 In progress | | P5.1 ✅ (Oct 7); P5.2 mock part done (Oct 8), live by Oct 20; P5.4 drafted (Oct 8), awaiting Abhishek's check; P5.3 ✅ (Oct 8): cloud 30/30, local 21/30 |
| 6 Integration + eval | Oct 20–28 | ⬜ | | |
| 7 Report + live demo prep | Oct 13–30 | 🟦 In progress | | P7.1a ✅ (Oct 8) |

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
  - [x] ADR-002 (Ryu) and ADR-003 (Ubuntu 20.04) confirmed. *(2026-10-07: Abhishek, deviation #5; solo build, decisions Q6)*

#### P0.2: Shared testbed VM · NET · **Oct 8**
- **Produces:** VM, `docs/setup.md`, ADR-002, ADR-003
- **Done when:**
  - [x] A 2-AP, 4-station topology with Ryu `simple_switch_13` passes `pingall`. *(2026-10-06: 3 of 3 runs PASS, `testbed/smoke/`)*
  - [x] VM RAM raised to 6 GB in UTM (shut down first). *(2026-10-07: `free -m` 5925 MB total)*
  - [x] `make smoke-vm` works from the Mac over `ssh sdnvm`. *(Per-member keys not needed: solo, decisions Q6)*

#### P0.3: Repo skeleton · GENAI · **Oct 6**
- **Done when:**
  - [x] `docker compose up` starts all three services and they are healthy. *(2026-10-06: MQTT round trip, InfluxDB bucket and Grafana data source verified)*
  - [x] CI runs green. *(2026-10-06: run 37425770707 on `3ca050b`)*
  - [x] ~~`main` is branch-protected; PRs need 1 review~~ → **solo workflow** (deviation #5): direct commits to `main` are allowed because pre-commit runs `make check` locally and CI runs on every push. A red CI on `main` is fixed or reverted immediately (RULEBOOK B-10).

#### P0.4: Literature review (5 papers) · all (1 each), DOC edits · **Oct 12** · ∥
- **Produces:** `docs/literature/<topic>.md` with summary, what we reuse, and citation (digital twin networks · RouteNet/GNN performance models · LLM intent-based networking · Wi-Fi channel/load-balancing optimization)
- **Done when:**
  - [ ] 5 summaries exist (the 5th topic is SDN for wireless / Mininet-WiFi). They feed the report's Related Work section (P7.1). *(2026-10-08: 5 drafts in `docs/literature/`, every citation checked against Crossref; **awaiting Abhishek's check against the full texts**, then tick)*
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
- [x] Status board names filled in *(2026-10-07)*

**Cut list:** (1) compare only 2 LLMs; (2) literature review becomes 1 combined page.
**Do not:** start building features before schemas are frozen, except throwaway spikes.

---

## Phase 1: Wireless SDN testbed (Oct 7–12) · NET

**Objective:** a reproducible campus network we can run from a scenario file, observe through REST, and control through an AP agent.

**Entry criteria:** P0.2 smoke passing ✅. Uses `docs/scenario.md` (P0.5, Oct 7).

| ID | Task | Due | Produces | Done when |
|---|---|---|---|---|
| P1.1 ✅ | Campus topology (4 APs, 2 switches, 20 stations, wmediumd), using `ensure_associated()` | Oct 8 | `testbed/topologies/campus_v1.py`, `testbed/layout.py`, `testbed/connectivity.py`, `config/campus_v1.yaml` | All 20 stations associate; **every pair reachable (retry up to 3 pings) and first-try single-ping loss ≤ 5%** (changed from "0% pingall", deviation #4), 3/3 runs. *(2026-10-06: `make campus-vm` 3/3 PASS, 420/420 reachable, loss 1.4–2.6%)* |
| P1.2 ✅ | Ryu app: L2 forwarding, port/flow stats every 1 s, REST `GET /stats/ports`, `/stats/flows`, `/topology`, `POST/DELETE /flows`, `POST /qos/queue` | Oct 9 | `controller/apps/twin_controller.py`, `controller/apps/ryu_logic.py` | Responses validate against schemas; an installed flow changes forwarding (`ovs-ofctl dump-flows`). *(2026-10-07: `make controller-vm` 19/19 checks, 3/3 runs: drop flow blocks sta1→srv1 and DELETE restores it; 400/404/409 errors; QoS flow installs. Contract test: real responses validate as `PortStats`/`FlowStats`. `ryu_logic` 100% branch coverage)* |
| P1.3 ✅ | AP agent inside the topology process: `GET /aps`, `/aps/{id}/stats`, `/stations`; `POST /aps/{id}/channel`, `/txpower`, `/stations/{id}/associate` | Oct 10 | `testbed/ap_agent.py` | POSTs change state; out-of-bounds values return 422 *(2026-10-07: `make ap-agent-vm` 29/29 checks, 3/3 runs: ap1 → ch 6 via hostapd CSA and its 3 clients follow; tx power 14 → 10 dBm; sta2 steered ap1 → ap2 and still reaches srv1; 422 for off-plan channel / 25 dBm / bad JSON / non-AP target, 404 for unknown AP/station/path; every change confirmed with `iw`. Found and fixed a P1.2 bug: stale L2 flows after a host move (setup Known problems #11); `make controller-vm` still 19/19. Contract test: real responses validate as `APStats`/`StationStats`. `ap_logic` 100% branch coverage)* |
| P1.4 ✅ | Scheduled-crowd mobility (group moves zone A → B over a time window) | Oct 10 ∥ | `testbed/mobility/` | 10 stations move to the lecture hall and re-associate *(2026-10-07: `make mobility-vm` 12/12 checks, 3/3 runs: 6 corridor + 4 library stations walk to the lecture hall (shortened timeline: leave over 20 s from t=5 s, 1.2 m/s); 344 mid-walk samples within 0.06 m of the planned paths; all 10 re-associate to ap1 (nearest AP, decision P1.4-A), signal ≥ −75 dBm, reach srv1; other 10 untouched; ap1 13 clients; agent stats ≤ 0.02 s throughout (steer now holds the agent lock per command). Controller detected all 10 host moves. `make ap-agent-vm` still 29/29. `crowd.py` 100% branch coverage)* |
| P1.5 ✅ | Traffic profiles (video, web, bulk) + KPI probe (throughput, latency, jitter, loss per flow) | Oct 11 ∥ | `testbed/traffic/` | Probe outputs schema-valid KPI records *(2026-10-07: `make traffic-vm` 21/21 checks, 3/3 runs: video 3.00 / 1.50 Mbit/s (scenario rate override), bulk ≈ 4.6 Mbit/s, web fetches ≈ 4.6 Mbit/s goodput, idle loss 0%, one record per video/bulk flow per 1 s window (web: per window in which a fetch finished); agent `GET /kpi` returns the latest record per flow; `stop_all()` leaves no tool running. Latency = `ping -O` RTT to srv1 (decision P1.5-A), lost pings tracked by sequence number (ping's interval drifts); records reach the collector through `GET /kpi` (decision P1.5-B). Contract test: all 102 recorded records + the `/kpi` response validate as `KPIRecord`. `parse.py`/`profiles.py` 100% branch coverage. `make ap-agent-vm` still 29/29)* |
| P1.6 ✅ | Scenario runner + 4 scenario YAMLs | Oct 12 | `testbed/run_scenario.py`, `experiments/scenarios/*.yaml` | 10-minute run without manual steps; same seed ×3 gives throughput within ±5% *(2026-10-08: `make scenario-repro-vm SCENARIO=lecture_flash_crowd`: 3 unattended 10-min runs PASS (33 flows, ~6,870 KPI records each), per-class mean throughput within **0.98%** (video 0.204/0.203/0.203, web 2.606/2.580/2.556 Mbit/s). Runner: crowd + traffic (selectors resolved at start time, batch start) + events (`force_channel`, `ap_down`/`ap_up` with orphans rejoining the nearest AP after 5 s) + co-channel interference emulation (deviation #7), all exercised in a 90 s smoke scenario. Artefacts per run: manifest (seed, commit, config hash), events, KPIs, summary. Contract test: all 4 YAMLs valid `Scenario`s and parsed identically on the VM. `scenario_plan.py`, `interference.py` 100% branch coverage)* |

**Exit gate (part of M1, Oct 12):** P1.1–P1.6 done · REST + AP agent live · `lecture_flash_crowd` reproducible · `docs/setup.md` explains how to run a scenario.

**Cut list:** (1) 15 stations instead of 20; (2) drop P1.4 and use scripted re-association instead of movement; (3) bulk + video profiles only.
**Do not:** add topologies, tune radio realism, or build the collector (that's TWIN's job).

---

## Phase 2: Telemetry and dataset (Oct 8–14) · TWIN

**Objective:** live telemetry in InfluxDB on schema, plus a labelled dataset for the forecaster, anomaly detector and twin validation.

**Entry criteria:** schemas (P0.6). Until P1.2/P1.3 land (Oct 9–10), develop against **recorded fixtures** of their JSON responses.

| ID | Task | Due | Produces | Done when |
|---|---|---|---|---|
| P2.1 ✅ | Collector: polls Ryu REST + AP agent every 1–2 s, validates against schemas, writes to InfluxDB (measurements from PROJECT_PLAN §7.1, tagged `scenario_id`, `run_id`) | Oct 11 | `telemetry/collector/` | Lag < 2 s; no gaps > 5 s in a 30-minute run; invalid data logged and dropped *(2026-10-08: 30-min `normal` run (`make collect`, 1 s period): 297,531 records, **max lag 1.19 s, max gap 1.01 s**, 0 failed polls. Lag = write time − record ts, excluding the 1,239 records produced before the collector started; a source counts as polled only once its data is stored. Invalid records are logged with the reason and dropped (e.g. a disabled AP's `channel: null`). Two earlier attempts failed, and both were fixed or explained: start-up backlog counted as lag (fixed), and the Mac slept for 131 s mid-run (setup.md #13: runs now under `caffeinate`). Stdlib only (line protocol over urllib); `records.py` 100% branch coverage)* |
| P2.2 ✅ | Grafana dashboard (provisioned): per-AP load, link utilization, per-flow KPIs | Oct 12 ∥ | `telemetry/grafana/dashboards/raw_kpis.json` | Flash crowd is visible live *(2026-10-08: watched live during `lecture_flash_crowd` with the collector: clients per AP show ap1 3 → 13 while ap3 7 → 1 and ap4 5 → 1; ap1 downlink jumps to 3.49 Mbit/s against its 3.45 Mbit/s cap; ap1 airtime rises to 82% across the 80% line; video loss ~53% and throughput 0.18 of 0.4 Mbit/s. Panels: AP downlink/airtime/clients/channel, KPIs by class, link utilisation (% of capacity), latest KPIs per flow. Colours validated for CVD and contrast on Grafana's light and dark surfaces. Contract test: every queried measurement/field is one the collector writes)* |
| P2.3 ✅ | Batch runner (N scenarios × M seeds, resets the network between runs) + dataset export to Parquet | Oct 14 | `experiments/run_batch.py`, `experiments/export_dataset.py`, `docs/dataset.md` | **≥ 1 hour** of labelled telemetry across 4 scenarios; split by run *(2026-10-08: `make batch` 16:16–18:32, **12/12 runs PASS** (4 scenarios × seeds 42/43/44; max lag 1.13–1.21 s, max gap ~1.0 s, no host sleep, VM clock within 0.04 s). `make dataset` → `data/v1/`: **2.0 h of telemetry, 1,485,424 rows** in 5 Parquet files + manifest (commit, config hash, scenarios, seeds). Split by run: seed 42 → train, 43 → val, 44 → test; every run in exactly one split, every scenario in every split. Labels: `phase` switches to stress at 210 s (flash crowd), 240 s (ap_down), 180 s (force_channel); `normal` has none)* |

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
| P3.1 ✅ | `TwinState` builder + incremental sync from InfluxDB | Oct 14 | `twin/state/` | Matches the controller/AP agent view; lag < 3 s; replay test with recorded telemetry *(2026-10-08: `builder.py` (latest record per series; an AP is up if it reported within 5 s) + `sync.py` (each refresh reads the last 10 s of the run via the new `common/influx.py`). Live check `experiments/check_twin_sync.py` during a smoke scenario (crowd walk, forced channel, AP down, rejoins): **98.7% agreement** with the AP agent's /stations and /aps over 32 refreshes, **max lag 1.04 s**. Replay test on 10 s of recorded InfluxDB telemetry (expected values derived independently of the builder). `TwinState` gained `flows`. 100% branch coverage. **2026-10-08 review fix:** lag was measured from the newest row of any measurement and before the queries ran, so a stalled measurement could hide behind fresh KPI rows. It is now the age of the stalest measurement's newest row, taken after the queries. On the replay data that is 0.827 s instead of 0.317 s, so the live 1.04 s above is an underestimate: **re-run the live check on the VM to confirm < 3 s**)* |
| P3.2 ✅ | Apply each allow-listed `Action` to a **copy** of the state | Oct 15 | `twin/sim/apply.py` | Unit test per action type; the original state is never mutated *(2026-10-08: `apply(state, action)` returns a new `TwinState` for all 7 action types (steer, channel, tx power, AP down/up, QoS queue, rate limit, reroute). AP down sends its stations to the nearest AP still up (P1.6-A rule); AP up brings nobody back. Unknown or stale targets (e.g. a steered station not on `from_ap`) raise `ValueError`. Every test also checks the original equals a fresh build. `TwinState` gained tx power, station zone, and flow queue/rate cap/path; the builder fills tx power and zone. 100% branch coverage, strict mypy)* |
| P3.3 ✅ | Analytical simulator: link queueing delay + Wi-Fi airtime model with a co-channel overlap penalty → throughput, latency, loss, AP utilization, Jain | Oct 16 | `twin/sim/analytical.py` | < 1 s per simulation; property tests (`hypothesis`) for invariants *(2026-10-08: `twin/sim/analytical.py`, params `config/sim.yaml`. Per AP that is up: capacity = 4.6 Mbit/s capped by co-channel APs (`twin/radio.py`, the model the testbed emulates); strict priority between queues 1 → 0 → 2, max-min fair within a queue; inelastic video/web lose what they can't send; latency = base + M/M/1/K bounded queue (fitted to the ~8–10 ms plateau in data/v1); web throughput = one fetch's rate, as the probe measures it; dead flows = 0 Mbit/s, 100% loss, 1000 ms. Network KPIs: total throughput, mean latency and loss, Jain of clients per AP. Exact sums (`math.fsum`) so a verdict doesn't depend on dict order (found by a property test). **0.09 ms per simulation** (60 flows). worked-example and `hypothesis` property tests (physical limits, priority and capacity never hurt, order-free) plus a parity test with the traffic profiles, 100% branch coverage. Wired links not modelled (deviation #12); QoS queues not yet in the testbed (deviation #11). Parameters are first estimates from data/v1; P3.5 calibrates them. **Review fixes (2026-10-08):** network throughput now sums the traffic each flow carries (10 web flows summed fetch rates to 36.8 Mbit/s on one 4.6 Mbit/s AP); a capacity ≤ 0 is refused when the radio config is loaded (it crashed the simulator); app classes are one table in `config/sim.yaml` (offered rate, elastic, fetch-measured) instead of web special cases; formulas cited (M/M/1/K, Jain); **`enabled: false`** until M2 (RULEBOOK B-5))* |
| P3.4 | Verifier: acceptance rule (PROJECT_PLAN §7.5), policy checks, impact class | Oct 17 | `twin/verify/` | **100% branch coverage**: accept, reject-regression, reject-policy, needs-approval *(Open from the P3.3/P5.3 review, settle here: (1) the network KPIs the verifier compares: the simulator reports total carried throughput and mean latency/loss over all flows, while problem statement §5.1 defines throughput over affected flows and latency as p95 of video flows; (2) verify a policy's actions together, not only one by one; (3) callers must check `config/sim.yaml` `enabled`)* |
| P3.5 | Validation: predicted vs measured on real actions | Oct 18 | `twin/validation/`, `experiments/notebooks/02_twin_validation.ipynb` | MAPE reported; **throughput MAPE < 20%** (target < 15%) *(From the P3.3 review: bulk is modelled at a measured 0.5 Mbit/s, so a rate limit (≥ 1 Mbit/s) never changes a prediction; check against real runs whether bulk should take the capacity left over)* |
| P3.6 | `POST /twin/simulate`, `GET /topology`, `GET /metrics`, `POST /intents` (FastAPI; the intent engine is P5.3) | Oct 17 ∥ (GENAI helps) | `api/` | Schema-valid `Verdict` for every action type |

**Exit gate (part of M2, Oct 19):** P3.1–P3.6 done · twin services run in Docker Compose.

**Cut list:** (1) MAPE < 25%, stated as a limitation; (2) load-only airtime model; (3) verifier only checks KPI deltas, with policy checks moved to the intent compiler.
**Do not:** start a GNN, add action types, or build UI.

---

## Phase 4: Intelligence and executor (Oct 9–19) · ML

**Objective:** a closed loop that only ever applies **verified** actions, rolls back bad ones, and beats the baseline on at least one KPI.

**Entry criteria:** schemas (P0.6). Before the real dataset (Oct 14), use **synthetic series and fixture states**.

| ID | Task | Due | Produces | Done when |
|---|---|---|---|---|
| P4.1 ✅ | Forecaster: moving-average baseline + Holt-Winters, per-AP load at t+1/t+3 min | Oct 15 | `ml/forecast/` | Beats the baseline on RMSE on the test split (or is reported honestly) *(2026-10-08, **reported honestly: Holt does not beat the baseline**. Per-AP utilisation from `data/v1` at 5 s, rolling-origin, parameters tuned on train only. Test RMSE, baseline vs Holt: **t+1 min 0.117 vs 0.129, t+3 min 0.212 vs 0.256**. Holt wins only in `lecture_flash_crowd` (1 min: 0.125 vs 0.147), the one gradual ramp; in step-like scenarios (AP down, forced channel, flat normal) trend extrapolation overshoots. Holt-Winters without seasonality, own implementation (decision P4.1-A). `experiments/analysis/forecast_eval.py` → `models/forecast/v1/`. 100% branch coverage. **2026-10-08 review fix:** a gap in a series now restarts the forecast history instead of joining the values on both sides. The dataset has no gaps (the failed AP's series just ends), so the re-run numbers are unchanged)* |
| P4.2 ✅ | Anomaly detector: Isolation Forest on windowed AP/link features | Oct 15 ∥ | `ml/anomaly/` | Precision/recall/F1 on labelled events; alerts fire in `ap_failure` *(2026-10-08: Isolation Forest (scikit-learn 1.9.1, seed 42) on whole-network 30 s windows (per AP: utilisation, clients, client change, silent share; network: unassociated stations, loss, p95 latency). Fitted on train-split normal windows, threshold chosen on val (F1 0.977). **Test: precision 0.950, recall 0.979, F1 0.964**; normal run: 0 alerts. **ap_failure: alert 5 s after ap2 went down, 69/72 alerts name ap2**; co-channel detected after 25 s. Flash crowd precision 0.867: alerts while the crowd walks in, before the video onset that starts the stress label. `experiments/analysis/anomaly_eval.py` → `models/anomaly/v1/`. 100% branch coverage. **2026-10-08 review fix:** a window was labelled stress when it *ended* at the onset, though it holds no post-onset data; now only windows with post-onset data are. Re-run: threshold 0.575 → 0.564, test F1 unchanged, ap_failure F1 0.993 → 1.0, flash crowd 12 alerts before onset (was 10))* |
| P4.3 ✅ | Heuristic optimizer: least-loaded AP steering, non-overlapping channel choice, shortest-delay reroute → `Action[]` | Oct 13 | `ml/optimizer/heuristics.py` | Sensible candidates for each scenario (fixture-state unit tests) *(2026-10-08: steering and channel heuristics (reroute dropped: tree topology, deviation #9) on a `TwinState` defined early (`twin/state/model.py`, decision P4.3-A). Fixture states: flash crowd → steer the 3 hall stations nearest ap3 (30% of 13); ap_failure → ap1 sheds 1 station to ap3; ap3 forced to ch 1 → back to ch 11; normal and default channel plan → nothing. Bounds respected: ≤ 30% of clients, predicted signal ≥ −75 dBm (log-distance fit to P1.6 measurements, `twin/radio.py`), never a down AP. Twin and testbed interference models pinned equal by a contract test (81 channel plans × 3 AP-down cases). 100% branch coverage)* |
| P4.4 | Action executor: applies only actions with an accepted `Verdict`, stores the previous config, watches KPIs 30 s, rolls back on > 10% regression, rate-limits, writes an audit log | Oct 17 (NET helps with the AP agent/Ryu calls) | `controller/executor/` | **100% branch coverage**; unverified action refused; deliberate bad action rolled back |
| P4.4a | Provision the QoS queues and flow rate limits the twin models: strict-priority classes 1/0/2 and per-flow limits on each AP's downlink (htb, where the bottleneck is), driven by `set_qos_queue` / `rate_limit_flow` | Oct 17 (before P4.4 applies QoS actions) | `testbed/`, `controller/` | A priority flow keeps its rate while best effort saturates the AP; a rate limit holds within 10% (deviation #11) *(Also decide: the latency probe is one ping per station, which sits in queue 0, so the twin's per-queue latency for priority flows may not be what the probe measures)* |
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
| P5.1 ✅ | LLM client for Ollama (structured JSON output, timeout, retries) with **automatic fallback from the cloud model to the local model** on error/timeout; logs model used, tokens, latency and validity | Oct 9 | `genai/llm/client.py` | Schema-valid output on test prompts; every call logged *(2026-10-07: `make llm-client-check` 6/6: 5 test prompts schema-valid on `gpt-oss:120b-cloud` first try; unknown main model → HTTP 404 → `qwen2.5:3b` answers. Every attempt logged to `logs/llm_calls.jsonl` (no prompt text). Invalid output repaired ≤ 2× on the same model, then `LLMOutputError`; only unreachable models trigger fallback. `client.py` 100% branch coverage)* |
| P5.2 🟦 | Tool layer: `get_topology`, `get_metrics`, `get_alerts`, `simulate_in_twin`, `apply_action` (verified IDs only) | Oct 13 (mocks) → Oct 20 (live) | `genai/tools/` | Live data by Oct 20; `apply_action` refuses unverified IDs *(2026-10-08, mock part done: 5 tools with LLM tool specs over a `Backend` interface; `MockBackend` serves the recorded fixtures. `apply_action` refuses unverified, rejected and already-applied IDs, and high-impact ones until an operator approves (approval is not a tool), and the backend re-checks the verdict (tested, T-5a/c). Pydantic-validated arguments, errors returned as data. 100% branch coverage. **Left for Oct 20:** an HTTP backend over the P3.6 API)* |
| P5.3 ✅ | Intent engine: prompt + few-shot → `Policy` JSON → validation and repair (≤ 2 retries) → **deterministic compiler** → twin verify → `POST /intents` | Oct 16 | `genai/intent/`, `genai/prompts/` | Compiler at 100% branch coverage; invalid LLM output never reaches it *(2026-10-08: `genai/intent/compiler.py` + `engine.py`, prompt `genai/prompts/intent_v2.md` (few-shot, examples distinct from the test set). Compiler (decision P5.3-A): priority → `set_qos_queue` (high 1, normal 0, low 2), throughput cap → `rate_limit_flow` per matching flow; KPI targets and constraints stay as standing objectives for the verifier; priority for all traffic everywhere, conflicting priorities and caps below 1 Mbit/s are refused. Engine: invalid LLM output stops before the compiler (tested); each action goes to `simulate_in_twin`; nothing is applied. Compiler and engine at 100% branch coverage. **Intent eval with intent_v2: gpt-oss:120b-cloud 30/30 (100%), local qwen2.5:3b 21/30 (70%)** (v1: 29/30, 20/30); one prompt revision after the first v2 run cost the local model a point (it invented priorities). **`POST /intents` moves to P3.6** (decision P5.3-B). **Review fixes (2026-10-08):** naming all three app classes everywhere is now refused like "all traffic everywhere" (it compiled to 3 actions); the operator's text replaces `intent_text` through schema validation, with the limit read from the schema; the eval calls the engine's own `parse_intent`; **`enabled: false`** in `config/intent.yaml` until M3 (RULEBOOK B-5). Eval after the fixes: cloud 30/30)* |
| P5.4 🟦 | Intent test set: **30 intents** with expected policies (Claude drafts, Abhishek checks) + eval script | Oct 15 ∥ | `genai/eval/intents.jsonl`, `genai/eval/run_intents.py` | Script reports accuracy *(2026-10-08: 30 intents drafted (4 zones + campus-wide, all 3 app classes and 4 KPIs, 3 priority levels, 7 with hard constraints of both scopes, 6 in looser wording). Correct = schema-valid and scope, objectives and constraints all equal as sets (decisions P5.4-A). Prompt `genai/prompts/intent_v1.md`. **gpt-oss:120b-cloud 29/30 (96.7%)**, the miss: "cap … at 2 Mbps" read as a constraint; **local qwen2.5:3b 20/30 (66.7%)**, misses: constraints and a dropped priority. Scoring at 100% branch coverage. **Awaiting Abhishek's check of the 30 expected policies**, then tick)* |
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
| P7.1a ✅ | Report skeleton + title page + Introduction + Related Work (from P0.4) | **DOC** | Oct 15 | Sections drafted in `docs/report/` *(2026-10-08: chapters 00–08 + references as Markdown, `docs/report/README.md` maps each to its task. Title page (course, institute, guide still to fill), Introduction (motivation, problem, approach, RQ + H1–H3, contributions, organisation), Related Work (5 papers + positioning table), 5 IEEE references. 4 claims marked `[check]` wait on the P0.4 full-text check; none may remain at submission)* |
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
| 7 | 2026-10-08 | v2.3 | **Emulated radio model + traffic sized to it.** (a) The scenario runner caps AP downlink with `tc` to emulate co-channel interference (`radio_model` in `config/campus_v1.yaml`: 4.6 Mbit/s per AP, neighbour weight 1 at ≤ 30 m → 0 at ≥ 60 m). (b) Video default 3 → 1 Mbit/s; web 500 KB / 2 s → 50 KB / 5 s; flash-crowd stream 0.4 Mbit/s, ap_failure calls 0.6 Mbit/s; flash-crowd walkers leave over 40 s (was 60) and their video starts at t=210 s (was 180), so all walkers have arrived. (c) Stations of a failed AP rejoin the nearest AP still up after 5 s | P1.6 calibration: each emulated AP carries ~4.6 Mbit/s whatever the bitrate, and same-channel APs do not interfere in hwsim/wmediumd. With 3 Mbit/s video the flash crowd (13 × 3 Mbit/s) could never recover, so time to recover would be undefined, and the co-channel scenario would show nothing | `docs/scenario.md` scenarios table updated (still awaiting P0.6 approval); radio behaviour is stated as an emulation model in the report; the twin (P3.3) uses the same model | — | Abhishek |
| 8 | 2026-10-08 | v2.3 | **`channel_util` = traffic ÷ the AP's current capacity** (nominal 4.6 Mbit/s, or its co-channel cap), replacing the P1.3 bits-per-bitrate estimate. The time-to-recover KPI's "< 80% utilisation" now means 80% of what the AP can actually carry | P1.6: reported bitrates have no effect on throughput in hwsim/wmediumd, and the old estimate ignored the interference caps, so a capped (congested) AP could look *less* busy. Raised by the P1.6/P2.1 code review | AP agent (`ap_logic.capacity_util`), dashboard airtime panel, problem_statement KPI note; data recorded before this change uses the old estimate | — | Abhishek |
| 9 | 2026-10-08 | v2.3 | P4.3 heuristics = **client steering + channel choice**; the shortest-delay reroute heuristic is dropped (phase cut list item 3) | campus_v1 is a tree: every pair of nodes has exactly one path, so a reroute heuristic could never propose anything | No effect on the evaluation; `reroute_flow` stays in the action allow-list for operator/LLM use | — | Abhishek |
| 10 | 2026-10-08 | v2.3 | (a) RULEBOOK C-3 reworded: each module validates its own `config/*.yaml` (there is no `common/config.py`). (b) Steering bounds become constants in `common/schemas.py` (ADR-004). (c) New `common/influx.py`: Flux query building and CSV parsing shared by twin, experiments and telemetry. (d) The P4.4 executor will own the verified/approved/applied records; the tool layer keeps its check as defence in depth | P2.3–P5.2 code review: the rule named a module that never existed; a safety bound was about to live in two places; the twin needs to read InfluxDB but may only import `common` | Adds 2 constants and 1 module to `common/`, before the P0.6 freeze | ADR-004 | Abhishek |
| 11 | 2026-10-08 | v2.3 | **The twin models QoS queues and rate limits at the AP bottleneck; the testbed must provision them (new task P4.4a).** | Found in P3.3: `set_qos_queue` installs `set_queue` on OVS ports that have no queues behind them, and the bottleneck is the AP radio, not a switch port; there is no rate-limit (meter) action in the controller. Today a priority or rate-limit action changes nothing in the testbed | Intent actions (priority, caps) can't be validated live until P4.4a; P3.5 validates other actions first | — | Abhishek |
| 12 | 2026-10-08 | v2.3 | P3.3 simulator models the **AP downlink only, not wired-link queueing** (the task says "link queueing delay + Wi-Fi airtime") | Wired links are 100 Mbit/s against 4.6 Mbit/s at each AP, so their load stays under 5% and their queueing delay is negligible; the twin state has no links yet | None on predictions; stated as a modelling simplification in the report | — | Abhishek |
