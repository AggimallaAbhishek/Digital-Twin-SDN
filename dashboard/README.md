# dashboard

Operator UI (P6.1), Streamlit. It talks to the API over HTTP only (import-linter contract);
the operator token stays in the Streamlit server process.

```bash
make api          # the API (with the control loop and alerts)
make dashboard    # http://127.0.0.1:8501
make demo         # or both, plus a scenario on the VM (docs/runbooks/demo.md)
```

- `app.py`: the page (redesigned for the demo, deviation #19; design:
  `docs/superpowers/specs/2026-10-16-dashboard-redesign-design.md`). From the top: a status
  banner (what is wrong and what the system is doing) and four big numbers; the "What is
  happening" timeline (changes waiting for the operator on top with Approve / Apply / Deny, the
  twin's checks, outcomes after the 30 s watch, alert episodes with the root cause opened in
  place) beside the campus map (discs coloured by load, faint coverage rings in the channel's
  colour, an arrow for the steer being watched); a chart card switching between load per AP,
  traffic KPIs and twin prediction vs measured. The copilot and intents are in the sidebar.
  The page never fades while it refreshes.
- `views.py`: API JSON to what each panel shows (pure, unit-tested): `status`, `tiles`,
  `timeline`, `alert_groups`, `rca_view`, `plain_action`, `latest_steer`, `map_layers`.
- `client.py`: the HTTP client (unit-tested).
