# twin

The digital twin (Phase 3, **critical path**): state mirror and sync (`state/`), simulators (`sim/`: analytical, GNN, emulation), the verifier (`verify/`), validation harness (`validation/`) and the closed-loop orchestrator (`loop.py`, P4.5).

- Simulation always works on a **copy** of `TwinState` (RULEBOOK C-7).
- `verify/` needs 100% branch coverage (RULEBOOK T-2).
- Must not import `ml`, `genai`, `api`, `controller`, `testbed` or `telemetry`.

**So far:**
- **`state/model.py`:** `TwinState` (APs, stations; a station's AP is stored once, on the station). It was defined early for P4.3; P3.1 builds it from InfluxDB.
- **`radio.py`:** predicted RSSI (log-distance, −16 dBm at 1 m, exponent 4, fitted to measurements) and co-channel load. The twin's copy of the testbed's interference model is pinned equal by `tests/contract/test_radio_model_parity.py`.
