# api

FastAPI backend (P3.6): REST endpoints from PROJECT_PLAN §7.7. It is the only module allowed to compose `twin`, `ml`, `genai` and `controller.executor`. `/ws/live` and `/chat` come with P5.5/P6.

    make api      # 127.0.0.1:8000 (config/api.yaml); needs `make up` and .env

| Method | Path | Notes |
|---|---|---|
| GET | `/topology` | the twin's current state (TwinSync over InfluxDB) |
| GET | `/metrics?entity=&metric=&window=` | series of one AP (`apN`), station (`staN`) or flow (`staN-<class>`), up to 3600 s |
| POST | `/twin/simulate` | `{"actions": [...]}` → joint Verdicts, recorded in the executor's ledger; **503 until `config/sim.yaml` is on** |
| POST | `/intents` | `{"text": "..."}` → policy, actions, Verdicts (not applied); **503 until `config/intent.yaml` is on** |
| POST | `/actions/{id}/approve` | `{"by": "..."}`; needs `X-Operator-Token` |
| POST | `/actions/{id}/apply` | applies the whole verified set the action belongs to; needs `X-Operator-Token` |
| GET | `/actions?status=` | the audit log |

- Binds to 127.0.0.1. Approve and apply compare `X-Operator-Token` with `OPERATOR_TOKEN` from the environment (constant-time); with no token set they answer 503 (RULEBOOK §14).
- Errors: 422 invalid input, 409 refused by the executor (with its reason), 503 feature off.
- `create_app(services)` takes everything injected; `api/main.py` builds the live services. Tests: `tests/unit/test_api*.py`.

## Control loop (P4.5, `api/loop.py`)

Every `period_s` (5 s, `config/loop.yaml`): finish the executor's due watches, then **V1** stop; **V3** (while nothing is under watch) verify each heuristic proposal in the twin, apply accepted ones that need no approval, leave the rest to an operator; **V2** (evaluation only, ADR-005) apply every proposal anyway, verdict recorded. Rate limits and rollback always hold. Batch runs play it alongside the scenario (`loop_mode` in the batch YAML, `experiments/loop_actor.py`).
