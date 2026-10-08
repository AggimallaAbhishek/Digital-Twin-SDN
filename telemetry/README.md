# telemetry

Collector (polls the controller REST and AP agent every second and writes straight to InfluxDB; MQTT is optional per PHASE_PLAN and not used), the Grafana dashboard, and service config (Phase 2).

| Path | Purpose |
|---|---|
| `mosquitto/mosquitto.conf` | Local broker config. Anonymous access, localhost only. **Switch to password auth before the VM connects (P2.1).** |
| `grafana/provisioning/` | InfluxDB (Flux) data source + dashboard provider, loaded automatically |
| `grafana/dashboards/raw_kpis.json` | P2.2 "Raw KPIs" dashboard (provisioned, uid `raw-kpis`) |
| `collector/` | P2.1 collector: `records.py` (validation + line protocol), `collector.py` (poll loop, InfluxDB writer, health) |

MQTT topics and InfluxDB measurements are defined in PROJECT_PLAN §7.1. May import only `common`.

## Collector (P2.1)

```bash
make up                                                      # InfluxDB + Grafana
make collect SCENARIO_ID=lecture_flash_crowd RUN_ID=flash-1  # Ctrl-C to stop, or DURATION_S=600
```

- **Sources** (`config/telemetry.yaml`, VM `192.168.64.2`):
  - Ryu `/stats/ports` → `port_stats`, `/stats/flows` → `flow_stats`;
  - AP agent `/aps/{ap}/stats` → `ap_stats`, `/stations` → `sta_stats`, `/kpi` → `kpi`.

  Every period (1 s) all sources are polled in parallel, and the valid records go to InfluxDB in one write.
- **Validation** happens on arrival against `common/schemas.py`. An invalid record is logged with its reason and dropped. For example, a disabled AP reports `channel: null`, which `APStats` rejects.
- **No duplicates:** `/kpi` returns each flow's *latest* record on every poll. The collector writes only records newer than the last one it wrote for the same series.
- **Tags:** every line carries `scenario_id` and `run_id` (from the command line) plus the PROJECT_PLAN §7.1 tags.
- **When a source counts as polled:** only once its data is stored, so a failed InfluxDB write counts as a gap for every source in that poll, and so does the time after the last success when the run ends. A malformed `/aps` reply fails the `ap_stats` source only.
- **Health** is checked against the P2.1 *Done when*:
  - lag = write time − record `ts`, must stay under 2 s;
  - gap = time between successful polls of a source, must stay under 5 s.

  The result is printed as `COLLECTOR_RESULT …` and saved to `logs/collector/<run_id>.json`. Records the VM produced before the collector started (the probe's latest KPI records, say) are written but don't count as lag (`backlog_records`). The JSON also gives the worst lag per measurement (`max_lag_by_measurement`), and a poll that takes longer than its period is logged as a warning, so a lag problem can be traced to its source.
- **Secrets:** the InfluxDB URL, org and token come from `.env`, which `make collect` sources. The token is never logged or printed.

## Dashboard (P2.2)

Grafana → *Digital Twin SDN / Raw KPIs (P2.2)*. Pick the run in the **Run** drop-down (values of the `run_id` tag).

| Row | Panels |
|---|---|
| **Access points** | AP downlink throughput (dashed line: 4.6 Mbit/s capacity) · AP utilisation as % of current capacity (dashed line: 80% congestion limit) · clients per AP · channel per AP |
| **Traffic KPIs by class** | mean flow throughput · p95 latency · packet loss |
| **Wired links** | utilisation of the s1 → s2 core link (% of 100 Mbit/s) · utilisation of srv1's link (% of 1 Gbit/s) |
| **Flows** | table of every flow's latest KPIs: class, throughput, latency (RTT), jitter, loss |

**Colours** follow the entity and never change between panels:
- APs: ap1 blue, ap2 orange, ap3 aqua, ap4 yellow.
- Traffic classes: video magenta, web green, bulk violet.

Both sets were checked with the dataviz palette validator on Grafana's light and dark surfaces. Legends show the last and max values, so colour is never the only cue.
