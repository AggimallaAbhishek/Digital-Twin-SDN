# Reproducing the paper

This guide takes you from the unpacked `Code_and_Data.zip` to every table, figure and number in the
paper. Two levels:

| Level | What it reproduces | Needs | Time |
|---|---|---|---|
| **A. From the recorded runs** (recommended) | Every table, figure and number of the paper, from the recorded evaluation shipped in the ZIP | A laptop with Python 3.11 and `uv` | about 5 minutes |
| **B. From scratch** | The recorded runs themselves: the 27 evaluation runs and the intent evaluation | The Ubuntu testbed VM, Docker and Ollama | about 7 hours of testbed time |

## 0. What is in the ZIP, and what is synthetic

- `Digital-Twin-SDN/`: the whole repository (code, configuration, tests, documentation).
- `data/`: **synthetic** datasets, all produced by the Mininet-WiFi emulation. No real-network traces
  are used anywhere.
  - `data/v1`: 12 runs (4 scenarios x seeds 42, 43, 44), split by seed into train, validation and
    test; calibrates the twin and trains the forecaster and detector.
  - `data/evalv1-v1`, `evalv2-v1`, `evalv3-v1`: the evaluation campaign (V1, V2, V3), 9 runs each.
  - `data/raw/eval<mode>-v1/`: per-run events, manifests and the executor ledgers (`actions.db`).
