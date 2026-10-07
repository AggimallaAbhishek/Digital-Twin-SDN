# Real KPI probe output captured on the testbed VM (2026-10-07, P1.5, campus_v1, idle campus).

`make traffic-vm` (testbed/checks/traffic_check.py, seed 1), third of 3 passing runs, uncommitted
P1.5 working tree on top of `fe9e882`. Flows from srv1: video 3 Mbit/s to sta1 (ap1), bulk to
sta4 (ap2), web to sta9 (ap3), video 1.5 Mbit/s to sta16 (ap4), for 30 s.

- `kpi_records.jsonl`: every record the probe wrote (`<LOG_DIR>/kpi.jsonl`), one per flow per window.
- `kpi_response.json`: the AP agent's `GET /kpi` response at the end of the run.

Used by tests/contract/test_traffic_fixtures.py.
