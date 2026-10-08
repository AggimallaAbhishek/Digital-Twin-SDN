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
