# twin

The digital twin (Phase 3, **critical path**): state mirror and sync (`state/`), simulators (`sim/`: analytical, GNN, emulation), the verifier (`verify/`), validation harness (`validation/`) and the closed-loop orchestrator (`loop.py`, P4.5).

- Simulation always works on a **copy** of `TwinState` (RULEBOOK C-7).
- `verify/` needs 100% branch coverage (RULEBOOK T-2).
- Must not import `ml`, `genai`, `api`, `controller`, `testbed` or `telemetry`.

**So far:**
- **`state/model.py`:** `TwinState` (APs, stations, flows; read-only mappings; a station's AP is stored once, on the station).
- **`state/builder.py`, `state/sync.py` (P3.1):** `TwinSync(conn, campus, run_id, config).refresh()` reads the last 10 s of a run from InfluxDB (`common/influx.py`) and builds the state from the latest record of each series. An AP is up if it reported within 5 s (`config/twin.yaml`). Lag = `lag_s(state, now)` taken when the state is used: the age of the **stalest** measurement's newest record (ap_stats, sta_stats, kpi), so one stalled measurement can't hide behind fresh ones, and the query time counts.
- **`sim/apply.py` (P3.2):** `apply(state, action)` returns a new `TwinState` with the action applied (all 7 allow-listed types). AP down: its stations rejoin the nearest AP still up. Unknown or stale targets raise `ValueError`.
- **`radio.py`:** predicted RSSI (log-distance, −16 dBm at 1 m, exponent 4, fitted to measurements) and co-channel load. The twin's copy of the testbed's interference model is pinned equal by `tests/contract/test_radio_model_parity.py`.

## Analytical simulator (P3.3)

```python
params = load_sim_params(yaml.safe_load(Path("config/sim.yaml").read_text()))
radio = load_radio_params(campus)                    # config/campus_v1.yaml
baseline = simulate(state, radio, params)            # SimResult: flows, ap_util, kpis
predicted = simulate(apply(state, action), radio, params)
```

- Per AP that is up: capacity 4.6 Mbit/s, capped by same-channel APs that are up (`radio.py`, the model the testbed emulates). Strict priority between OVS queues 1 → 0 → 2, max-min fair within a queue. Video and web lose what they can't send; TCP bulk only sees base loss.
- Latency = base + `service_ms` × the mean length of an M/M/1/K queue at the load of the flow's queue and those served before it. The queue is bounded, so latency levels off at saturation, as measured.
- App classes are one table in `config/sim.yaml` (`apps`: offered rate, elastic = TCP, fetch = the probe reports one fetch's rate). Web is a fetch class: its throughput is `fetch_efficiency` × the capacity left by other traffic in the same or a higher queue, while `carried_mbps` is the little it puts on the air.
- A flow with no working AP: 0 Mbit/s, 100% loss, 1000 ms.
- `kpis` (`common.schemas.KPIValues`): total traffic carried (fetch rates don't add up), mean latency and loss over flows, Jain's index of clients per AP.
- **Off by default** (`enabled: false`, RULEBOOK B-5) until the twin's exit gate (M2); the verifier, API and loop must check it.
- Not modelled: wired links (100 Mbit/s, negligible; deviation #12), the ~4 s reconnection of a steered station. QoS queues are modelled but not yet provisioned in the testbed (deviation #11, task P4.4a).
- Parameters in `config/sim.yaml` are first estimates from data/v1; P3.5 calibrates them. `tests/contract/test_sim_traffic_parity.py` keeps the video rate and probe timeout equal to the testbed's.

## Verifier (P3.4)

```python
context = VerifyContext(campus, radio, sim_params, load_verify_config(raw))   # config/verify.yaml
verdicts = verify(state, actions, context.with_policies(standing))   # one Verdict per action
```

- A set is checked and simulated **together** (an intent's actions are all or nothing, P3.4-B).
- **Bounds** (PROJECT_PLAN §7.3, ADR-004), on the state the earlier actions leave: steer ≤ 30% of the source AP's clients, only stations on it, target signal ≥ −75 dBm; tx power step ≤ 3 dB; never the last AP up in a zone; no reroute (deviation #9); unknown targets refused.
- **KPIs** of the affected flows (P3.4-A): mean throughput, p95 video latency, mean loss; Jain network-wide. **Reject** if a KPI gets > 5% worse while none gets > 5% better (§7.5).
- **Policies:** a hard constraint may not break (or get worse if already broken); a met objective may not become missed. Jitter isn't predicted, so jitter targets aren't checked.
- **Impact:** high always needs approval; medium needs it while `config/verify.yaml` says so (until P3.5, P3.4-C). 100% branch coverage.
