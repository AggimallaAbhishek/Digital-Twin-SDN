# twin

The digital twin (Phase 3, **critical path**): state mirror and sync (`state/`), simulators (`sim/`: analytical, GNN, emulation), the verifier (`verify/`), validation harness (`validation/`) and the closed-loop orchestrator (`loop.py`, P4.5).

- Simulation always works on a **copy** of `TwinState` (RULEBOOK C-7).
- `verify/` needs 100% branch coverage (RULEBOOK T-2).
- Must not import `ml`, `genai`, `api`, `controller`, `testbed` or `telemetry`.