- `models/`: the metrics files of the twin, forecaster, detector and LLM evaluations.
- `experiments/results/`: the outputs the paper reads (`results.json`, `results.md`, the intent
  evaluation's `intents*.json`).
- `final_submission/`: the paper source (`paper/`), this guide, `requirements.txt` and the revision
  reports.

No secret is included: `.env` is never packaged (`.env.example` lists the variables, all blank).

## 1. Install

Requirements: Python 3.11 (the project pins `>=3.11,<3.12`), [`uv`](https://docs.astral.sh/uv/).

```bash
unzip Code_and_Data.zip && cd Digital-Twin-SDN
uv sync                    # creates .venv from pyproject.toml + uv.lock (pinned versions)
# or, without uv:
python3.11 -m venv .venv && . .venv/bin/activate
pip install -r final_submission/requirements.txt
```

`final_submission/requirements.txt` is `uv export --no-dev --no-hashes` of the lock file. The
development tools (pytest, ruff, mypy, pypandoc) are in the `dev` group of `pyproject.toml`
(`uv sync` installs them).

Environment configuration (only Level B needs it): `make env` creates `.env` with locally generated
secrets from `.env.example`; it never overwrites an existing file and the file is git-ignored.

## 2. Level A: regenerate every result from the recorded runs

```bash
make results      # experiments/results/{results.json,results.md,figures/}  (no VM, no LLM)
make paper        # generated numbers + tables + 2 figures, then paper.pdf (needs Tectonic)
make paper-check  # exit 0 if the paper's generated files match the evaluation
make check        # lint, types, import boundaries and all unit tests (about 25 s)
```

The Make targets run through `uv run`. With the pip route, run the same commands inside the
activated environment: `python -m experiments.analysis.results` (`make results`),
`python -m experiments.paper_build` (`make paper`), `python -m experiments.paper_build --check`
(`make paper-check`) and, for the checks, `ruff check .`, `mypy .`, `lint-imports` and `pytest`.

`make results` reads `data/evalv*-v1`, `data/raw/evalv*-v1` and `models/` and rewrites
`experiments/results/`. Its tables match `results.md` in the ZIP (the `created`, `git_commit` and
the absolute dataset paths inside `results.json` differ, the numbers do not).

`make paper` writes `final_submission/paper/generated/numbers.tex` (one macro per number quoted in
the text), `table_kpis.tex`, `table_actions.tex` and `figures/fig_kpis.pdf`, `fig_recovery.pdf`,
from `results.json` and the ledgers; `main.tex` contains no hand-typed result. Without Tectonic,
use `make paper` only for the generated files, then upload `final_submission/paper/` to Overleaf
(or use `dist/Overleaf_Source.zip`) and compile there.

| In the paper | Produced by |
|---|---|
| Table II, Fig. 2, Fig. 3, H1 verdicts, fairness | `make results`, then `make paper` |
| Table III, H2 counts, failed rollbacks, twin prediction time | the executor ledgers in `data/raw/eval*-v1`, `make paper` |
| Twin accuracy (4.5%, per case) | `models/twin/v1/validation.json` (Level B: `python -m experiments.analysis.twin_validation --datasets data/v1 data/actions-v1`) |
| Anomaly detection | `models/anomaly/v1/metrics.json` (`python -m experiments.analysis.anomaly_eval`) |
| Forecasting | `models/forecast/v1/metrics.json` (`python -m experiments.analysis.forecast_eval`) |
| Intent accuracy (30/30, 21/30) | `experiments/results/intents*.json` (`make intent-eval`, needs Ollama) |
| Copilot and root-cause results | `models/genai/v1/live.json` (`make genai-batch`, then `make genai-live`) |
| Fig. 1 | TikZ in `paper/main.tex` |

### Equations and algorithm against the code

| Paper | Implementation |
|---|---|
| Eq. (1) capacity with co-channel interference | `twin/sim/analytical.py`; the testbed's identical model: `testbed/interference.py`, `config/campus_v1.yaml` (`radio_model`) |
| Eq. (2) max-min sharing in strict-priority queues, loss | `twin/sim/analytical.py` |
| Eq. (3) M/M/1/K latency | `twin/sim/analytical.py` `_mm1k_mean_number`, `config/sim.yaml` |
| Eq. (4) Jain's index | `twin/sim/analytical.py` |
| Eq. (5) time to recover | `experiments/analysis/time_to_recover.py` |
| Eq. (6) acceptance rule, bounds (S1) | `twin/verify/verifier.py` (`CHANGE_PCT`, `_kpi_rule`), `common/schemas.py` |
| (S3) approval, (S4) watch and rollback | `controller/executor/` |
| Algorithm 1 | `api/loop.py`; proposals: `ml/optimizer/heuristics.py` |
| LLM roles | `genai/intent/`, `genai/agent/`, `genai/rca/`, prompts in `genai/prompts/` |

## 3. Parameters, seeds and baselines

- **Seeds:** 42, 43, 44, in `experiments/batch_eval_v*.yaml` (`seeds:`; the batch passes each to the
  scenario with `--seed`, overriding the default `seed: 42` of the scenario file), mapped to train,
  validation and test for the calibration dataset. Also: station positions `stations.seed: 7`
  (`config/campus_v1.yaml`) and the Isolation Forest `seed: 42` (`config/anomaly.yaml`). Scenario
  files: `experiments/scenarios/*.yaml` (duration 600 s and the events).
- **Baselines:** V1 plain SDN, V2 heuristics without the twin, V3 full system. Configuration:
  `experiments/batch_eval_v1.yaml`, `batch_eval_v2.yaml`, `batch_eval_v3.yaml` (`loop_mode`),
  `config/loop.yaml` (`mode`, `evaluation`).
- **Model and loop parameters:** `config/sim.yaml` (twin), `config/optimizer.yaml` (heuristics),
  `config/executor.yaml` (watch, rollback, rate limits), `config/loop.yaml` (5 s period),
  `config/anomaly.yaml`, `config/forecast.yaml`, `config/llm.yaml` (models, temperature 0,
  at most 2 repairs), `config/campus_v1.yaml` (topology and radio model). The constants the paper
  quotes are read from these files and from the code by `experiments/paper_build.py`.
- **Testbed:** Mininet-WiFi 2.7 with Ryu 4.34 (OpenFlow 1.3) on Ubuntu 20.04 aarch64, 4 vCPU;
  versions in `docs/setup.md`.
- **Evaluation code version:** the recorded runs were made at the git tag `eval-v1` (frozen before
  the campaign). The ZIP holds the final code, which has moved on since (the testbed and the
  dashboard were refactored); a Level B re-run for an exact repeat should use
  `git checkout eval-v1` in the project's repository (this ZIP has no `.git`). Level A needs no
  such step: it recomputes from the recorded runs.

## 4. Level B: from scratch

1. Build the testbed VM: `docs/setup.md` (Mininet-WiFi, Ryu, traffic tools), then the SSH alias
   `sdnvm` for it.
2. `make up` (InfluxDB, Grafana, Mosquitto in Docker), `make sync-vm` (copies the testbed code and
   scenarios to the VM), `make vm-clock`.
3. The campaign, one variant at a time (about 2 hours each, the Mac must stay awake):

   ```bash
   make campaign MODE=V1
   make campaign MODE=V2
   make campaign MODE=V3
   ```

   Each writes `data/raw/eval<mode>-v1/` and exports `data/eval<mode>-v1/`.
4. The calibration dataset: `make batch` then `make dataset` (about 2 h 15 min), and
   `make validation-batch` for the twin's action cases.
5. LLM evaluations (Ollama running with the models of `config/llm.yaml`): `make intent-eval`,
   `make genai-batch`, `make genai-live`, `make rca-replay`.
6. Back to section 2: `make results`, `make paper`.

A re-run gives close but not identical numbers: the emulator's timing and the LLMs are not
deterministic. The seeds fix the crowd, the traffic and the scenario schedule.

## 5. Troubleshooting

- `make paper` fails with "tectonic not found": install Tectonic (`brew install tectonic`) or
  compile `final_submission/paper/` on Overleaf.
- `make results` reports a missing dataset: check that `data/evalv1-v1`, `evalv2-v1` and
  `evalv3-v1` exist next to `data/raw/`.
- Level B problems with the VM: `docs/setup.md` ("Known problems").
