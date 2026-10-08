# LLM intent-based networking

**Citation (IEEE):** A. Mekrache, A. Ksentini and C. Verikoukis, "Intent-Based Management of Next-Generation Networks: an LLM-Centric Approach," *IEEE Network*, vol. 38, no. 5, pp. 29–36, Sep. 2024, doi: [10.1109/MNET.2024.3420120](https://doi.org/10.1109/MNET.2024.3420120).

## Summary
Intent-based networking (IBN) simplifies network management by letting operators state goals instead of low-level configuration, but existing IBN systems still express intents in structured formats such as JSON or YAML. The paper proposes an LLM-centric architecture that manages the whole intent life cycle in natural language — decomposition, translation, negotiation, activation and assurance — and validates it with a real deployment in the EURECOM 5G facility, where intents are defined, decomposed, translated and activated from natural-language input.

## What we reuse
- Natural language as the operator interface, with the LLM producing a structured policy (our `Policy` JSON, PROJECT_PLAN §7.4).
- The life-cycle view: translation is not the end — the intent must be activated and then assured (our policies stay active and the verifier re-checks their objectives every loop).

## Where we differ
- Our LLM never configures anything directly: its output is validated against a schema, compiled by a **deterministic** compiler, and simulated in the twin before an executor applies it (RULEBOOK rule 8). *(Check full text for how the paper guards against wrong translations.)*
- We target a Wi-Fi campus (QoS priority, client steering, channel/power changes) rather than 5G service deployment.
- Small local models must work too (offline fallback, ADR-001), so we rely on structured output plus a repair loop rather than on model size.
