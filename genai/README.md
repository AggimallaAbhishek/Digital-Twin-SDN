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
- **2026-10-08, prompt intent_v2 (few-shot, P5.3):** `gpt-oss:120b-cloud` 30/30 (100%); `qwen2.5:3b` 21/30 (70%). The local model's misses are mostly hard constraints.
- The eval always uses the intent engine's prompt (`genai/intent/engine.py` `PROMPT`).

## Intent engine (P5.3)

```python
engine = IntentEngine(LLMClient.from_config(), ToolLayer(backend))
result = engine.handle("Give video calls in the lab priority.", flows, now)   # flows: FlowRef list
result.policy, result.actions, result.verdicts, result.standing, result.error
```

1. `parse_intent` (also what the intent eval measures): the LLM client turns the text into a `Policy` (`prompts/intent_v2.md`, schema-constrained, at most 2 repairs). No valid policy → `error`, and the compiler never sees it.
2. `intent/compiler.py` (deterministic, decision P5.3-A): `priority` → `set_qos_queue` (high 1, normal 0, low 2; one per app class); `throughput_mbps <=` → `rate_limit_flow` on every matching flow (strictest cap wins). KPI targets and constraints become no action: they stay in `standing` for the verifier. Refused with a reason: a priority for all traffic everywhere (also when all three app classes are named), conflicting priorities, a cap under 1 Mbit/s.
3. Each action goes to `simulate_in_twin`. Nothing is applied: the executor (P4.4) does that after approval (L-1).
4. The policy keeps the operator's exact words as `intent_text`, whatever the model echoed (validated by the schema again).
5. **Off by default** (`config/intent.yaml` `enabled: false`, RULEBOOK B-5) until the GenAI exit gate (M3); the API checks it.

`flows` (id, app class, zone) come from the twin state; `POST /intents` arrives with the API in P3.6 (decision P5.3-B).
