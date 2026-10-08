# experiments

| Path | Purpose |
|---|---|
| `scenarios/*.yaml` | Scenario definitions (PROJECT_PLAN §7.6), P1.6 / P2.4 |
| `batch_v1.yaml`, `batch.py`, `run_batch.py` | P2.3: every scenario × seed, unattended, with the collector (`make batch`, ~2 h 15 min, Mac on power with the lid open). Splits by seed: 42 → train, 43 → val, 44 → test. Output: `data/raw/<version>/<run_id>/` (manifest, events, summary, collector report) and `batch.json`. Resumable: re-running repeats only the runs that failed or during which the Mac slept |
| `analysis/` | Scripts that generate **every** reported table and figure (RULEBOOK E-6) |
| `notebooks/` | Exploration only. Outputs are stripped on commit (nbstripout) |
| `results/` | Raw results (gitignored) |
