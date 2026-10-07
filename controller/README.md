# controller

| Path | Runs on | Purpose | Task |
|---|---|---|---|
| `apps/twin_controller.py` | VM, **Python 3.8**, `~/ryu-venv` (ADR-002) | Ryu app: L2 learning, stats polling (1 s), northbound REST | P1.2 ✅ |
| `apps/ryu_logic.py` | VM + Mac (pure Python 3.8) | REST body validation, flow cookies, rate maths (100% branch coverage) | P1.2 ✅ |
| `executor/` | Mac, Python 3.11 | Applies **verified** actions only, watches KPIs, rolls back, rate-limits, writes the audit log | P4.4 |

## REST API (`http://<vm>:8080`)

| Method | Path | Body / result |
|---|---|---|
| GET | `/stats/ports` | `{"ports": [{ts, dpid, port, rx_bytes, tx_bytes, rx_pkts, tx_pkts, rx_dropped, tx_dropped, rx_bps, tx_bps}]}` |
| GET | `/stats/flows` | `{"flows": [{ts, dpid, flow_id, ours, priority, match, bytes, pkts, duration_s, bps}]}` |
| GET | `/topology` | `{"switches": [{dpid, ports: [{port_no, name, hw_addr}]}], "hosts": [{mac, dpid, port}]}` |
| POST | `/flows` | `{flow_id, dpid, priority?, match: {in_port, eth_src, eth_dst, eth_type, ipv4_src, ipv4_dst, ip_proto}, actions: [{output: N|"normal"|"controller"} \| {queue: 0-2} \| {drop: true}], idle_timeout?, hard_timeout?}` → 201 `{installed, cookie}` |
| POST | `/qos/queue` | `{flow_id, dpid, match, queue_id, out_port}` → 201 |
| DELETE | `/flows/{flow_id}` | → 200 `{deleted}` |

Errors: 400 invalid body (message explains the field), 404 unknown dpid/flow_id, 409 flow_id already installed. Our flows use priority ≥ 100 and a tagged cookie, so they override learned L2 flows (priority 1) and are deletable by `flow_id`.

Run: `make controller-vm` (19 end-to-end checks on the campus). Records omit `scenario_id`/`run_id`; the collector (P2.1) adds them and validates against `common/schemas.py` (see `tests/contract/test_controller_fixtures.py`).

- `executor/` must keep 100% branch coverage on its safety paths (RULEBOOK T-2, T-5).
- Must not import `ml`, `genai`, `api`, `testbed` or `telemetry` (import-linter contract).
