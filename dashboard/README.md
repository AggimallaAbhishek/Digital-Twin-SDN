# dashboard

Operator UI (P6.1), Streamlit. It talks to the API over HTTP only (import-linter contract);
the operator token stays in the Streamlit server process.

```bash
make api          # the API (with the control loop and alerts)
make dashboard    # http://127.0.0.1:8501
make demo         # or both, plus a scenario on the VM (docs/runbooks/demo.md)
```

- `app.py`: the page. Campus map (rings in each AP's channel colour, disc = load), the
  decision queue (approve / deny / apply), alerts with root cause, recent actions, load per AP,
  twin prediction vs measured, and the copilot and intents in the sidebar.
- `views.py`: API JSON to panel rows (pure, unit-tested).
- `client.py`: the HTTP client (unit-tested).
