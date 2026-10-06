# api

FastAPI backend (from P3.6): REST endpoints from PROJECT_PLAN §7.7, a WebSocket `/ws/live` and SSE `/chat`. It is the only module allowed to compose `twin`, `ml`, `genai` and `controller.executor`.

Binds to 127.0.0.1 by default. Approval and apply endpoints need `OPERATOR_TOKEN` (RULEBOOK §14).
