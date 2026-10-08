# controller

| Path | Runs on | Purpose | Task |
|---|---|---|---|
| `apps/twin_controller.py` | VM, **Python 3.8**, `~/ryu-venv` (ADR-002) | Ryu app: L2 learning, stats polling (1 s), northbound REST | P1.2 ✅ |
| `apps/ryu_logic.py` | VM + Mac (pure Python 3.8) | REST body validation, flow cookies, rate maths (100% branch coverage) | P1.2 ✅ |
| `executor/` | Mac, Python 3.11 | Applies **verified** actions only, watches KPIs, rolls back, rate-limits, writes the audit log | P4.4 ✅ |

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

**Host moves (P1.3):** when a MAC shows up on a different port than learned (a station steered or roamed to another AP), the controller forgets its location on every datapath and deletes the learned flows to and from it (cookie 0 only; REST-installed flows are kept). Otherwise return traffic keeps the stale flows alive and never reaches the new AP (docs/setup.md, Known problems #11).

Run: `make controller-vm` (19 end-to-end checks on the campus). Records omit `scenario_id`/`run_id`; the collector (P2.1) adds them and validates against `common/schemas.py` (see `tests/contract/test_controller_fixtures.py`).

- `executor/` must keep 100% branch coverage on its safety paths (RULEBOOK T-2, T-5).
- Must not import `ml`, `genai`, `api`, `testbed` or `telemetry` (import-linter contract).

## Executor (P4.4)

```python
executor = Executor(Ledger(path), AgentActuator(agent_url), InfluxKpis(conn, run_id), load_executor_config(raw))
executor.record(actions, verdicts)      # the verifier's joint verdicts
executor.approve(action_id, by="...")   # operator, when the verdict needs it
executor.apply(executor.group_of(action_id), state)   # the whole set, or nothing
executor.check()                         # every loop: keep or roll back what was watched
```

- **Refuses:** no verdict, a rejected verdict, an action already applied, part of a verified set, missing approval.
- **Rate limits (always on, N-6):** 1 high-impact action per AP per 120 s, 3 actions per 5 s loop. The config loader refuses values that would switch them off.
- **Watch and rollback:** after 30 s the live KPIs of the watch window are compared with the 30 s before. A KPI worse by > 10% **and** past its noise floor rolls the whole set back, last action first (P4.4-B). No live KPIs → roll back. A revert that fails marks the action `rollback_failed` for an operator.
- **Ledger:** SQLite (`logs/actions.db`, gitignored), one row per action plus an append-only event log of every status change (P4.4-A).
- **Actuator:** AP agent REST: steer, channel, tx power, AP admin state, QoS queue, rate limit (QoS matches resolved with the twin's `qos_flow_ids`). Reroute is refused (deviation #9).
- 100% branch coverage on every module. Live check: `uv run python -m experiments.check_rollback --run-id <run>` during a scenario.
