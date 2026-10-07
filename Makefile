# Developer commands (RULEBOOK §19.6). Run `make help` for the list.
.DEFAULT_GOAL := help
RUN := uv run
FAST_TESTS := -m "not vm and not llm and not integration"

.PHONY: help setup env hooks fmt lint types imports test test-all check security up down ps logs sync-vm smoke-vm campus-vm controller-vm llm-check llm-client-check

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

setup: ## Install Python 3.11 env + dev tools (uv), create .env, install git hooks
	uv sync
	@$(MAKE) --no-print-directory env hooks

env: ## Create .env with generated local secrets (never overwrites)
	@./scripts/init_env.sh

hooks: ## Install pre-commit git hooks (runs checks on every commit)
	$(RUN) pre-commit install

fmt: ## Auto-fix lint + format
	$(RUN) ruff check --fix .
	$(RUN) ruff format .

lint: ## Lint + format check (no changes)
	$(RUN) ruff check .
	$(RUN) ruff format --check .

types: ## Type-check
	$(RUN) mypy .

imports: ## Check module boundaries (RULEBOOK §4)
	$(RUN) lint-imports

test: ## Fast tests with coverage (no VM, LLM or services)
	$(RUN) pytest $(FAST_TESTS) --cov

test-all: ## All tests except VM and LLM (needs `make up`)
	$(RUN) pytest -m "not vm and not llm" --cov

check: lint types imports test ## Everything that must pass before you push

security: ## Static security scan + dependency audit
	$(RUN) bandit -q -r common twin ml genai api telemetry controller -ll
	$(RUN) pip-audit --skip-editable

up: ## Start Mosquitto, InfluxDB, Grafana and wait until healthy
	docker compose up -d --wait

down: ## Stop services (data volumes are kept)
	docker compose down

ps: ## Service status
	docker compose ps

logs: ## Follow service logs
	docker compose logs -f --tail=50

sync-vm: ## Copy testbed/, controller/ and config/ to the VM (~/Digital-Twin-SDN)
	ssh sdnvm 'mkdir -p ~/Digital-Twin-SDN'
	ssh sdnvm 'rm -rf ~/Digital-Twin-SDN/testbed ~/Digital-Twin-SDN/controller ~/Digital-Twin-SDN/config'
	scp -qr testbed controller config sdnvm:Digital-Twin-SDN/

smoke-vm: sync-vm ## P0.2 smoke test on the VM (2 APs, 4 stations)
	ssh sdnvm '~/Digital-Twin-SDN/testbed/smoke/run_smoke.sh'

campus-vm: sync-vm ## P1.1 campus check on the VM (4 APs, 20 stations, pingall)
	ssh sdnvm '~/Digital-Twin-SDN/testbed/run_on_vm.sh campus testbed.topologies.campus_v1 --check'

controller-vm: sync-vm ## P1.2 controller check on the VM (REST, stats, flow install/delete)
	ssh sdnvm 'RYU_APP=controller.apps.twin_controller RYU_STARTUP_S=5 ~/Digital-Twin-SDN/testbed/run_on_vm.sh controller testbed.checks.controller_check'

llm-check: ## P0.7: main + fallback LLM intent -> Policy check (config/llm.yaml; needs Ollama)
	$(RUN) python -m genai.eval.compare_models

llm-client-check: ## P5.1: LLM client live check (5 prompts + forced fallback; needs Ollama)
	$(RUN) pytest tests/integration/test_llm_live.py -m llm -s -p no:cacheprovider
