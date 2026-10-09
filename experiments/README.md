# experiments

| Path | Purpose |
|---|---|
| `scenarios/*.yaml` | Scenario definitions (PROJECT_PLAN §7.6), P1.6 / P2.4 |
| `batch_v1.yaml`, `batch.py`, `run_batch.py` | P2.3: every scenario × seed, unattended, with the collector (`make batch`, ~2 h 15 min, Mac on power with the lid open). Splits by seed: 42 → train, 43 → val, 44 → test. Output: `data/raw/<version>/<run_id>/` (manifest, events, summary, collector report) and `batch.json`. Resumable: re-running repeats only the runs that failed or during which the Mac slept |
| `actions_v1.yaml`, `batch_actions_v1.yaml`, `validation_actions.py`, `validation_actor.py` | P3.5: the validation batch (`make validation-batch`, ~50 min): scheduled steer, QoS, rate limit, tx power and heuristic actions, each verified by the twin and applied by the executor; logged per run (`actions.jsonl`), exported to `data/actions-v1/actions.jsonl` with scenario time |
| `batch_loop_v3.yaml`, `loop_actor.py` | P4.5: the flash crowd with the V3 loop running (`loop_mode`, `run_tag`), seeds 42–44; V1 is data/v1 |
| `analysis/twin_validation.py`, `analysis/time_to_recover.py` | P3.5 per-flow throughput MAPE (`models/twin/v1/validation.json`); P4.5 time to recover (P4.5-A) |
| `analysis/` | Scripts that generate **every** reported table and figure (RULEBOOK E-6) |
| `notebooks/` | Exploration only. Outputs are stripped on commit (nbstripout) |
| `results/` | Raw results (gitignored) |
