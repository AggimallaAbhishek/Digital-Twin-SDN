# ml

Forecasting (`forecast/`), anomaly detection (`anomaly/`), optimizer heuristics (`optimizer/`), the RL env and agents (`rl/`), and synthetic traffic (`synthetic/`). Phases 4–5.

- Every learned model is compared against a simple baseline (RULEBOOK E-5).
- Seeds come from config. Models are saved to `models/<name>/<version>/` (gitignored, E-4).
- May import `common` and `twin` (for the RL env).
