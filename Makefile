# Developer commands (RULEBOOK §19.6). Run `make help` for the list.
.DEFAULT_GOAL := help
RUN := uv run
FAST_TESTS := -m "not vm and not llm and not integration"

.PHONY: api qos-vm validation-batch help setup env hooks fmt lint types imports test test-all check security up down ps logs sync-vm smoke-vm campus-vm controller-vm vm-clock ap-agent-vm mobility-vm traffic-vm scenario-vm scenario-repro-vm collect batch dataset llm-check llm-client-check

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

sync-vm: ## Copy testbed/, controller/, config/ and the scenarios to the VM (~/Digital-Twin-SDN)
	ssh sdnvm 'mkdir -p ~/Digital-Twin-SDN/experiments'
	ssh sdnvm 'rm -rf ~/Digital-Twin-SDN/testbed ~/Digital-Twin-SDN/controller ~/Digital-Twin-SDN/config ~/Digital-Twin-SDN/experiments/scenarios'
	scp -qr testbed controller config sdnvm:Digital-Twin-SDN/
	scp -qr experiments/scenarios sdnvm:Digital-Twin-SDN/experiments/
	@$(MAKE) --no-print-directory vm-clock

vm-clock: ## Set the VM clock from the Mac (its NTP can't sync: docs/setup.md Known problems #12)
	ssh sdnvm "sudo date -u -s @$$(python3 -c 'import time; print(round(time.time(), 3))') > /dev/null"
	@python3 -c 'import subprocess,time; a=time.time(); b=float(subprocess.check_output(["ssh","sdnvm","date +%s.%N"])); c=time.time(); print(f"VM clock skew {b-(a+c)/2:+.2f} s")'

smoke-vm: sync-vm ## P0.2 smoke test on the VM (2 APs, 4 stations)
	ssh sdnvm '~/Digital-Twin-SDN/testbed/smoke/run_smoke.sh'

campus-vm: sync-vm ## P1.1 campus check on the VM (4 APs, 20 stations, pingall)
	ssh sdnvm '~/Digital-Twin-SDN/testbed/run_on_vm.sh campus testbed.topologies.campus_v1 --check'

controller-vm: sync-vm ## P1.2 controller check on the VM (REST, stats, flow install/delete)
	ssh sdnvm 'RYU_APP=controller.apps.twin_controller RYU_STARTUP_S=5 ~/Digital-Twin-SDN/testbed/run_on_vm.sh controller testbed.checks.controller_check'

ap-agent-vm: sync-vm ## P1.3 AP agent check on the VM (channel, tx power, steering, errors)
	ssh sdnvm 'RYU_APP=controller.apps.twin_controller RYU_STARTUP_S=5 ~/Digital-Twin-SDN/testbed/run_on_vm.sh ap_agent testbed.checks.ap_agent_check'

mobility-vm: sync-vm ## P1.4 crowd mobility check on the VM (10 stations walk to the lecture hall)
	ssh sdnvm 'RYU_APP=controller.apps.twin_controller RYU_STARTUP_S=5 ~/Digital-Twin-SDN/testbed/run_on_vm.sh mobility testbed.checks.mobility_check'

traffic-vm: sync-vm ## P1.5 traffic + KPI probe check on the VM (video, bulk, web flows; GET /kpi)
	ssh sdnvm 'RYU_APP=controller.apps.twin_controller RYU_STARTUP_S=5 ~/Digital-Twin-SDN/testbed/run_on_vm.sh traffic testbed.checks.traffic_check'

qos-vm: sync-vm ## P4.4a QoS check on the VM (priority queue under saturation, rate limit, reset)
	ssh sdnvm 'RYU_APP=controller.apps.twin_controller RYU_STARTUP_S=5 ~/Digital-Twin-SDN/testbed/run_on_vm.sh qos testbed.checks.qos_check'

