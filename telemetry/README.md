# telemetry

Collector (polls the controller REST and AP agent every 1–2 s → MQTT), the MQTT → InfluxDB writer, and service config (Phase 2).

| Path | Purpose |
|---|---|
| `mosquitto/mosquitto.conf` | Local broker config. Anonymous access, localhost only. **Switch to password auth before the VM connects (P2.1).** |
| `grafana/provisioning/` | InfluxDB (Flux) data source + dashboard provider, loaded automatically |
| `grafana/dashboards/` | Dashboard JSON (P2.3) |
| `collector/`, `writer/` | P2.1, P2.2 |

MQTT topics and InfluxDB measurements are defined in PROJECT_PLAN §7.1. May import only `common`.
