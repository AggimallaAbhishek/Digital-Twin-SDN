# Dashboard redesign: design

**Date:** 2026-10-16 · **Owner:** Abhishek (approver) · **Status:** approved 2026-10-16; implemented (see §6b for what changed on the way)
**Plan:** [2026-10-16-dashboard-redesign-plan.md](../plans/2026-10-16-dashboard-redesign-plan.md)
**Deviation:** #19 in docs/PHASE_PLAN.md: out-of-plan work after the `eval-v1` code freeze;
the evaluation is finished, so no result depends on the dashboard.

## 1. Goal

Make the live demo easy to follow and the dashboard look finished. An examiner who has never
seen it should, within a few seconds, know what is wrong, what the system is doing about it, and
what the twin predicted versus what happened.

Agreed in the session of 2026-10-16:

- **Approach:** restyle Streamlit (keep `dashboard/app.py`'s structure, the API client and every
  behaviour). No new front end.
- **Look:** style F, "soft modern": rounded white cards with soft shadows on a light blue-to-warm
  gradient, pill badges, a glow on a congested AP. Light, projector-friendly.
- **Layout:** F1 and F2 merged (mockup: `.superpowers/brainstorm/…/content/f-merged.html`).

## 2. Problems seen in the live run (2026-10-16, flash crowd, seed 44)

1. The whole page fades while Streamlit re-runs (every 5–15 s): washed out on a projector.
2. No headline: the viewer must read the map to learn that ap1 is congested.
3. Map: 30 m coverage rings spill past the floor plan; labels collide with stations; "congested"
   is a slightly darker grey than "busy".
4. The twin's story is scattered: raw statuses (`rolled_back`) in Recent actions; the twin-vs-
   measured bars are far below, wider than the screen, and repeat each action's name 3 times.
5. Alerts: the same "network looks unusual" every 5 s, each with its own button; the root-cause
   report opens far from the alert, mixes UTC and local times, shows raw tags (`bad_action`) and
   long station lists.
6. Start-up shows a developer message (`GET /topology: no telemetry yet…`).

## 3. Layout

```
┌──────────────┬───────────────────────────────────────────────────────────────┐
│ SIDEBAR      │ GENAI-DRIVEN DIGITAL TWIN · SDN WI-FI          (● live 08:22:06) │
│              │ Campus Wi-Fi twin                                               │
│ 💬 Ask the   │ ┌ status banner: ● ap1 is congested in the lecture hall (100%,  ┐ │
│   network    │ │   13 clients). The system is moving clients to ap3.          │ │
│  chat history│ └──────────────────────────────────────────────────────────────┘ │
│  + input     │ [ 1 AP congested ][ 0 without an AP ][ 1 waiting ][ ✓ last kept ] │
│              │ ┌ What is happening ─────────┐ ┌ Campus · twin view ───────────┐ │
│ 🎯 Tell the  │ │ ● waiting for you (pinned) │ │ floor plan, AP discs coloured │ │
│   network    │ │   Approve / Deny / Apply   │ │ by load, pill labels, faint   │ │
│  intent box  │ │ ● measured ✓ kept / ↺      │ │ coverage, steer arrow, legend │ │
│  + result    │ │ ● twin checked             │ │                               │ │
│              │ │ ● detected · 6 alerts      │ │                               │ │
│              │ │   └ root cause, in place   │ │                               │ │
│              │ └────────────────────────────┘ └───────────────────────────────┘ │
│              │ ┌ [Load per AP] [Traffic KPIs] [Twin vs measured] ─────────────┐ │
│              │ └──────────────────────────────────────────────────────────────┘ │
└──────────────┴───────────────────────────────────────────────────────────────┘
```

## 4. Components

All display logic is in `dashboard/views.py` as pure, unit-tested functions on the API's JSON;
`dashboard/app.py` only lays them out. The API, the control loop and the data are not changed.

### 4.1 Status banner and tiles

- `status(topology, zones, actions, alerts) -> Status(level, text)`, level one of `waiting`,
  `calm`, `attention`, `critical`. Rules, first match wins:
  1. no topology → `waiting`: "Waiting for data from the network…"
  2. an AP down → `critical`: "ap2 is down (lab)."
  3. a station without an AP → `critical`: "2 clients have no access point."
  4. a congested AP → `critical`: "ap1 is congested in the lecture hall (100%, 13 clients)."
  5. a busy AP → `attention`: "ap3 is busy in the corridor (68%, 7 clients)."
  6. otherwise `calm`: "All access points are calm · 20 clients connected."
  A second sentence says what the system is doing, if anything: a change being watched →
  "The system is moving 3 clients to ap3."; a decision waiting → "A change is waiting for you."
- `tiles(topology, actions) -> list[Tile]`: APs congested, clients without an AP, changes waiting
  for the operator, last finished change (✓ kept / ↺ rolled back / — none yet).
- Zones (lecture hall, lab, …) come from `config/campus_v1.yaml`, as today.

### 4.2 "What is happening" timeline

