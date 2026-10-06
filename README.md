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
make help      # all commands
```

Grafana runs at http://localhost:3000. The admin password is the generated `GRAFANA_ADMIN_PASSWORD` in your local `.env`.

Testbed smoke test (needs the VM from `docs/setup.md`):

```bash
make smoke-vm  # expected: SMOKE_RESULT assoc=4/4 loss=0.0% -> PASS
```

## Repository layout

```text
testbed/      Mininet-WiFi topologies, mobility, AP agent, traffic, scenario runner   (VM, py3.8)
controller/   apps/: Ryu apps (VM, py3.8) · executor/: apply, watch, rollback (Mac)
telemetry/    collector, MQTT → InfluxDB writer, Mosquitto + Grafana config
twin/         twin state, simulators, verifier, validation, loop orchestrator
ml/           forecasting, anomaly detection, optimizer, RL, synthetic data
genai/        LLM client, tools/MCP, intent engine, RAG, copilot, RCA, scenario generator
common/       shared Pydantic schemas (frozen after P0.6), config loading, logging
api/          FastAPI backend (REST, WebSocket, SSE)
dashboard/    operator UI (P6.1)
config/       YAML config: loop period, thresholds, bounds, model selection
experiments/  scenarios, batch runner, analysis scripts, notebooks
tests/        unit, contract, replay, integration, emulation tests + fixtures
docs/         plans, rule book, setup, ADRs, runbooks
```

## Working rules (short version)

- Work only on a task ID from `PHASE_PLAN.md`. Branch names follow `<role>/<task-id>-<name>`, and PR titles contain `[Px.y]`.
- `make check` must pass. Pre-commit hooks and CI enforce it. Never weaken a check to make it pass.
- Secrets live only in `.env`, which is gitignored. `.env.example` lists the variable names.
- Nothing reaches the network without an accepted twin verdict.
