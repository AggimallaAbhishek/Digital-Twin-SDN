# testbed

Runs **on the testbed VM** (Ubuntu 20.04, **Python 3.8**; see ADR-003). Covers Mininet-WiFi topologies, mobility, the AP agent, traffic profiles, KPI probes and the scenario runner (Phase 1).

| Path | Task | Status |
|---|---|---|
| `smoke/` | P0.2 smoke test (2 APs, 4 stations, Ryu `simple_switch_13`) | ✅ passing |
| `topologies/campus_v1.py` | P1.1 (`--check`, `--cli`, `--serve` runs the AP agent) | ✅ |
| `ap_agent.py`, `ap_logic.py` | P1.3 AP agent (REST, port 8081) | ✅ `make ap-agent-vm` |
| `mobility/` | P1.4 scheduled-crowd mobility | ✅ `make mobility-vm` |
| `traffic/` | P1.5 traffic profiles + KPI probe (`GET /kpi` on the agent) | ✅ `make traffic-vm` |
| `run_scenario.py`, `scenario_plan.py`, `interference.py` | P1.6 scenario runner (+ co-channel interference emulation) | ✅ `make scenario-repro-vm` |

**Rules for this folder**
- Keep code Python 3.8-compatible. `ruff.toml` here sets `target-version = py38`.
- Every topology calls `ensure_associated()` after `ap.start()` (docs/setup.md, Known problems #4).
- Run things on the VM through **script files**. `mn -c` kills any shell whose command line mentions `ryu-manager`, `hostapd` or `ping`, and deletes `/tmp/*.log` (Known problems #5–6).
- May import only `common`.

**Run:** `make smoke-vm` from the Mac, or `testbed/smoke/run_smoke.sh` on the VM.

## AP agent (`http://<vm>:8081`, P1.3)

OpenFlow can't change the radio, so this HTTP server runs inside the topology process and drives Mininet-WiFi directly (`campus_v1 --serve`, or `ap_agent.start_in_background()` from a script).

| Method | Path | Body → response |
|---|---|---|
| GET | `/aps` | → `{ts, aps: [{ap, bssid, ssid, channel, tx_power_dbm, x, y, n_clients}]}` |
| GET | `/aps/{ap}/stats` | → `{ts, ap, channel, n_clients, channel_util, tx_power_dbm, retries, noise_dbm}` (`APStats` fields) |
| GET | `/stations` | → `{ts, stations: [{sta, ap, rssi_dbm, snr_db, tx_bitrate_mbps, rx_bitrate_mbps, x, y}]}` (`StationStats` fields) |
| GET | `/kpi` | → `{ts, kpis: [{ts, flow_id, app_class, throughput_mbps, latency_ms, jitter_ms, loss_pct}]}`: latest `KPIRecord` fields per flow (P1.5); `[]` when no traffic runs |
| POST | `/aps/{ap}/channel` | `{"channel": 1\|6\|11}` → `{ts, ap, channel}`. hostapd channel switch; clients follow without reconnecting |
| POST | `/aps/{ap}/txpower` | `{"dbm": 5–20}` → `{ts, ap, tx_power_dbm}`. Rounded to whole dBm (Mininet applies integers) |
| POST | `/stations/{sta}/associate` | `{"ap": "ap2"}` → `{ts, sta, ap}`. Disconnect + connect to that BSSID (~4 s) |

- **Errors:** 422 invalid body or out-of-bounds value (nothing applied), 404 unknown AP/station/path, 500 the radio didn't apply the change. A 200 means `iw` confirmed the change.
- **Measurements (decisions P1.3, deviation #8):** `channel_util` is the share of the AP's *current capacity* its clients used: (bytes sent + received) × 8 ÷ elapsed time ÷ capacity, over the time since the previous `/stats` call for that AP (the first call returns 0). Capacity is `radio_model.ap_capacity_mbps` (4.6 Mbit/s), or the AP's co-channel cap while the scenario runner applies one. The P1.3 estimate (bits ÷ the bitrate `iw` reports) was dropped because those bitrates have no effect on throughput in this emulator. `noise_dbm` is hwsim's fixed −92 dBm floor, so `snr_db = rssi_dbm + 92`. `rx_bitrate_mbps` is the AP's downlink bitrate to that station.
- **Bounds** (channels, tx power) are copied from `common/schemas.py` into `ap_logic.py`; `tests/unit/test_ap_logic.py` fails if they drift.
- **Concurrency:** Mininet node shells aren't thread-safe. Anything else in the process that calls `node.cmd()` while the agent serves must hold `agent.lock`.
- **Safety:** the agent applies what it is told. Only the action executor (P4.4) calls the POST endpoints, and only for actions with an accepted twin `Verdict`.
- **Steering:** use `wifi_utils.steer()`, which checks the target BSSID. `ensure_associated()` accepts a link to *any* AP and is only for start-up. Pass the agent's lock (`steer(..., lock=agent.lock)`): it is held per command, not for the ~4 s wait.

## Crowd mobility (`mobility/`, P1.4)

A scenario's `mobility.groups` (fields of `common/schemas.py` `CrowdGroup`) become one straight-line walk per station:

- **Who:** a seeded sample of the stations in `from` that aren't still walking. Later groups see where earlier walkers ended up.
- **When:** departures spaced evenly over `[start_s, start_s + spread_s]`; walking speed 1.2 m/s (`crowd.WALK_SPEED_MPS`), positions updated every second.
- **Where:** a seeded point inside the `to` zone. `setPosition` moves the station in wmediumd's radio model, so its signal follows.
- **Re-association (decision P1.4-A):** stations never roam on their own (sticky clients, P1.4 probe), so on arrival each one joins the **nearest AP**; a flash crowd therefore lands on ap1. RSSI-threshold roaming during the walk is in the PHASE_PLAN parking lot.

```python
walks = plan_crowd(parse_groups(scenario["mobility"]["groups"]), layout, place_stations(layout), seed)
CrowdRunner(walks, layout, campus, lock=agent.lock).run()   # blocks; the scenario runner threads it
```

`crowd.py` is pure (unit-tested on the Mac, 100% branch coverage); `runner.py` drives Mininet-WiFi on the VM. The controller notices each re-associated station as a host move and drops its stale flows (Known problems #11).

## Traffic and KPI probe (`traffic/`, P1.5)

Profiles live in `traffic/profiles.yaml`. All traffic is **downlink**, srv1 → station (docs/scenario.md).

| Profile | Tool | Default |
|---|---|---|
| `video` | iperf3 UDP, reverse mode | 3 Mbit/s constant (a scenario's `rate_mbps` overrides it) |
| `bulk` | iperf3 TCP, reverse mode | unlimited (optional `rate_mbps` cap) |
| `web` | curl fetches a 500 KB object from `python3 -m http.server` on srv1 | exponential think time, mean 2 s (seeded); 10 s timeout |

**KPI records.** One record per flow per 1 s window, with the `KPIRecord` fields minus `scenario_id`/`run_id`, which the collector adds. `flow_id` is `<sta>-<class>`.

| | throughput | latency | jitter | loss |
|---|---|---|---|---|
| video | iperf3 per-second line | ping RTT mean | iperf3 jitter | iperf3 datagram loss (ping loss if iperf3 counted none) |
| bulk | iperf3 per-second line | ping RTT mean | ping jitter* | ping loss |
| web | mean goodput of the fetches that finished in the window | ping RTT mean | ping jitter* | the higher of ping loss and the failed-fetch % |

\* Ping jitter is the mean absolute difference between consecutive RTTs (IP delay variation, RFC 3393), not a standard deviation.

- **Decision P1.5-A (2026-10-07): latency comes from ping.** Latency is a round-trip time from `ping -O -i 0.2` on each active station to srv1. It is stricter than one-way delay. Flows on the same station share it.
- **Lost pings:** a ping counts as lost if no reply arrives within 1 s. Loss is tracked by sequence number, not by clock, because ping's real interval drifts (about 0.207 s on the VM). A dead link therefore reads 100% loss, with latency set to the 1 s timeout, rather than producing no records.
- **Web records** appear only in windows where a fetch finished. Video and bulk produce one record every window.
- **Bulk raises its own station's latency.** It fills the radio at about 4.6 Mbit/s, and its RTT rises to roughly 60–80 ms from queueing behind its own traffic. That is expected.
- **Decision P1.5-B (2026-10-07): records reach the collector through the AP agent's `GET /kpi`.** That is the same polling pattern as `/aps` and `/stations`, and RULEBOOK §4 rules out shared files. `kpi.jsonl` is a local run log for checks and fixtures, not a telemetry path.
- **`rate_mbps`** applies to video and bulk only. Passing a rate for a web flow is an error.
- **Process model:** tools start with `node.popen()`, so they run as their own processes, not in the shared node shell, and the agent lock is held only while each one launches. iperf3 3.7 can't stream JSON, so the probe reads its `--forceflush` text output.

```python
probe = TrafficProbe(campus, load_traffic_config_file(), log_dir, lock=agent.lock, seed=seed)
agent.kpi_source = probe.latest          # GET /kpi
probe.start()
probe.start_flow("sta1", "video")        # P1.6 picks stations and start times from the scenario
probe.stop_all()
```

`parse.py` and `profiles.py` are pure: unit-tested on the Mac with 100% branch coverage. `runner.py` drives Mininet-WiFi on the VM. Every record is also appended to `<LOG_DIR>/kpi.jsonl`.

## Scenario runner (`run_scenario.py`, P1.6)

```bash
make scenario-vm SCENARIO=lecture_flash_crowd        # one unattended run (~11 min)
make scenario-repro-vm SCENARIO=lecture_flash_crowd  # 3 runs, same seed, throughput within ±5%
```

It plays `experiments/scenarios/<id>.yaml` on campus_v1 with the AP agent serving on port 8081 (reachable from the Mac for the collector, P2.1) and the traffic probe behind `GET /kpi`:

- **Crowd walks** (`mobility/`) run on the scenario clock.
- **Traffic** starts at each item's `start_s`. Selectors (`*`, `<zone>:*`, `staN`) are resolved at that moment from the planned positions, so `lecture_hall:*` includes the walkers who have arrived. All flows of a step start together, with one 0.5 s server wait.
- **Events** are the *environment* changing, so they don't go through the twin:
  - `force_channel` uses the agent's channel switch;
  - `ap_down` / `ap_up` run `hostapd_cli disable` / `enable`.

  After an `ap_down`, the stations it dropped rejoin the nearest AP that is still up after `radio_model.orphan_rejoin_s` (5 s), all at once, like real clients. After an `ap_up`, nobody moves back: stations are sticky.
- **Interference** (`interference.py`, deviation #7): every second the runner re-reads every AP's channel and caps each one's downlink with an htb qdisc at `4.6 / (1 + Σ w)`. Here `w` is 1 for a same-channel AP that is up and within 30 m, falling to 0 at 60 m. Caps are removed as soon as the channels change. See docs/scenario.md "Radio model" for why.

**Artefacts** in `<LOG_DIR>/runs/<run_id>/`:
- `manifest.json`: seed, git commit, config hash and host;
- `events.jsonl`: scenario time of every traffic start, event, cap change, arrival and rejoin;
- `kpi.jsonl`: every KPI record;
- `summary.json`: per class, record count, mean throughput, p50/p95 latency and mean loss.

**Pure and Mac-tested:** `scenario_plan.py` and `interference.py` (100% branch coverage). `tests/contract/test_scenario_files.py` checks every scenario file against `common/schemas.py` `Scenario`.

**Clock:** `make sync-vm` also sets the VM clock from the Mac (`make vm-clock`; setup.md Known problems #12). Telemetry timestamps come from the VM.
