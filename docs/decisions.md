# P0.1 Decisions

Answers to the open questions in [PROJECT_PLAN §17](PROJECT_PLAN.md#17-open-questions). Task P0.1 in [PHASE_PLAN](PHASE_PLAN.md) is done when every question below is answered.

| # | Question | Answer | Status | Date | Decided by |
|---|---|---|---|---|---|
| Q1 | Team size and timeline | **5 people** (see Team below). **Deadline Oct 31, 2026** (25 working days from Oct 6). Internal submission target **Oct 30**. The plan was rewritten as PHASE_PLAN **v2.0** (parallel tracks, reduced scope). | ✅ Decided | 2026-10-06 | Abhishek |
| Q2 | Real hardware or emulation only? | **Fully virtual, software only.** Wi-Fi APs, stations and radio are emulated with Mininet-WiFi (`mac80211_hwsim` + wmediumd); switches are Open vSwitch; everything runs in the Ubuntu VM and Docker. No physical APs, Raspberry Pis or real Wi-Fi interfaces. | ✅ Decided | 2026-10-06 | Abhishek |
| Q3 | LLM provider, and is there an API budget? | **Ollama only (local, free), no hosted API budget.** The specific model is chosen in P0.7 and recorded in ADR-001. | ✅ Decided | 2026-10-06 | Abhishek |
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

**Q3 (Ollama only):**
- Every GenAI feature must work with a local model on a 16 GB Mac, alongside Docker (~8 GB) and the VM (4–6 GB). Model size matters: aim for ≤ 8B parameters, quantized.
- Ollama's `-cloud` models are **not** used. They aren't local or offline.
- Structured JSON output (schema-constrained) plus the validation/repair loop and the deterministic policy compiler (RULEBOOK L-2) make up for a weaker model.
- `genai/llm/client.py` stays provider-agnostic (RULEBOOK L-4), so a hosted model could be added later without code changes elsewhere.
