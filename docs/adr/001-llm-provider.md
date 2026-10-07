# ADR-001: LLM is Ollama cloud `gpt-oss:120b-cloud`, with local `qwen2.5:3b` as automatic fallback

- **Status:** Accepted (Abhishek, 2026-10-07). **Revised the same day** after round 3 (cloud models); the original local-only decision is kept below for the record.
- **Phase / task:** P0.7
- **Related:** decisions Q3 (revised: Ollama cloud + local fallback), RULEBOOK L-2/L-4/L-8, `config/llm.yaml`, PHASE_PLAN deviation #6

## Context

The GenAI layer has to run **locally and free** (decisions Q3) on a 16 GB Apple Silicon Mac that also runs Docker Desktop (~8 GB) and the testbed VM (4–6 GB). The main LLM job is turning an operator intent into a `common.schemas.Policy` JSON object. That output is schema-constrained (Ollama `format` = the Policy JSON schema), validated by Pydantic, compiled deterministically, and checked by the twin, so a small model can be good enough.

## Experiment

`uv run python -m genai.eval.compare_models --models phi3 qwen2.5:3b qwen2.5:7b`. It uses 5 intents covering zone + app class + KPI objectives + priority, temperature 0, the same prompt and schema for every model, and one warm-up call per model. It ran with Docker and the VM up.

**Round 1** (zero-shot prompt):

| Model | Schema-valid | Scope | Objectives | Fully correct | Mean s |
|---|---|---|---|---|---|
| phi3 (3.8B) | 4/5 | 0/5 | 3/5 | 0/5 | 4.1 |
| qwen2.5:3b | 5/5 | 3/5 | 4/5 | 2/5 | 2.8 |
| qwen2.5:7b | 5/5 | 0/5 | 5/5 | 0/5 | 6.5 |

Diagnosis: the models got zones right but left `scope.app_class` null ("all traffic") even when the intent named a traffic type. The prompt never said to fill it in. That's a prompt gap, not a model limit.

**Round 2** (one explicit app-class rule + one worked example, the style P5.3 will use):

| Model | Schema-valid | Scope | Objectives | Fully correct | Mean s | Max s | Resident RAM |
|---|---|---|---|---|---|---|---|
| phi3 (3.8B) | 5/5 | 5/5 | 4/5 | 4/5 | 3.5 | 5.3 | 3.8 GB |
| **qwen2.5:3b** | **5/5** | **5/5** | **5/5** | **5/5** | **3.0** | **3.7** | **2.2 GB** |
| qwen2.5:7b | 5/5 | 5/5 | 4/5 | 4/5 | 6.0 | 7.0 | 4.7 GB |

Both misses (phi3, qwen2.5:7b) were on the two-objective intent "…lab priority and keep latency under 50 ms".

**Round 3** (cloud models through the same local Ollama API, same prompt as round 2, 2026-10-07):

| Model | Fully correct | Mean s | Max s | Local RAM | Status |
|---|---|---|---|---|---|
| qwen2.5:3b (local) | 5/5 | 3.0 | 3.7 | 2.2 GB | ok |
| gpt-oss:20b-cloud | 5/5 | 3.3 | 4.8 | ~0 | ok |
| **gpt-oss:120b-cloud** | **5/5** | **1.6** | **2.3** | ~0 | ok |
| qwen3-coder:480b-cloud | — | — | — | — | **retired 2026-07-15** (HTTP 410) |
| deepseek-v3.1:671b-cloud | — | — | — | — | **retired 2026-07-15** (HTTP 410) |

All available models saturate the 5-intent set, so it can't separate them on accuracy.

## Decision (revised)

- **Main model: `gpt-oss:120b-cloud`.** It's the fastest in the test and the largest model, which should help on the harder 30-intent set. It uses no local RAM.
- **Automatic fallback: `qwen2.5:3b` (local).** `genai/llm/client.py` (P5.1) calls the cloud model with a short timeout (`cloud_timeout_s: 15`). On any error or timeout it retries once on the local model and logs which model answered. The live demo therefore still works with no internet.
- `qwen2.5:7b` was deleted (4.7 GB). `phi3` is no longer needed (`ollama rm phi3`).

### Original decision (superseded)

Use `qwen2.5:3b` as the default model, with `qwen2.5:7b` as the fallback.

## Consequences

- **Demo dependency:** the main path needs internet + an Ollama sign-in. Mitigations: automatic local fallback, `keep_alive` keeps the local model loaded, and P7.4 rehearses the demo once **with Wi-Fi off** to prove the fallback works.
- **Account limits:** Ollama cloud usage may be rate-limited; terms unverified. Keep evaluation runs modest and log every call (RULEBOOK L-5).
- **Privacy:** prompts and (virtual) network data go to Ollama's cloud. Acceptable: everything is a simulated campus, and no secrets go into prompts (RULEBOOK §14).
- **The sample is small (5 intents).** P5.4 re-runs the comparison (main vs fallback, and `gpt-oss:20b-cloud`) on the full **30-intent set**, and reports both models' accuracy in the report.
- Retired cloud models (`qwen3-coder:480b`, `deepseek-v3.1:671b`) are not used; their stale entries can be removed with `ollama rm`.
- Prompts matter more than model size here: P5.3 must use explicit field rules + few-shot examples, kept as versioned files in `genai/prompts/` (RULEBOOK L-3).
- `phi3` is removed from consideration. Ollama `-cloud` models are not used (not local).
- Disk: models use ~6.6 GB (`qwen2.5:3b` 1.9 GB + `qwen2.5:7b` 4.7 GB); `phi3` (2.2 GB) can be deleted with `ollama rm phi3`.
