# Phase Plan: Execution Guide

**Project:** GenAI-Driven Digital Twin for Intelligent SDN-Based Wireless Network Optimization
**Companion to:** [`PROJECT_PLAN.md`](PROJECT_PLAN.md), which covers the *what* and *why*. This file covers *how and in what order*.
**Baseline version:** v1.0 · 2026-10-06 · 16 weeks · 4 people

> **This file is the single source of truth for execution.** Work happens in the order written here. Anything not in this file is out of scope until it passes the [change control process](#2-change-control).

---

## Contents

1. [Rules for staying on plan](#1-rules-for-staying-on-plan)
2. [Change control](#2-change-control)
3. [Scope lock](#3-scope-lock)
4. [How to read a phase](#4-how-to-read-a-phase)
5. [Status board](#5-status-board)
6. [Phase 0: Research and setup (W1–W2)](#phase-0-research-and-setup-weeks-12)
7. [Phase 1: Wireless SDN testbed (W3–W4)](#phase-1-wireless-sdn-testbed-weeks-34)
8. [Phase 2: Telemetry pipeline and dataset (W5–W6)](#phase-2-telemetry-pipeline-and-dataset-weeks-56)
9. [Phase 3: Digital twin core (W7–W9)](#phase-3-digital-twin-core-weeks-79)
10. [Phase 4: Intelligence and optimization (W9–W11)](#phase-4-intelligence-and-optimization-weeks-911)
11. [Phase 5: GenAI and LLM layer (W11–W13)](#phase-5-genai-and-llm-layer-weeks-1113)
12. [Phase 6: Dashboard, integration and evaluation (W14–W15)](#phase-6-dashboard-integration-and-evaluation-weeks-1415)
13. [Phase 7: Report and presentation (W16)](#phase-7-report-and-presentation-week-16)
14. [Weekly checkpoint template](#weekly-checkpoint-template)
15. [Deviation log](#deviation-log)

---

## 1. Rules for staying on plan

1. **One phase at a time.** A phase starts only when the previous phase's **exit gate** has passed, or when its entry criteria explicitly allow overlap (listed per phase).
2. **Tasks in order.** Inside a phase, do tasks in ID order unless a task is marked `∥` (can run in parallel).
3. **Done means the Definition of Done.** A task isn't done until every bullet in its *Done when* list is true and the change is merged to `main`.
4. **No unplanned work.** If an idea isn't a task in this file, write it in the [Parking lot](#parking-lot) and keep going. Don't build it.
5. **Behind schedule? Cut, don't extend.** Each phase has a **cut list** in priority order. Use it before you consider moving a deadline.
6. **Contracts are frozen after Phase 0.** Schemas in `common/schemas.py` change only through an ADR (see [§2](#2-change-control)).
7. **Every phase ends with a demo.** If you can't demo it, it isn't done.
8. **Integrate continuously.** Each phase's work runs inside `docker compose up` (services) plus the VM (network) by the end of that phase, not in week 15.
9. **Check the status board weekly.** Update [§5](#5-status-board) and the [weekly checkpoint](#weekly-checkpoint-template) every Friday.

---

## 2. Change control

Use this process for any change to scope, schedule, contracts or technology choices.

1. **Write it down.** Add a row to the [Deviation log](#deviation-log) with: what changes, why, and the impact on schedule and other phases.
2. **Write an ADR** if it changes a technology, schema or architecture decision: `docs/adr/NNN-title.md` (context, decision, consequences).
3. **Agree as a team** at the weekly sync. It needs at least 3 of the 4 members.
4. **Update this file.** Edit the affected tasks, bump the version at the top (v1.0 → v1.1), and note it in the log.
5. **Only then** start the work.

**Doesn't need change control:** bug fixes, refactors inside one module that keep its interface, tests, docs.

---

## 3. Scope lock

### In scope (v1.0)

- Emulated network only: Mininet-WiFi + Ryu (or OS-Ken) + Open vSwitch.
- One campus scenario: 4–6 APs, 2–3 switches, 20–40 mobile stations.
- 5 scenario types: normal, flash crowd, AP failure, co-channel interference, mixed video + bulk.
- Twin: analytical simulator (**required**), GNN surrogate (**stretch**), cloned emulation (**stretch**).
- ML: forecaster, anomaly detector, heuristic optimizer (**required**), PPO agent (**should**).
- LLM: intent → policy, RAG copilot, root-cause explanation (**required**); scenario generator, TimeGAN (**should**); config synthesis (**nice to have**).
- Dashboard, 4-variant evaluation, IEEE report, demo video.

### Out of scope (v1.0). Parking lot only.

- Real hardware (Raspberry Pi / OpenWrt APs) *(unless decided in Phase 0, see open question Q2)*
- ns-3, OMNeT++, P4/BMv2, ONOS/OpenDaylight
- Kubernetes or any cloud deployment beyond one VM
- Multi-site / multi-controller networks, 5G/LTE
- LLM fine-tuning
- User authentication beyond a single operator role
- Mobile app

### Parking lot

Ideas that came up and are **not** being built. Review them at the end of Phase 6.

| Date | Idea | Raised by | Notes |
|---|---|---|---|
| | | | |

---

## 4. How to read a phase

Each phase has the same structure:

| Section | Meaning |
|---|---|
| **Objective** | One sentence. If a task doesn't serve it, it doesn't belong in the phase. |
| **Entry criteria** | Must be true before starting. |
| **Tasks** | Numbered `Px.y`. Owner role, files produced, and a *Done when* list. `∥` = can run in parallel with the previous task. |
| **Exit gate** | Checklist. All items must be ticked to close the phase. |
| **Demo script** | What is shown at the end-of-phase demo. |
| **Cut list** | What to drop, in order, if the phase is behind. |
| **Do not** | Common diversions to avoid in this phase. |

**Roles:** NET = Network engineer · TWIN = Twin and data engineer · ML = ML engineer · GENAI = GenAI and full-stack. Assign names in [§5](#5-status-board).

---

## 5. Status board

**Team**

| Role | Name | Secondary on |
|---|---|---|
| NET | | telemetry collector |
| TWIN | | GNN surrogate |
| ML | | evaluation analysis |
| GENAI | | verifier policy checks |

**Phases**

| Phase | Weeks | Status | Exit gate passed | Notes |
|---|---|---|---|---|
| 0 Research & setup | 1–2 | ⬜ Not started | | |
| 1 Wireless SDN testbed | 3–4 | ⬜ Not started | | |
| 2 Telemetry & dataset | 5–6 | ⬜ Not started | | |
| 3 Digital twin core ⚠ | 7–9 | ⬜ Not started | | critical path |
| 4 Intelligence & optimization | 9–11 | ⬜ Not started | | |
| 5 GenAI & LLM layer | 11–13 | ⬜ Not started | | |
| 6 Dashboard & evaluation | 14–15 | ⬜ Not started | | |
| 7 Report & presentation | 16 | ⬜ Not started | | |

Status values: ⬜ Not started · 🟦 In progress · 🟨 At risk · 🟥 Blocked · ✅ Done

**Milestones**

| ID | Week | Milestone | Status |
|---|---|---|---|
| M0 | 2 | Toolchain works, contracts agreed | ⬜ |
| M1 | 4 | Reproducible scenario + controllable network | ⬜ |
| M2 | 6 | Labelled dataset available | ⬜ |
| M3 | 9 | Twin validated (MAPE target met) | ⬜ |
| M4 | 11 | Closed loop beats baseline | ⬜ |
| M5 | 13 | LLM intents + copilot working through the twin | ⬜ |
| M6 | 15 | Results frozen, one-command demo | ⬜ |
| M7 | 16 | Report submitted, presentation | ⬜ |

---

## Phase 0: Research and setup (weeks 1–2)

**Objective:** a working toolchain on every machine, a shared understanding of the problem, and frozen data contracts.

**Entry criteria:** none.

### Tasks

#### P0.1: Answer the open questions · all · Week 1, day 1–2
Decide on the [open questions in PROJECT_PLAN §17](PROJECT_PLAN.md#17-open-questions): team size, timeline, real hardware, LLM provider, report format, controller.
- **Produces:** `docs/decisions.md`
- **Done when:**
  - [ ] Every question has a written answer.
  - [ ] If team size or timeline differs from 4 people / 16 weeks, this file is re-planned **before** P0.2 (via [change control](#2-change-control)).

#### P0.2: Build the shared Ubuntu VM · NET · Week 1
- Ubuntu 22.04, 4 vCPU, 8 GB RAM, 40 GB disk (UTM or Multipass on macOS).
- Mininet-WiFi from source with wmediumd: `git clone https://github.com/intrig-unicamp/mininet-wifi && cd mininet-wifi && sudo util/install.sh -Wlnfv`.
- Open vSwitch, iperf3, D-ITG.
- Ryu in a pinned environment (Python 3.9 + pinned `eventlet`) **or** OS-Ken. Record the choice in ADR-002.
- **Produces:** VM image shared with the team, `docs/setup.md` (step-by-step), `docs/adr/002-controller.md`
- **Done when:**
  - [ ] A 2-AP, 4-station topology with Ryu `simple_switch_13` passes `pingall`.
  - [ ] A second team member reproduces it from `docs/setup.md` alone.

#### P0.3: Repo skeleton · GENAI · Week 1 · ∥
- Folders from [PROJECT_PLAN §16](PROJECT_PLAN.md#repository-layout), `README.md`, `.gitignore` (Python, Node, `data/`, `.env`, `models/`), `.env.example`.
- `pyproject.toml` with ruff, mypy, pytest.
- `docker-compose.yml` with `mosquitto`, `influxdb`, `grafana`.
- GitHub Actions: lint + test on PRs.
- **Done when:**
  - [ ] `docker compose up` starts all three services and they are healthy.
  - [ ] CI runs green on an empty test.
  - [ ] `main` is branch-protected; PRs need 1 review.

#### P0.4: Literature review · all (split) · Weeks 1–2 · ∥
Each person reads 2–3 papers from [PROJECT_PLAN §19](PROJECT_PLAN.md#19-references-and-reading-list) in their area.
- **Produces:** `docs/literature/<topic>.md`, each with a summary, what we reuse, and the citation.
- **Done when:**
  - [ ] At least 6 papers summarized.
  - [ ] A 1–2 page combined review is drafted in `docs/literature/README.md`.

#### P0.5: Problem statement, KPIs, scenario definition · all · Week 2
- **Produces:** `docs/problem_statement.md`, `docs/scenario.md` (campus map: zones, AP positions, switch links, station counts per zone).
- **Done when:**
  - [ ] KPIs are listed with target values (from [PROJECT_PLAN §13](PROJECT_PLAN.md#13-evaluation-plan)).
  - [ ] Campus layout is fixed: number of APs, switches, stations and zones.

#### P0.6: Freeze data contracts · TWIN + GENAI · Week 2
Implement [PROJECT_PLAN §7](PROJECT_PLAN.md#7-data-models-and-interfaces) as Pydantic models.
- **Produces:** `common/schemas.py` (telemetry messages, `TwinState` pieces, `Action`, `Policy`, `Verdict`, `Scenario`), `tests/unit/test_schemas.py`
- **Done when:**
  - [ ] Every schema has a valid and an invalid example in tests.
  - [ ] Action bounds from §7.3 are enforced by validators.
  - [ ] All 4 members have reviewed the PR. **Contracts are now frozen.**

#### P0.7: LLM provider setup · GENAI · Week 2 · ∥
- **Produces:** `docs/adr/001-llm-provider.md`, API key in `.env`, Ollama installed with one small model pulled.
- **Done when:**
  - [ ] A one-line script gets a response from both the hosted and the local model.

### Exit gate (M0)

- [ ] P0.1–P0.7 done
- [ ] `pingall` works in Mininet-WiFi under Ryu (or OS-Ken) on the shared VM
- [ ] `docker compose up` is healthy; CI is green
- [ ] Schemas merged and frozen
- [ ] Literature review drafted
- [ ] Status board names filled in

**Demo script:** start the VM topology → `pingall` → show Ryu logs → `docker compose up` → show Grafana login.

**Cut list:** (1) trim the literature review to 4 papers; (2) defer Ollama to Phase 5.
**Do not:** start writing topology or twin code; try other controllers "just to compare"; design the dashboard.

---

## Phase 1: Wireless SDN testbed (weeks 3–4)

**Objective:** a reproducible campus network we can run from a scenario file, observe through REST, and control through an AP agent.

**Entry criteria:** M0 passed.

### Tasks

#### P1.1: Campus topology · NET · Week 3
- **Produces:** `testbed/topologies/campus_v1.py` built from `docs/scenario.md`, with wmediumd interference enabled.
- **Done when:**
  - [ ] All APs, switches and stations start; `pingall` passes.
  - [ ] Stations associate to the expected APs at start.

#### P1.2: Ryu controller app · NET · Week 3 · ∥
- **Produces:** `controller/apps/twin_controller.py`, which covers L2 learning + L3 forwarding (shortest path over a NetworkX graph), port/flow stats polling every 1 s, and REST endpoints: `GET /stats/ports`, `GET /stats/flows`, `GET /topology`, `POST /flows` (install), `DELETE /flows/{id}`, `POST /qos/queue`.
- **Done when:**
  - [ ] All endpoints return data that validates against `common/schemas.py`.
  - [ ] A flow installed via `POST /flows` changes the path of traffic (checked with `ovs-ofctl dump-flows`).

#### P1.3: AP agent · NET · Week 3–4
A small HTTP server that runs **inside** the topology process.
- **Produces:** `testbed/ap_agent.py` with `GET /aps`, `GET /aps/{id}/stats`, `GET /stations`, `POST /aps/{id}/channel`, `POST /aps/{id}/txpower`, `POST /stations/{id}/associate`.
- **Done when:**
  - [ ] Each POST changes the AP or station state, and the change shows up in the next GET.
  - [ ] Out-of-bounds values (§7.3) return HTTP 422.

#### P1.4: Mobility models · NET · Week 4
- **Produces:** `testbed/mobility/` with random waypoint and scheduled crowd movement (group moves zone A → B over a time window).
- **Done when:**
  - [ ] A crowd of 20 stations moves from corridor to lecture hall in a test run, and associations change.

#### P1.5: Traffic profiles and KPI probes · NET + ML · Week 4 · ∥
- **Produces:** `testbed/traffic/profiles.yaml` (video, web, bulk, voip), `testbed/traffic/generator.py`, `testbed/traffic/kpi_probe.py` (per-flow throughput, latency, jitter, loss).
- **Done when:**
  - [ ] Each profile runs, and the probe outputs KPI records that match the `kpi` schema.

#### P1.6: Scenario runner · NET · Week 4
- **Produces:** `testbed/run_scenario.py <scenario.yaml>`, plus `experiments/scenarios/lecture_flash_crowd.yaml`.
- **Done when:**
  - [ ] It runs a 10-minute scenario end to end without manual steps.
  - [ ] **Reproducibility:** the same seed, run 3 times, gives mean throughput within ±5%.

### Exit gate (M1)

- [ ] P1.1–P1.6 done
- [ ] Controller REST and AP agent are live and schema-valid
- [ ] `lecture_flash_crowd` runs reproducibly (±5% over 3 runs)
- [ ] `docs/setup.md` updated with how to run a scenario

**Demo script:** run `lecture_flash_crowd` → `curl` the controller stats → change AP-3's channel through the AP agent → show the change in `GET /aps`.

**Cut list:** (1) drop random waypoint and keep only the scheduled crowd; (2) drop the voip profile; (3) L2-only forwarding with static paths.
**Do not:** build the telemetry pipeline; add more topologies; tune Wi-Fi realism beyond wmediumd defaults.

---

## Phase 2: Telemetry pipeline and dataset (weeks 5–6)

**Objective:** all telemetry flowing into InfluxDB on schema, plus a labelled dataset for ML and twin validation.

**Entry criteria:** M1 passed.

### Tasks

#### P2.1: Collector · TWIN · Week 5
- **Produces:** `telemetry/collector/` that polls the controller REST and the AP agent every 1–2 s, validates against the schemas, and publishes to the MQTT topics in §7.1. Every message carries `ts`, `scenario_id` and `run_id`.
- **Done when:**
  - [ ] All 5 telemetry topics publish during a scenario.
  - [ ] Invalid data is logged and dropped, not published.

#### P2.2: MQTT → InfluxDB writer · TWIN · Week 5
- **Produces:** `telemetry/writer/`, added to `docker-compose.yml`.
- **Done when:**
  - [ ] All measurements from §7.1 appear in InfluxDB with the correct tags.
  - [ ] **Lag:** under 2 s; **gaps:** none over 5 s in a 1-hour run.

#### P2.3: Grafana dashboards · TWIN · Week 5 · ∥
- **Produces:** `telemetry/grafana/raw_kpis.json` (provisioned automatically).
- **Done when:**
  - [ ] Per-AP load, per-link utilization and per-flow KPIs are visible live.

#### P2.4: Scenario library · NET · Week 5
- **Produces:** 5 YAML files in `experiments/scenarios/`: `normal`, `lecture_flash_crowd`, `ap_failure`, `cochannel_interference`, `mixed_video_bulk`, each with `labels:`.
- **Done when:**
  - [ ] Each runs end to end, and its labelled event is visible in Grafana.

#### P2.5: Batch runner · NET + TWIN · Week 6
- **Produces:** `experiments/run_batch.py --scenarios ... --seeds N` that runs unattended and resets the network between runs.
- **Done when:**
  - [ ] It completes 5 scenarios × 3 seeds overnight with no manual steps.

#### P2.6: Dataset export · TWIN + ML · Week 6
- **Produces:** `experiments/export_dataset.py` → `data/<version>/` Parquet (gitignored), and `docs/dataset.md` (fields, labels, splits, size).
- **Done when:**
  - [ ] At least **4 hours** of labelled telemetry across all 5 scenario types.
  - [ ] Train/val/test split is **by run**, not by row, and documented.

#### P2.7: EDA · ML · Week 6 · ∥
- **Produces:** `experiments/notebooks/01_eda.ipynb`
- **Done when:**
  - [ ] Shows distributions per scenario and confirms that the labelled events are visible in the data.

### Exit gate (M2)

- [ ] P2.1–P2.7 done
- [ ] Lag under 2 s, no gaps over 5 s in a 1-hour run
- [ ] At least 4 h labelled dataset, versioned and documented
- [ ] Collector and writer run inside Docker Compose

**Demo script:** run `lecture_flash_crowd` → Grafana shows the AP-3 load spike live → open `docs/dataset.md` and the EDA notebook.

**Cut list:** (1) 3 h of data instead of 4; (2) drop `mixed_video_bulk`; (3) Grafana only for APs, not links.
**Do not:** start the twin simulator; train models on partial data; switch MQTT to Kafka.

---

## Phase 3: Digital twin core (weeks 7–9)

> ⚠ **Critical path.** Phases 4 and 5 depend on this. If it is behind by the end of week 8, apply the cut list immediately.

**Objective:** a twin that mirrors live state and predicts the KPI effect of an action within the error target, fast enough for the loop.

**Entry criteria:** M2 passed.

### Tasks

#### P3.1: Twin state and sync · TWIN · Week 7
- **Produces:** `twin/state/builder.py` (state from InfluxDB at time *t*), `twin/state/sync.py` (incremental update from MQTT).
- **Done when:**
  - [ ] Twin state matches the controller/AP agent view (same APs, links, flows, associations).
  - [ ] Sync lag is under 3 s.
  - [ ] Replay test: recorded telemetry → expected state (`tests/replay/`).

#### P3.2: Apply actions in the twin · TWIN · Week 7
- **Produces:** `twin/sim/apply.py`, which applies each allow-listed `Action` type to a **copy** of the state.
- **Done when:**
  - [ ] Each action type has unit tests; the original state is never mutated.

#### P3.3: Analytical simulator · TWIN · Week 7–8
- **Produces:** `twin/sim/analytical.py`. It predicts per-flow throughput, latency and loss, plus per-AP utilization and Jain fairness. The model uses queueing delay per link (M/M/1-style) and a Wi-Fi airtime model (shared airtime per AP, co-channel overlap penalty).
- **Done when:**
  - [ ] One simulation takes under 1 s.
  - [ ] Its outputs validate against the `Verdict.predicted` schema.

#### P3.4: Validation harness · TWIN · Week 8
- **Produces:** `twin/validation/run_validation.py`, which applies a set of real actions on the emulated network, compares the twin's prediction with the measured outcome, and writes `twin_predictions` to InfluxDB. Also `experiments/notebooks/02_twin_validation.ipynb`.
- **Done when:**
  - [ ] It reports MAPE for throughput and delay per scenario.

#### P3.5: Verifier · TWIN + GENAI · Week 8
- **Produces:** `twin/verify/verifier.py`, which applies the acceptance rule from §7.5, checks policy constraints and assigns the impact class from §8.
- **Done when:**
  - [ ] Unit tests cover accept, reject (regression), reject (policy violation), and needs-approval (high impact).

#### P3.6: `/twin/simulate` API · GENAI · Week 8 · ∥
- **Produces:** `api/` FastAPI app with `GET /topology`, `GET /metrics`, `POST /twin/simulate`, added to Docker Compose.
- **Done when:**
  - [ ] It returns a schema-valid `Verdict` for every action type.

#### P3.7: GNN surrogate (stretch) · ML + TWIN · Week 8–9
- **Produces:** `twin/sim/gnn/`
- **Done when:**
  - [ ] Its MAPE beats or matches the analytical model on the test runs. **If not, keep analytical as the default and record the result.**

#### P3.8: Cloned-emulation mode (stretch) · NET · Week 9 · ∥
- **Produces:** `twin/sim/emulation.py`
- **Done when:**
  - [ ] It replays the current state into a second Mininet-WiFi instance and returns KPIs.

### Exit gate (M3)

- [ ] P3.1–P3.6 done (P3.7, P3.8 optional)
- [ ] Sync lag under 3 s
- [ ] **Throughput MAPE under 15%** (target under 10%) on held-out runs
- [ ] Fast-mode simulation under 1 s
- [ ] Twin services run in Docker Compose

**Demo script:** live flash crowd → call `/twin/simulate` with "AP-3 → channel 11" → show the predicted KPIs → apply it by hand through the AP agent → show predicted vs actual.

**Cut list:** (1) drop P3.8; (2) drop P3.7; (3) relax MAPE to under 20% and document it as a limitation; (4) simplify the airtime model to load-only.
**Do not:** start the RL agent; add new action types; build the dashboard.

---

## Phase 4: Intelligence and optimization (weeks 9–11)

**Objective:** a closed loop that runs unattended, never applies an unverified action, rolls back bad ones, and beats the baseline on at least one KPI.

**Entry criteria:** P3.1–P3.5 done. Week 9 overlap is allowed for P4.1–P4.2, which only need the Phase 2 dataset.

### Tasks

#### P4.1: Traffic forecaster · ML · Week 9
- **Produces:** `ml/forecast/`: moving-average baseline, then LSTM. Per-AP load forecasts for t+1, t+3 and t+5 min.
- **Done when:**
  - [ ] The LSTM beats the baseline on RMSE on the test split.
  - [ ] An inference function exists, and the model is saved to `models/`.

#### P4.2: Anomaly detector · ML · Week 9 · ∥
- **Produces:** `ml/anomaly/` with Isolation Forest, publishing to `twin/events/alert`.
- **Done when:**
  - [ ] Precision, recall and F1 are reported on labelled events.
  - [ ] Alerts appear during an `ap_failure` run.

#### P4.3: Action executor · NET + TWIN · Week 10
- **Produces:** `controller/executor/`. It applies only actions that have an accepted `Verdict`, stores the previous config, watches KPIs for 30 s, rolls back on a regression over 10%, enforces rate limits (§8), and writes to the `actions` audit log.
- **Done when:**
  - [ ] Tests show that an unverified action is refused.
  - [ ] A deliberately bad action is rolled back automatically.

#### P4.4: Heuristic optimizer · ML · Week 10 · ∥
- **Produces:** `ml/optimizer/heuristics.py`: least-loaded AP steering, shortest-delay reroute, non-overlapping channel selection. Takes state, forecasts and alerts; returns `Action[]`.
- **Done when:**
  - [ ] It produces sensible candidates for each of the 5 scenarios (unit tests with fixture states).

#### P4.5: Loop orchestrator · TWIN · Week 10
- **Produces:** `twin/loop.py` (period from `config/loop.yaml`, default 5 s). It runs observe → mirror → predict → decide → verify → act, and has a `--mode` flag for evaluation variants V1–V4.
- **Done when:**
  - [ ] It runs through a full flash-crowd scenario unattended with no crashes.

#### P4.6: RL environment and PPO agent · ML · Week 10–11
- **Produces:** `ml/rl/env.py` (spec in PROJECT_PLAN §6), `ml/rl/train.py`, `models/ppo_*.zip`
- **Done when:**
  - [ ] The env passes `gymnasium.utils.env_checker`.
  - [ ] The agent is evaluated against the heuristics in the twin. **If it is worse, keep the heuristics as the default and report RL as an ablation.**

#### P4.7: Baseline comparison (first look) · ML + TWIN · Week 11
- **Produces:** `experiments/notebooks/03_loop_vs_baseline.ipynb`
- **Done when:**
  - [ ] Over 3 seeds of `lecture_flash_crowd`, the closed loop beats V1 on at least one KPI (target: time to recover).

### Exit gate (M4)

- [ ] P4.1–P4.5, P4.7 done (P4.6 should)
- [ ] Loop runs unattended through a congestion scenario
- [ ] Beats the baseline on at least one KPI
- [ ] Rollback demonstrated
- [ ] Audit log shows that every applied action has an accepted verdict

**Demo script:** flash crowd with the loop **off** vs **on**, KPIs side by side → inject a bad action → show the rollback.

**Cut list:** (1) drop PPO and present it as future work; (2) forecaster = moving average only; (3) anomaly detector = static thresholds.
**Do not:** start the LLM work early; tune RL hyperparameters past week 11; add new scenarios.

---

## Phase 5: GenAI and LLM layer (weeks 11–13)

**Objective:** natural-language control and explanation on top of the verified loop, where every LLM-originated action goes through the twin.

**Entry criteria:** P4.3 and P4.5 done (the executor and loop exist). GENAI may start P5.1, P5.2 and P5.5 from **week 5** against mock data. This is the only allowed early start.

### Tasks

#### P5.1: LLM client · GENAI · (from week 5)
- **Produces:** `genai/llm/client.py`, a provider-agnostic wrapper (hosted + Ollama, chosen by config) that logs model, tokens, latency and tool calls.
- **Done when:**
  - [ ] The same call works on both providers.
  - [ ] Logs are written for every call.

#### P5.2: Tool layer · GENAI · (from week 5, finished week 11)
- **Produces:** `genai/tools/` with the tools from PROJECT_PLAN §5.6, exposed as an MCP server and/or FastAPI tools. `apply_action` only accepts IDs of verified actions.
- **Done when:**
  - [ ] Every tool returns schema-valid data from the **live** system (mocks removed).

#### P5.3: Intent engine · GENAI · Week 11–12
- **Produces:** `genai/intent/` with a prompt + few-shot examples → Policy JSON → validation and repair loop (at most 2 retries) → `genai/intent/compiler.py` (Policy → `Action[]`, deterministic) → twin verify → `POST /intents`.
- **Done when:**
  - [ ] The compiler has unit tests.
  - [ ] An invalid LLM output never reaches the compiler.

#### P5.4: Intent test set · GENAI + all · Week 11 · ∥
- **Produces:** `genai/eval/intents.jsonl`: 50 intents with expected policies (each member writes 12–13), plus `genai/eval/run_intents.py`.
- **Done when:**
  - [ ] The script reports accuracy for both providers.

#### P5.5: RAG index · GENAI · (from week 5)
- **Produces:** `genai/rag/`: chunk by heading, embed, store in Chroma. Corpus: OpenFlow 1.3 excerpts, Ryu/Mininet-WiFi docs, `docs/runbooks/*.md`, ADRs.
- **Done when:**
  - [ ] `search_docs` returns relevant chunks for 10 test queries.

#### P5.6: Copilot agent · GENAI · Week 12
- **Produces:** `genai/agent/` (tool-using agent) and `POST /chat` (SSE streaming).
- **Done when:**
  - [ ] It answers 10 diagnostic questions using live tools, with evidence cited.
  - [ ] Any action it proposes goes through `simulate_in_twin`.

#### P5.7: Root-cause explainer · GENAI + ML · Week 12 · ∥
- **Produces:** `genai/rca/`: alert + metric window + recent actions → JSON report (§5.3). Triggered on each alert and shown in the action log.
- **Done when:**
  - [ ] It produces a correct diagnosis for `ap_failure` and `cochannel_interference` runs.

#### P5.8: What-if scenario generator (should) · GENAI + NET · Week 13
- **Produces:** `genai/scenarios/`, natural language → scenario YAML validated against the `Scenario` schema, plus `POST /scenarios/generate`.
- **Done when:**
  - [ ] 5 generated scenarios validate and run in the testbed.

#### P5.9: Synthetic traffic (should) · ML · Week 12–13 · ∥
- **Produces:** `ml/synthetic/` (TimeGAN or VAE) with quality checks: KS test, autocorrelation, train-on-synthetic / test-on-real.
- **Done when:**
  - [ ] The quality report is in `experiments/notebooks/04_synthetic.ipynb`.

### Exit gate (M5)

- [ ] P5.1–P5.7 done (P5.8, P5.9 should)
- [ ] At least **20 intents** translated correctly (full 50-intent score is reported in Phase 6)
- [ ] Copilot answers diagnostic questions using live data
- [ ] Audit log shows **100%** of LLM-originated actions have a twin verdict
- [ ] Works with the local model (degraded quality is acceptable)

**Demo script:** type *"Give video calls in Lab 2 priority and keep latency under 50 ms"* → show the policy → twin verdict → approval → effect on KPIs → ask *"Why was AP-3 slow at 10:00?"* → show the RCA report.

**Cut list:** (1) drop P5.9; (2) drop P5.8; (3) copilot without RAG (tools only); (4) intent engine limited to QoS and reroute intents.
**Do not:** fine-tune models; build config synthesis (use case 6) unless every must and should item is done; let the LLM call the controller or AP agent directly.

---

## Phase 6: Dashboard, integration and evaluation (weeks 14–15)

**Objective:** the whole system starts with one command, and the evaluation results are frozen.

**Entry criteria:** M5 passed.

### Tasks

#### P6.1: Dashboard · GENAI · Week 14
- **Produces:** `dashboard/` with a live topology map (AP load heat colours), KPI charts, twin-vs-live panel, action log with approve/deny, and a chat panel. Fed by `WS /ws/live`.
- **Done when:**
  - [ ] All 5 panels work during a live scenario.
  - [ ] High-impact actions can be approved from the UI.

#### P6.2: One-command startup · all · Week 14 · ∥
- **Produces:** `make demo` (or a script) that starts the VM topology and `docker compose up`, then loads the default scenario. Plus `docs/runbooks/demo.md`.
- **Done when:**
  - [ ] A team member who didn't write it starts the full demo from the runbook.

#### P6.3: Freeze for evaluation · all · Week 14 end
- **Done when:**
  - [ ] Git tag `eval-v1` exists.
  - [ ] Configs are frozen.
  - [ ] **No feature work after this point.** Only fixes needed to run the evaluation.

#### P6.4: Experiment campaign · ML + TWIN · Week 14–15
- **Produces:** `experiments/results/`: V1–V4 × 5 scenarios × at least 5 seeds (PROJECT_PLAN §13).
- **Done when:**
  - [ ] All 100+ runs are complete.
  - [ ] Failed runs are re-run and logged.

#### P6.5: Twin-blocking and LLM evaluation · TWIN + GENAI · Week 15 · ∥
- **Produces:** twin-blocking analysis (§13 step 4); 50-intent scores for the hosted and local model; RAG answer correctness; token cost per action.
- **Done when:**
  - [ ] The numbers are in `experiments/results/`.

#### P6.6: Analysis and figures · ML · Week 15
- **Produces:** `experiments/analysis/*.py` that generate every table and chart (mean ± 95% CI, Wilcoxon V1 vs V4).
- **Done when:**
  - [ ] One command regenerates all figures from raw results. **Nothing is made by hand.**

### Exit gate (M6)

- [ ] P6.1–P6.6 done
- [ ] End-to-end demo from one command
- [ ] All results tables and figures generated by script
- [ ] Headline claim tested; the result is written down whether it holds or not

**Demo script:** the full system live, using the Phase 5 demo script, run from the dashboard.

**Cut list:** (1) Streamlit instead of React; (2) 3 seeds instead of 5 (state it in the report); (3) drop the `mixed_video_bulk` scenario from the evaluation.
**Do not:** add features after `eval-v1`; re-tune models to improve results; change the scenarios mid-campaign.

---

## Phase 7: Report and presentation (week 16)

**Objective:** submit the report and give the presentation.

**Entry criteria:** M6 passed.

### Tasks

| ID | Task | Owner | Produces | Done when |
|---|---|---|---|---|
| P7.1 | Final report (IEEE): intro, related work, architecture, method, results, limitations, future work | all (by section) | `docs/report/` | Full draft by day 3; reviewed by all; submitted |
| P7.2 | Figures and diagrams | GENAI + TWIN | `docs/figures/` | All figures come from P6.6 scripts or source diagrams |
| P7.3 | Demo video (backup) | GENAI | `docs/demo.mp4` or link | 5–8 min, covers the Phase 5 demo script |
| P7.4 | Slides | all | `docs/slides/` | Rehearsed twice, on time |
| P7.5 | Repo clean-up | all | README, setup docs | A fresh clone + `docs/setup.md` gets someone to the demo |
| P7.6 | *(optional)* workshop paper | all | `docs/paper/` | Only if P7.1–P7.5 are done |

### Exit gate (M7)

- [ ] Report submitted
- [ ] Presentation delivered
- [ ] Demo video available
- [ ] Repo README lets someone else run the system

**Do not:** change code beyond critical demo fixes; run new experiments.

---

## Weekly checkpoint template

Copy this into `docs/progress.md` every Friday.

```markdown
### Week N: YYYY-MM-DD

**Phase:** Px · **Status:** 🟦 / 🟨 / 🟥 / ✅

| Task | Owner | Status | Note |
|---|---|---|---|
| Px.y | | | |

**Done this week:**
-

**Planned next week (task IDs only):**
-

**Blockers / risks:**
-

**Cut-list items used:**
-

**Change requests raised (see deviation log):**
-

**Demo shown:** yes / no
```

---

## Deviation log

Every change to this plan goes here **before** the work starts.

| # | Date | Version | Change | Reason | Impact (schedule / other phases) | ADR | Agreed by |
|---|---|---|---|---|---|---|---|
| 0 | 2026-10-06 | v1.0 | Baseline plan created | — | — | — | — |