- `timeline(actions, alerts, limit=8) -> list[Item]`, newest first, built from fields the API
  already returns (`action.created_at`, `applied_at`, `status`, `verdict`, `measured`, alert `ts`):
  - **waiting for you** (status `verified` + needs approval, or `approved`), always pinned on top,
    with Approve then Apply, or Deny (today's two-step flow, unchanged);
  - **twin checked** at `created_at`: plain action, accepted/rejected, predicted latency/loss change;
  - **measured** at `applied_at` + watch: ✓ kept or ↺ rolled back, twin vs measured latency;
  - **detected**: alerts grouped (see 4.3), with an "Explain" button.
- `plain_action(action) -> str`: "Move 3 clients ap1 → ap3", "Move ap4 to channel 11",
  "Set ap3 power to 14 dBm", "Turn ap2 off", "Give video priority on ap1", and a readable
  fallback for any other type. `describe()` stays for tooltips and the audit-style text.
- Every string from the API that an LLM may have written is escaped before it is put in HTML
  (rule L-6, as today).

### 4.3 Alerts and root cause

- `group_alerts(alerts) -> list[AlertGroup]`: consecutive alerts on the same entity collapse into
  one item: entity, count, first and last time, highest score.
- The root-cause report opens **inside its timeline item** (session state keyed by the group).
- `rca_view(report) -> RcaView`: category words (`congestion` → "congestion", `bad_action` → "a
  recent change", `ap_down` → "an AP down", `cochannel_interference` → "co-channel
  interference", `other` → "other"); station lists shortened ("9 clients"); suggested actions via
  `plain_action` with the twin's verdict word. Times in the report body are left as the model
  wrote them, but the UI's own times are all local.

### 4.4 Campus map (Altair)

- Disc colour = load: calm `#8DB8F0`, busy `#F2B84B`, congested `#E0603A` with a soft halo
  (`#FBE3DA`), down = hollow ring. Colours are re-checked for colour-vision safety and contrast
  (the `dataviz` skill's checks) before they are fixed.
- One label per AP under its disc, on a white halo so stations never hide it:
  "ap1 · 100% · 13" with the channel in small grey ("ch1").
- Coverage rings: kept (they show co-channel overlap, the interference story) but faint, thin and
  clipped to the floor plan.
- Latest steer: a dashed arrow from the source AP to the target AP with "3 clients", while that
  change is being watched (`latest_steer(actions, aps)`).
- One legend row under the map: calm · busy · congested · down · ✕ client without an AP · steer.

### 4.5 Charts

A segmented control (persists its choice across refreshes, unlike `st.tabs`) switches between:
Load per AP (one panel per AP, congestion line), Traffic KPIs (as today), and Twin vs measured
(the latest 3 finished changes, sized to the page width, the action named once per row).

### 4.6 Sidebar

Copilot answers as chat bubbles (question, answer, tools used, suggested actions with the twin's
verdict), newest at the bottom; the intent box below, its result shown as plain actions with a
verdict badge.

### 4.7 Look and feel

- `.streamlit/config.toml` theme updated: background `#F4F6FA`, cards white, text `#1C2433`,
  primary `#2A78D6`.
- CSS: gradient page background; cards = Streamlit containers with a `key`, styled through their
  `st-key-…` class (rounded 14 px, soft shadow); pill badges; IBM Plex Sans; base font 17 px for
  the projector.
- **No fading:** CSS keeps re-running elements at full opacity (`[data-stale="true"]`).
- Friendly empty and error states: no data yet, API not reachable, a chart with no points.

## 5. What does not change

The API and its client, the operator token handling (server-side only), the two-step
approve/apply flow, refresh rates (5 s live panels, 15 s KPIs), the import-linter contracts, and
all measured data.

## 6. Testing

- Unit tests first (TDD) for every new function in `views.py`, at its public interface, with
  expected values written by hand from the API's JSON shapes.
- `app.py` is checked in a live `make demo` run in Chrome: screenshots at start-up, normal load,
  congestion, steering, and after an approval; the page must never fade.
- `make check` green; the RULEBOOK review loop (/simplify, /code-review) on the diff.

## 6b. Changed during implementation (live run of 2026-10-16, approved in the session)

- Banner rules 3 and 4 swapped: congestion is the headline even while clients have no AP, and
  the count is added ("ap1 is congested … · 1 client has no access point."). A steered client is
  unassociated for a moment, so the old order made the headline flip on every steer.
- A change the twin **rejected** shows the twin's first reason (verifier violation, without the
  action id and ADR reference) and how many more, not its predicted KPIs (all zero when it was
  rejected on its bounds).
- The waiting text is "Waiting for data from the network…": true at the start and after a run.
- Names in the code: `alert_groups` (§4.3's `group_alerts`), `waiting_steps` replaces the old
  `decision_queue`, `band()` replaces `load_band`/`BANDS`.
- Load colours fixed by the palette checks: calm `#2A78D6`, busy `#D18A00`, congested `#D03B3B`
  (the pastel blue and amber of the mockup failed the lightness and chroma checks).
- The map is sized to the floor plan (x 0–80 m, y 5–65 m), so coverage rings are clipped at its
  edge. The congested halo is `#F6D6D6`.
- `status(topology, zones, actions)`: the alerts were not needed for the banner.
- Alert episodes (§4.3): an entity's alerts form one item until a minute passes without one,
  even with other entities' alerts in between (the monitor interleaves "ap1" and "network").
- Category words: `ap_down` → "an access point down", `other` → "something else" (read better
  in "likely: …").
- Two more timeline kinds: "applied · watching 30 s" while a change is watched, and "✕ could not
  apply" (status `failed`); a denied change shows "denied by the operator" on its twin check.
- The sidebar shows the last 3 exchanges (the sidebar has no room for more; the rest stay in
  the session). The Streamlit toolbar is set to minimal (no "Deploy" button on the projector).
- Twin vs measured: fixed 240 px per KPI column, which fits the card at the runbook's window
  size; it does not stretch on wider screens.

## 7. Out of scope (parking lot)

- Alerts firing during normal load and repeating every 5 s (detection, not display).
- Video KPIs appearing late in the run (data, not display).
- `.env` lines 32–33 warning at `make demo` start (for Abhishek).
- Report §5.4 describes today's panels; whether to update its wording is Abhishek's call after
  the redesign (the report is signed off).
