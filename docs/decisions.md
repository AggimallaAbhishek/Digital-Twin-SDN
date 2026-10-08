# P0.1 Decisions

Answers to the open questions in [PROJECT_PLAN §17](PROJECT_PLAN.md#17-open-questions). Task P0.1 in [PHASE_PLAN](PHASE_PLAN.md) is done when every question below is answered.

| # | Question | Answer | Status | Date | Decided by |
|---|---|---|---|---|---|
| Q1 | Team size and timeline | **5 people** (see Team below). **Deadline Oct 31, 2026** (25 working days from Oct 6). Internal submission target **Oct 30**. The plan was rewritten as PHASE_PLAN **v2.0** (parallel tracks, reduced scope). | ✅ Decided | 2026-10-06 | Abhishek |
| Q2 | Real hardware or emulation only? | **Fully virtual, software only.** Wi-Fi APs, stations and radio are emulated with Mininet-WiFi (`mac80211_hwsim` + wmediumd); switches are Open vSwitch; everything runs in the Ubuntu VM and Docker. No physical APs, Raspberry Pis or real Wi-Fi interfaces. | ✅ Decided | 2026-10-06 | Abhishek |
| Q3 | LLM provider, and is there an API budget? | **Ollama, no paid API budget.** Revised 2026-10-07: main model **`gpt-oss:120b-cloud`** (Ollama cloud), with automatic fallback to local **`qwen2.5:3b`** so the demo works offline ([ADR-001](adr/001-llm-provider.md)). Originally "local only". | ✅ Decided (revised) | 2026-10-07 | Abhishek |
| Q4 | Deliverables and report format | **A project report + a live demonstration.** No slides required. A backup screen recording is kept in case the live demo fails. Report template: use the department's template if one exists, otherwise our own structure (P7.1a). | ✅ Decided (template 🟨 to confirm) | 2026-10-06 | Abhishek |
| Q5 | Controller: Ryu, or OS-Ken / ONOS? | **Ryu 4.34** in a pinned venv ([ADR-002](adr/002-controller.md)). | ✅ Decided | 2026-10-07 | Abhishek |
| — | Testbed OS: Ubuntu 22.04 → 20.04 | **Ubuntu 20.04** ([ADR-003](adr/003-vm-ubuntu-20-04.md)). | ✅ Decided | 2026-10-07 | Abhishek |
| Q6 | Who does the work? | **Abhishek alone, with Claude Code.** The other four team members are named on the report but take no part in development, reviews or approvals. All decisions and approvals are Abhishek's. | ✅ Decided | 2026-10-07 | Abhishek |

## Team

| Name | Roll no. |
|---|---|
| Aggimalla Abhishek | 23BDS004 |
| N. Likhith Naik | 23BDS037 |
| Sundaram | 23BDS060 |
| Sambhav Mishra | 23BDS050 |
| Bikram Hawaldar | 23BCS033 |

All work, decisions and approvals: **Aggimalla Abhishek** (with Claude Code). The other members are listed as report authors only (Q6).

## Consequences

**Q1 (25 days):** see PHASE_PLAN v2.0, scope lock §3. Out of scope, and listed as future work in the report: GNN surrogate, cloned-emulation twin, RL (PPO), LSTM/TFT, TimeGAN, RAG vector DB, scenario generator, config synthesis, React dashboard. Evaluation is 3 variants × 3 scenarios × 3 seeds.

**Q2 (virtual only):**
- No hardware track and no hardware purchases.
- All scenarios are reproducible by seed, which the evaluation needs.
- RULEBOOK N-1 still applies: the testbed never touches a real Wi-Fi interface or production network.
- Limitation to state in the report: radio behaviour comes from wmediumd's propagation and interference model, not real RF measurements.

**Q3 (Ollama cloud + local fallback, revised 2026-10-07):**
- Main path: an Ollama cloud model (no local RAM). It needs internet and an Ollama sign-in.
- Every GenAI feature must still work, possibly degraded, on the **local fallback** (`qwen2.5:3b`, 2.2 GB) on the 16 GB Mac alongside Docker and the VM (RULEBOOK L-8).
- Structured JSON output (schema-constrained) plus the validation/repair loop and the deterministic policy compiler (RULEBOOK L-2) make up for a weaker model.
- `genai/llm/client.py` stays provider-agnostic (RULEBOOK L-4), so a hosted model could be added later without code changes elsewhere.

## Task-level decisions

Smaller design choices made while building a task, cited in code and docs by these IDs. All decided by Abhishek, with Claude Code proposing.

| ID | Date | Decision | Why |
|---|---|---|---|
| P1.4-A | 2026-10-07 | A walker joins the **nearest AP** on arrival (no RSSI-threshold roaming) | Emulated stations never roam on their own (sticky clients) |
| P1.5-A | 2026-10-07 | Flow latency = **ping RTT** to srv1 (`ping -O`, lost pings tracked by sequence number) | iperf3 gives no latency; RTT is stricter than one-way delay |
| P1.5-B | 2026-10-07 | KPI records reach the collector through the AP agent's **`GET /kpi`** | Same pattern as `/aps` and `/stations`; RULEBOOK §4 forbids shared files |
| P1.6-A | 2026-10-07 | Stations of a failed AP **rejoin the nearest AP that is up** after 5 s | Normal client behaviour; otherwise V1 never recovers |
| P1.6-B | 2026-10-08 | **Emulated co-channel interference** + traffic sized to 4.6 Mbit/s per AP | Deviation #7 |
| P2.3-A | 2026-10-08 | Parquet with **pyarrow** only (pinned) | One dependency; P4 reads Arrow tables directly |
| P2.3-B | 2026-10-08 | Dataset v1 = 4 scenarios × seeds 42/43/44 → **train/val/test by seed** | Split by run (E-2), every scenario in every split; 2 h of data |
| P2.3-C | 2026-10-08 | Rows labelled with **`phase`** (normal/stress from the scenario's disruption) and **`event`** | Exact onset times for anomaly precision/recall and time to recover |
| P4.3-A | 2026-10-08 | **`TwinState` defined early** in `twin/state/` for the heuristics; P3.1 builds and extends it | One shared type, no adapter |
| P5.2-A | 2026-10-08 | Tools run over a **`Backend` interface** (`MockBackend` now, HTTP over the P3.6 API by Oct 20); **approval is not a tool** | genai only talks to the system through tools/API; the LLM can't approve its own actions |
| P5.2-B | 2026-10-08 | `simulate_in_twin` takes an **action**, not a policy (PROJECT_PLAN §5.6 says "action \| policy") | A policy becomes actions through the deterministic compiler (P5.3), and each action is then simulated |
| P5.2-C | 2026-10-08 | `get_alerts` takes **`since_s`** (look-back in seconds), `get_metrics` **`window_s`** | Simple for the LLM to fill; no clock or time-zone handling |
| P4.4-A | 2026-10-08 | The **executor (P4.4) owns** the verified, approved and applied records for every action, and persists them. The P5.2 tool layer keeps its in-memory check only as defence in depth | One source for the API, the loop and the LLM, and it survives restarts |
| P4.1-A | 2026-10-08 | Forecaster = **Holt's linear trend** (Holt-Winters without a seasonal part), **own implementation**, target = per-AP **`channel_util`**, 5 s steps, horizons 1 and 3 min | Runs last 10 minutes, so there is no season; a 2-parameter model needs no ML library; utilisation is what the congestion limit and time-to-recover use |
| P4.2-A | 2026-10-08 | Anomaly detector = **scikit-learn IsolationForest** (scikit-learn 1.9.1 + numpy 2.4.6, pinned, pip-audited) | The standard, well-tested implementation; reinventing it adds risk (RULEBOOK AI-8) |
| P4.2-B | 2026-10-08 | Detector scores **whole-network 30 s windows** (all 4 APs side by side + network KPIs); the alert names the AP that deviates most | The stress labels are per run; per-AP windows would label unaffected APs as stressed |
