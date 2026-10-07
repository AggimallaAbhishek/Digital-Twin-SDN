# genai

The LLM layer (Phase 5): provider-agnostic client (`llm/`), tools/MCP server (`tools/`), intent engine and policy compiler (`intent/`), RAG (`rag/`), copilot agent (`agent/`), root-cause explainer (`rca/`), scenario generator (`scenarios/`), prompts (`prompts/`) and the eval set (`eval/`).

- **The LLM proposes, the twin verifies, the executor applies.** No tool writes to the network directly (RULEBOOK L-1).
- Talks to the rest of the system **only through tools and the API**. It must not import `controller`, `testbed`, `twin`, `telemetry` or `ml`.
- Prompts are versioned files. Changing one means re-running the intent eval (L-3, L-7).

## LLM client (P5.1)

`genai/llm/client.py` is the only code that calls a model (RULEBOOK L-4).

```python
client = LLMClient.from_config()                     # config/llm.yaml
result = client.complete_json(messages, Policy, prompt_version="intent/v1")
result.value, result.model, result.fell_back         # validated Policy, who answered, fallback?
client.complete_text(messages, prompt_version="rca/v1")   # free text, same fallback + logging
```

- **Fallback (ADR-001):** main cloud model with `cloud_timeout_s`; if it is unreachable (connection error, HTTP error, timeout) the local `fallback_model` is tried once with `timeout_s`. Both down → `LLMUnavailableError`.
- **Repair (L-2):** a schema-invalid reply is sent back with the validation errors, at most `max_repair_retries` times on the same model, then `LLMOutputError`. Invalid output does not trigger the fallback.
- **Logging (L-5):** one JSON line per model call in `logs/llm_calls.jsonl` (gitignored): time, model, fallback, prompt version, schema, attempt, tokens, latency, valid, error, cost. Prompt and reply text are never logged.
- **Tests:** `tests/unit/test_llm_client.py` (fake transport, no network); `make llm-client-check` runs the live check against Ollama.
