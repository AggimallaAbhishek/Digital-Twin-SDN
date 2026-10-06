# Runbook: Mac-side services

| Action | Command |
|---|---|
| First-time setup | `make setup` (creates `.env` with generated secrets; never overwrites an existing one) |
| Start | `make up` (waits until all services are healthy) |
| Status | `make ps` |
| Logs | `make logs` |
| Stop (keep data) | `make down` |
| Wipe all data | `docker compose down -v` (**destroys InfluxDB and Grafana data**) |

| Service | URL | Credentials |
|---|---|---|
| Grafana | http://localhost:3000 | `GRAFANA_ADMIN_USER` / `GRAFANA_ADMIN_PASSWORD` from `.env` |
| InfluxDB | http://localhost:8086 | `INFLUXDB_ADMIN_USER` / `INFLUXDB_ADMIN_PASSWORD`; API token `INFLUXDB_TOKEN` |
| MQTT | localhost:1883 | anonymous, localhost only (until P2.1) |

**Troubleshooting**
- `required variable ... run make env`: `.env` is missing. Run `make env`.
- InfluxDB credentials only apply on **first** start (init mode). If you change them in `.env` later, run `docker compose down -v` to re-initialise. This deletes data.
- Grafana data source errors: check that the `INFLUXDB_TOKEN` in `.env` matches the one used at InfluxDB's first start.
