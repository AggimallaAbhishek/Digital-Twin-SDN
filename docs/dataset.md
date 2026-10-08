# Dataset (P2.3)

Labelled telemetry for the forecaster (P4.1), the anomaly detector (P4.2) and twin validation (P3.5).

## How it is made

```bash
make up                      # InfluxDB + Grafana
make batch                   # ~2 h 15 min: every scenario × seed on the VM, with the collector
make dataset                 # data/raw/v1/ + InfluxDB -> data/v1/*.parquet
```

- **Batch** (`experiments/batch_v1.yaml`): 4 scenarios (`normal`, `lecture_flash_crowd`, `ap_failure`, `cochannel_interference`) × seeds 42, 43, 44, 10 minutes each, so 12 runs and **2 h of telemetry**. Each run starts from a clean network (`mn -c`) and a VM clock set from the Mac. The Mac must stay awake: plug it in and keep the lid open. A run during which the Mac slept is marked failed, and re-running `make batch` repeats only failed runs.
- **Split by run** (RULEBOOK E-2): seed 42 → `train`, 43 → `val`, 44 → `test`. Every scenario appears in every split, and no run is split across two.
- **Versions** (RULEBOOK E-3): `data/<version>/` is never edited; a new batch config gives a new version. `data/` is not in git.

## Files

`data/v1/` holds one Parquet file per measurement (`port_stats`, `flow_stats`, `ap_stats`, `sta_stats`, `kpi`), plus `manifest.json`: version, export time, commits, hours of telemetry, the runs with their seed and split, skipped runs, and rows per measurement and split.

Every row has these columns, followed by the measurement's tags and fields (common/schemas.py, PROJECT_PLAN §7.1):

| Column | Meaning |
|---|---|
| `ts` | UTC timestamp (ms) |
| `run_id`, `scenario_id` | e.g. `ap_failure-s43`, `ap_failure` |
| `seed`, `split` | 42/43/44, `train`/`val`/`test` |
| `t_s` | seconds since the scenario clock started |
| `phase` | `normal` before the run's disruption, `stress` from it on |
| `event` | the run's disruption: `flash_crowd` (crowd's traffic starts, t = 210 s), `ap_down` (t = 240 s), `force_channel` (t = 180 s); empty for `normal` |

Things to know when using it:

- **`channel_util`** (`ap_stats`) is traffic ÷ the AP's current capacity: 4.6 Mbit/s, or its co-channel cap (deviation #8). Utilisation of 0.8 or more means congested.
- **A disabled AP reports no `ap_stats`** (its `channel` is null, which the schema rejects), so `ap_failure` runs have no ap2 rows after t = 240 s. Its clients' `sta_stats` show them rejoining other APs.
- **Web KPIs** appear only in windows in which a fetch finished. Video and bulk have one row per flow per second.
- **Congestion shows mostly as `loss_pct`**, not latency, because the queues are `fq_codel` (docs/scenario.md).
