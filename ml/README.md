# ml

Forecasting (`forecast/`), anomaly detection (`anomaly/`), optimizer heuristics (`optimizer/`), the RL env and agents (`rl/`), and synthetic traffic (`synthetic/`). Phases 4–5.

- Every learned model is compared against a simple baseline (RULEBOOK E-5).
- Seeds come from config. Models are saved to `models/<name>/<version>/` (gitignored, E-4).
- May import `common` and `twin` (for the RL env).

**`optimizer/heuristics.py` (P4.3):** `propose(state, config, radio)` returns candidate `Action`s for a `TwinState`. Thresholds are in `config/optimizer.yaml`.
- **Steering:** an AP at ≥ 80% of its capacity sheds up to 30% of its clients to APs below 60%. A client is only moved where its predicted signal is ≥ −75 dBm.
- **Channel:** an AP sharing its channel with nearby APs moves to the least-interfered channel.
- **No reroute:** the topology is a tree, so there are no alternative paths (deviation #9).

These are only proposals: the twin verifier (P3.4) still checks every action.

**`forecast/` (P4.1):** moving-average baseline and Holt's linear trend (`models.py`), plus 5 s resampling, rolling-origin errors and RMSE (`series.py`). It forecasts per-AP utilisation 1 and 3 minutes ahead. `experiments/analysis/forecast_eval.py` tunes on train and reports val/test into `models/forecast/v1/`.

**Result on `data/v1`, test split:** Holt does **not** beat the baseline, which is the last 10 s average. RMSE at 1 min is 0.117 for the baseline vs 0.129 for Holt; at 3 min, 0.212 vs 0.256. Holt only wins in the flash crowd, the one gradual ramp; in the other scenarios load changes in single steps.
