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

## Tools (P5.2)

`genai/tools/` is the only way the agent reads or changes the network (RULEBOOK L-1).

```python
tools = ToolLayer(MockBackend())   # recorded fixtures; HTTP backend over the API once P3.6 exists
tools.specs()                      # get_topology, get_metrics, get_alerts, simulate_in_twin, apply_action
tools.call("simulate_in_twin", {"action": {...}})    # -> Verdict fields, or {"error": ...}
```

- **Arguments are untrusted** (L-6). Every call is validated with pydantic; a bad call returns `{"error": ...}` for the model to read instead of raising.
- **`apply_action` refuses** an ID that has no accepted verdict from `simulate_in_twin` in this session, an ID that was already applied, and a high-impact action until `ToolLayer.approve()`. `approve()` is called by the operator through the API; it is not a tool, so the LLM can't approve its own actions. The backend re-checks the verdict as well.
- **`MockBackend`:** topology, AP stats and KPI series come from `tests/fixtures/`. There are no alerts yet (P4.2). Every action is accepted, with the real impact class and approval rule.

## Intent eval (P5.4)

`genai/eval/intents.jsonl` holds 30 intents with the policy each should produce. `run_intents.py` sends each one through the LLM client with `genai/prompts/intent_v1.md` and reports accuracy (RULEBOOK L-7: a prompt or model change may not lower it by more than 2 points).

```sh
uv run python -m genai.eval.run_intents                               # config/llm.yaml (cloud, local fallback)
uv run python -m genai.eval.run_intents --config <copy with model: qwen2.5:3b>   # local model only
```

- **Correct** = schema-valid, and scope (zone + set of app classes), objectives and constraints equal the expected ones as sets (decisions P5.4-A). Each expected policy is checked against the `Policy` schema on load.
- **2026-10-08, prompt intent_v1:** `gpt-oss:120b-cloud` 29/30 (96.7%); `qwen2.5:3b` 20/30 (66.7%).
