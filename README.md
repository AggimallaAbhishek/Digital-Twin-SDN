# Digital-Twin-SDN

**GenAI-Driven Digital Twin for Intelligent SDN-Based Wireless Network Optimization.** A digital twin mirrors an emulated wireless SDN network (Mininet-WiFi + Ryu). ML and LLM components propose optimizations, the twin verifies each proposal, and only safe changes reach the network.

| Read | For |
|---|---|
| [`docs/PHASE_PLAN.md`](docs/PHASE_PLAN.md) | **What to work on now**: phases, task IDs, exit gates |
| [`docs/RULEBOOK.md`](docs/RULEBOOK.md) | **How to work**: coding, testing, safety and git rules |
| [`docs/PROJECT_PLAN.md`](docs/PROJECT_PLAN.md) | Design reference: architecture, schemas, evaluation |
| [`docs/setup.md`](docs/setup.md) | Building the testbed VM |
| [`docs/adr/`](docs/adr) | Architecture decision records |

## Two machines

| Where | What runs there | Python |
|---|---|---|
| **Testbed VM** (Ubuntu 20.04, `ssh sdnvm`) | Mininet-WiFi, Open vSwitch, Ryu, AP agent: `testbed/`, `controller/apps/` | 3.8 |
| **Mac / dev machine** | Twin, ML, GenAI, API, dashboard + Docker services (Mosquitto, InfluxDB, Grafana) | 3.11 |

The two sides talk only over REST and MQTT (RULEBOOK §4).

## Quick start (dev machine)

Prerequisites: [uv](https://docs.astral.sh/uv/), Docker Desktop, `make`.

```bash
make setup     # Python 3.11 env + dev tools, generates .env, installs git hooks
make up        # Mosquitto :1883, InfluxDB :8086, Grafana :3000 (localhost only)
make check     # lint + format + types + import boundaries + tests (run before every push)
make test-quick   # ~5 s inner loop while editing: no coverage, fewer property-test cases
make test-failed  # re-run only what failed last time
make help      # all commands
```

Grafana runs at http://localhost:3000. The admin password is the generated `GRAFANA_ADMIN_PASSWORD` in your local `.env`.

Testbed smoke test (needs the VM from `docs/setup.md`):

```bash
make smoke-vm  # expected: SMOKE_RESULT assoc=4/4 loss=0.0% -> PASS
```

## Live demo

```bash
make demo        # services, VM sync, API + dashboard, then the flash crowd (~12 min, lid open)
make demo-stop   # stop the API and the dashboard
```

The dashboard is at http://127.0.0.1:8501. The minute-by-minute script, talking points and a fallback for every step are in [`docs/runbooks/demo.md`](docs/runbooks/demo.md).

## Evaluation

```bash
make campaign MODE=V1   # then V2, V3: 3 scenarios x 3 seeds each (~2 h per mode, lid open)
make intent-eval        # the 30 intents, main route and local model alone (needs Ollama)
make results            # every table and figure -> experiments/results/ (no VM, no LLM)
```

`make campaign` re-runs only failed or missing runs, and keeps each failed attempt. `make results` never calls an LLM. The KPI definitions are decision P6.6-A in [`docs/decisions.md`](docs/decisions.md).

## Report

```bash
make report           # docs/report/*.md -> docs/report/build/report.docx (open in Word, accept "update fields")
make report-figures   # only after changing a diagram: re-render docs/report/figures/ (needs Node)
make report-latex     # the submitted version: an Overleaf project, docs/report/build/overleaf.zip
make report-latex-pdf # the same, compiled locally -> docs/report/build/report-latex.pdf (needs Tectonic)
```

The Markdown chapters are the source: comments made in the Word file must be carried back into them, because a rebuild doesn't keep them. A department template saved as `docs/report/template.docx` is used for the styles when present.

The LaTeX version (deviation #18) has boxed tables and framed diagrams. Its title page and preamble are in `docs/report/latex/`. Upload `overleaf.zip` with New Project → Upload Project and compile with XeLaTeX. Locally, `report-latex-pdf` needs [Tectonic](https://tectonic-typesetting.github.io) (`brew install tectonic`), which downloads its TeX packages on the first run.

## Repository layout

```text
testbed/      Mininet-WiFi topologies, mobility, AP agent, traffic, scenario runner   (VM, py3.8)
controller/   apps/: Ryu apps (VM, py3.8) · executor/: apply, watch, rollback, audit ledger (Mac)
telemetry/    collector, MQTT → InfluxDB writer, Mosquitto + Grafana config
twin/         twin state and sync, analytical simulator, verifier, validation
ml/           forecasting, anomaly detection, heuristic optimizer
genai/        LLM client, tools, intent engine, copilot, root-cause explainer, prompts, evals
common/       shared Pydantic schemas (frozen after P0.6), config loading, logging
api/          FastAPI backend, the control loop, live alerts
dashboard/    Streamlit operator UI (HTTP client of the API only)
config/       YAML config: loop period, thresholds, bounds, model selection, feature flags
experiments/  scenarios, batch runner, demo, analysis scripts, notebooks
tests/        unit, contract, replay, integration, emulation tests + fixtures
docs/         plans, rule book, decisions, setup, ADRs, runbooks, report chapters
```

## Working rules (short version)

- Work only on a task ID from `PHASE_PLAN.md`. Branch names follow `<role>/<task-id>-<name>`, and PR titles contain `[Px.y]`.
- `make check` must pass. Pre-commit hooks and CI enforce it. Never weaken a check to make it pass.
- Secrets live only in `.env`, which is gitignored. `.env.example` lists the variable names.
- Nothing reaches the network without an accepted twin verdict.
