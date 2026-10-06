# testbed

Runs **on the testbed VM** (Ubuntu 20.04, **Python 3.8**; see ADR-003). Covers Mininet-WiFi topologies, mobility, the AP agent, traffic profiles, KPI probes and the scenario runner (Phase 1).

| Path | Task | Status |
|---|---|---|
| `smoke/` | P0.2 smoke test (2 APs, 4 stations, Ryu `simple_switch_13`) | ✅ passing |
| `topologies/campus_v1.py` | P1.1 | — |
| `ap_agent.py` | P1.3 | — |
| `mobility/`, `traffic/`, `run_scenario.py` | P1.4–P1.6 | — |

**Rules for this folder**
- Keep code Python 3.8-compatible. `ruff.toml` here sets `target-version = py38`.
- Every topology calls `ensure_associated()` after `ap.start()` (docs/setup.md, Known problems #4).
- Run things on the VM through **script files**. `mn -c` kills any shell whose command line mentions `ryu-manager`, `hostapd` or `ping`, and deletes `/tmp/*.log` (Known problems #5–6).
- May import only `common`.

**Run:** `make smoke-vm` from the Mac, or `testbed/smoke/run_smoke.sh` on the VM.
