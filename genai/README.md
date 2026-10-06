# genai

The LLM layer (Phase 5): provider-agnostic client (`llm/`), tools/MCP server (`tools/`), intent engine and policy compiler (`intent/`), RAG (`rag/`), copilot agent (`agent/`), root-cause explainer (`rca/`), scenario generator (`scenarios/`), prompts (`prompts/`) and the eval set (`eval/`).

- **The LLM proposes, the twin verifies, the executor applies.** No tool writes to the network directly (RULEBOOK L-1).
- Talks to the rest of the system **only through tools and the API**. It must not import `controller`, `testbed`, `twin`, `telemetry` or `ml`.
- Prompts are versioned files. Changing one means re-running the intent eval (L-3, L-7).
