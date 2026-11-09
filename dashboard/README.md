# dashboard

Operator UI (P6.1), Streamlit, in the "Blueprint + Sorbet" look (deviation #20; design and plan:
`docs/superpowers/specs/2026-11-09-dashboard-blueprint-sorbet-design.md`, the image in
`frontend design images/`). It talks to the API over HTTP only (import-linter contract); the
operator token stays in the Streamlit server process and never reaches the browser.

```bash
make api          # the API (with the control loop and alerts)
make dashboard    # http://127.0.0.1:8501
make demo         # or both, plus a scenario on the VM (docs/runbooks/demo.md)
```

- `app.py`: the page. A header (scenario, demo clock, live status) and six pages as pills:
  - **Overview** (the design image): the story strip, the status card and three numbers for
    the busiest AP, the campus floor plan beside the proposal card (Deny / Approve / Apply) and
    the AI copilot (one box: a question goes to the copilot, anything else to the intent
    engine; "Create and apply policy" for a twin-accepted intent), then access points, the
    event timeline and twin prediction against measured;
  - **Network map**, **Digital twin**, **AI copilot** (with alert episodes and their root
    cause), **Policies**, **History and logs**.
- `panels.py`: what the panels show (pure, unit-tested): `demo_clock`, `story_steps`,
  `hero`, `focus_ap`, `ap_rows`, `event_rows`, `proposal_view`, `map_move`, `intent_view`,
  `route`.
- `svg.py`: the floor plan and the twin bars as inline SVG (pure, unit-tested).
- `theme.py`: colour and font tokens, and the page CSS.
- `views.py`: shared view logic (pure, unit-tested): plain words for actions, safe text from
  the API (`safe_html`, `md_literal`, `rich_html`), `map_layers`, `alert_groups`, `rca_view`.
- `client.py`: the HTTP client (unit-tested).

The demo clock and the story strip follow `logs/demo/run.json`, which `make demo` writes when
the scenario starts on the VM and removes on `make demo-stop`; without it the header says "No
demo running". The story of each scenario is in `config/dashboard.yaml`.
