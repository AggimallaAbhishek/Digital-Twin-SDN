# Developer commands (RULEBOOK §19.6). Run `make help` for the list.
.DEFAULT_GOAL := help
RUN := uv run
FAST_TESTS := -m "not vm and not llm and not integration"

.PHONY: help setup env hooks fmt lint types imports test test-all check security up down ps logs smoke-vm

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

smoke-vm: ## Copy testbed/ to the VM and run the P0.2 smoke test there
	ssh sdnvm 'mkdir -p ~/Digital-Twin-SDN'
	scp -qr testbed sdnvm:Digital-Twin-SDN/
	ssh sdnvm '~/Digital-Twin-SDN/testbed/smoke/run_smoke.sh'
