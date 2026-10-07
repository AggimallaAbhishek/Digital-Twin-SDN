# testbed

Runs **on the testbed VM** (Ubuntu 20.04, **Python 3.8**; see ADR-003). Covers Mininet-WiFi topologies, mobility, the AP agent, traffic profiles, KPI probes and the scenario runner (Phase 1).

| Path | Task | Status |
|---|---|---|
| `smoke/` | P0.2 smoke test (2 APs, 4 stations, Ryu `simple_switch_13`) | ✅ passing |
| `topologies/campus_v1.py` | P1.1 (`--check`, `--cli`, `--serve` runs the AP agent) | ✅ |
| `ap_agent.py`, `ap_logic.py` | P1.3 AP agent (REST, port 8081) | ✅ `make ap-agent-vm` |
| `mobility/` | P1.4 scheduled-crowd mobility | ✅ `make mobility-vm` |
| `traffic/`, `run_scenario.py` | P1.5–P1.6 | — |

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
| POST | `/aps/{ap}/channel` | `{"channel": 1\|6\|11}` → `{ts, ap, channel}`. hostapd channel switch; clients follow without reconnecting |
| POST | `/aps/{ap}/txpower` | `{"dbm": 5–20}` → `{ts, ap, tx_power_dbm}`. Rounded to whole dBm (Mininet applies integers) |
| POST | `/stations/{sta}/associate` | `{"ap": "ap2"}` → `{ts, sta, ap}`. Disconnect + connect to that BSSID (~4 s) |

- **Errors:** 422 invalid body or out-of-bounds value (nothing applied), 404 unknown AP/station/path, 500 the radio didn't apply the change. A 200 means `iw` confirmed the change.
- **Measurements (decisions P1.3):** `channel_util` is estimated airtime: each client's bytes per direction ÷ that direction's bitrate, over the time since the previous `/stats` call for that AP (the first call returns 0). `noise_dbm` is hwsim's fixed −92 dBm floor, so `snr_db = rssi_dbm + 92`. `rx_bitrate_mbps` is the AP's downlink bitrate to that station.
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