SCENARIO ?= lecture_flash_crowd
GIT_COMMIT = $(shell git rev-parse --short HEAD)$(shell git diff --quiet HEAD -- || echo -dirty)
# caffeinate -i: the Mac must not idle-sleep during long runs (it pauses the VM; setup.md #13)
KEEP_AWAKE = $(shell command -v caffeinate >/dev/null && echo caffeinate -i)
RUN_SCENARIO = RYU_APP=controller.apps.twin_controller RYU_STARTUP_S=5 TIMEOUT_S=1200 ~/Digital-Twin-SDN/testbed/run_on_vm.sh

scenario-vm: sync-vm ## P1.6 run one scenario on the VM (SCENARIO=lecture_flash_crowd, ~11 min)
	$(KEEP_AWAKE) ssh sdnvm '$(RUN_SCENARIO) scenario-$(SCENARIO) testbed.run_scenario experiments/scenarios/$(SCENARIO).yaml --git-commit $(GIT_COMMIT)'

scenario-repro-vm: sync-vm ## P1.6 run SCENARIO 3x with its seed and compare throughput (±5%, ~35 min)
	for i in 1 2 3; do $(KEEP_AWAKE) ssh sdnvm '$(RUN_SCENARIO) repro-$(SCENARIO)-'$$i' testbed.run_scenario experiments/scenarios/$(SCENARIO).yaml --run-id repro-$(SCENARIO)-'$$i' --git-commit $(GIT_COMMIT)' || exit 1; done
	ssh sdnvm 'cd ~/Digital-Twin-SDN && python3 -B -m testbed.checks.repro_check ~/p02/runs/repro-$(SCENARIO)-1 ~/p02/runs/repro-$(SCENARIO)-2 ~/p02/runs/repro-$(SCENARIO)-3'

SCENARIO_ID ?= $(SCENARIO)
RUN_ID ?= $(SCENARIO_ID)-manual

api: ## P3.6 API on 127.0.0.1:8000 (config/api.yaml; needs `make up`, OPERATOR_TOKEN in .env for approvals)
	@set -a; . ./.env; set +a; $(RUN) uvicorn api.main:app --factory --host 127.0.0.1 --port 8000

collect: ## P2.1 collector: VM -> InfluxDB (SCENARIO_ID=, RUN_ID=, optional DURATION_S=; needs `make up`)
	@set -a; . ./.env; set +a; $(KEEP_AWAKE) $(RUN) python -m telemetry.collector.collector --scenario-id $(SCENARIO_ID) --run-id $(RUN_ID) $(if $(DURATION_S),--duration-s $(DURATION_S))

BATCH_CONFIG ?= experiments/batch_v1.yaml

batch: sync-vm ## P2.3 every scenario x seed with the collector -> data/raw/<version>/ (~2 h 15 min; needs `make up`)
	@set -a; . ./.env; set +a; $(KEEP_AWAKE) $(RUN) python -m experiments.run_batch --config $(BATCH_CONFIG)

DATASET_VERSION ?= v1

validation-batch: ## P3.5 action batch: scenarios with scheduled, twin-verified actions (~50 min, lid open)
	@set -a; . ./.env; set +a; $(KEEP_AWAKE) $(RUN) python -m experiments.run_batch --config experiments/batch_actions_v1.yaml --actions experiments/actions_v1.yaml

dataset: ## P2.3 export data/raw/$(DATASET_VERSION)/ (from `make batch`) to data/$(DATASET_VERSION)/*.parquet
	@set -a; . ./.env; set +a; $(RUN) python -m experiments.export_dataset --version $(DATASET_VERSION)

llm-check: ## P0.7: main + fallback LLM intent -> Policy check (config/llm.yaml; needs Ollama)
	$(RUN) python -m genai.eval.compare_models

llm-client-check: ## P5.1: LLM client live check (5 prompts + forced fallback; needs Ollama)
	$(RUN) pytest tests/integration/test_llm_live.py -m llm -s -p no:cacheprovider
