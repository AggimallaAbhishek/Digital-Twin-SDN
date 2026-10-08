# twin

The digital twin (Phase 3, **critical path**): state mirror and sync (`state/`), simulators (`sim/`: analytical, GNN, emulation), the verifier (`verify/`), validation harness (`validation/`) and the closed-loop orchestrator (`loop.py`, P4.5).

- Simulation always works on a **copy** of `TwinState` (RULEBOOK C-7).
- `verify/` needs 100% branch coverage (RULEBOOK T-2).
- Must not import `ml`, `genai`, `api`, `controller`, `testbed` or `telemetry`.

**So far:**
- **`state/model.py`:** `TwinState` (APs, stations, flows; read-only mappings; a station's AP is stored once, on the station).
- **`state/builder.py`, `state/sync.py` (P3.1):** `TwinSync(conn, campus, run_id, config).refresh()` reads the last 10 s of a run from InfluxDB (`common/influx.py`) and builds the state from the latest record of each series. An AP is up if it reported within 5 s (`config/twin.yaml`). `sync.lag_s` is the age of the newest telemetry.
- **`radio.py`:** predicted RSSI (log-distance, −16 dBm at 1 m, exponent 4, fitted to measurements) and co-channel load. The twin's copy of the testbed's interference model is pinned equal by `tests/contract/test_radio_model_parity.py`.
