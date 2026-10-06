# controller

| Path | Runs on | Purpose | Task |
|---|---|---|---|
| `apps/` | VM, **Python 3.8**, `~/ryu-venv` (ADR-002) | Ryu apps: forwarding, stats polling, northbound REST, flow and queue installation | P1.2 |
| `executor/` | Mac, Python 3.11 | Applies **verified** actions only, watches KPIs, rolls back, rate-limits, writes the audit log | P4.3 |

- `executor/` has to keep 100% branch coverage on its safety paths (RULEBOOK T-2, T-5).
- Must not import `ml`, `genai`, `api`, `testbed` or `telemetry` (import-linter contract).
