# ADR-001: LLM is Ollama `qwen2.5:3b` (local), with `qwen2.5:7b` as fallback

- **Status:** Accepted (Abhishek, 2026-10-07)
- **Phase / task:** P0.7
- **Related:** decisions Q3 (Ollama only, no API budget), RULEBOOK L-2/L-4/L-8, `config/llm.yaml`

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

## Decision

Use **`qwen2.5:3b`** as the default model and keep **`qwen2.5:7b`** installed as the fallback (`config/llm.yaml`).

## Consequences

- Best accuracy on the sample, the fastest, and the smallest memory footprint, which leaves room for Docker + VM during the live demo.
- **The sample is small (5 intents).** Re-run the comparison on the full **30-intent set in P5.4**. Switch to the 7B model only if it is clearly better there, via an update to this ADR.
- Prompts matter more than model size here: P5.3 must use explicit field rules + few-shot examples, kept as versioned files in `genai/prompts/` (RULEBOOK L-3).
- `phi3` is removed from consideration. Ollama `-cloud` models are not used (not local).
- Disk: models use ~6.6 GB (`qwen2.5:3b` 1.9 GB + `qwen2.5:7b` 4.7 GB); `phi3` (2.2 GB) can be deleted with `ollama rm phi3`.
