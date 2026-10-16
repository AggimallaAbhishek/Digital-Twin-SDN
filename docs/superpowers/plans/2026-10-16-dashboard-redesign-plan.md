# Dashboard redesign: execution plan

**Design:** [2026-10-16-dashboard-redesign-design.md](../specs/2026-10-16-dashboard-redesign-design.md)
**Start:** on approval · **Finish by:** Oct 22 (a week before the Oct 29 rehearsals)
**Rules:** CLAUDE.md and RULEBOOK apply: TDD for `views.py`, the review loop after the code
batch, `make check` green, no commits by Claude (Abhishek commits).

## Before starting

- **Abhishek:** commit the current state (the report work is in the working tree), so the
  redesign can be reverted in one step if the demo needs the old dashboard back.
- **Abhishek:** check `.env` lines 32–33 (the `vm-ip` warning).

## Tasks, in order

Each task ends with its tests passing; the whole batch ends with the review loop and a live run.

| # | Task | Files | Tests | Done when |
|---|---|---|---|---|
| 0 | Paperwork: deviation #19; parking-lot rows (alert noise, late video KPIs); `.superpowers/` in `.gitignore` | `docs/PHASE_PLAN.md`, `.gitignore` | — | Rows in place |
| 1 | `plain_action()`: every action type in plain words | `dashboard/views.py` | `test_dashboard_views.py`: one case per action type + fallback | Red → green |
| 2 | `group_alerts()`: consecutive alerts per entity collapsed | `views.py` | runs of 1, many, interleaved entities, empty | Red → green |
| 3 | `status()` and `tiles()`: banner level + text, the four numbers | `views.py` | each rule in order (waiting, AP down, no AP, congested, busy, calm), the "doing" sentence, tile values | Red → green |
| 4 | `timeline()`: items newest first, waiting pinned on top, limit | `views.py` | waiting/approved, twin checked (accepted, rejected), kept, rolled back, alerts grouped, ordering, limit | Red → green |
| 5 | `rca_view()`: category words, station lists shortened, suggestions in plain words | `views.py` | each category, a long station list, an error report | Red → green |
| 6 | `latest_steer()` and the map's new label text | `views.py` | steer being watched → arrow; none / finished → no arrow; label "ap1 · 100% · 13" + channel; down AP | Red → green |
| 7 | Theme and CSS: config colours, gradient, cards via keyed containers, pills, 17 px base font, **no fading** | `.streamlit/config.toml`, `dashboard/app.py` (CSS) | checked in the live run (task 11) | — |
| 8 | Page layout: header + live pill, banner, tiles, timeline (with Approve/Apply/Deny and the root cause in place) beside the map, chart switcher | `dashboard/app.py` | existing client tests stay green; live run | — |
| 9 | Map restyle: load colours (checked with the `dataviz` palette checks), halo on congested, haloed labels, faint clipped coverage, steer arrow, one legend row | `dashboard/app.py` | live run | — |
| 10 | Charts in the switcher: load per AP, traffic KPIs, twin vs measured (latest 3, fits the width) | `dashboard/app.py` | live run | — |
| 11 | **Review loop:** /simplify → /code-review (Standards + Spec against the design) → fix → `make check` | all changed files | full suite | `make check` green, findings fixed or parked |
| 12 | **Live check:** `make demo` (flash crowd), screenshots in Chrome at start-up, normal load, congestion, steering, after an approval and an intent; fix what looks wrong; `make demo-stop` | — | the design's §6 list | Every item seen working; page never fades |
| 13 | Docs: `dashboard/README.md` (panels), `docs/runbooks/demo.md` (the story's panel names: "What is happening", banner, tiles) | docs | — | Runbook matches the screen |

Tasks 1–6 are pure functions (about half the work, fully unit-tested); 7–10 are the page
(checked live). After approval they run back to back, in one batch.

## Checkpoints with Abhishek

1. **Now:** approve the design and this plan.
2. **After task 12:** screenshots of the new dashboard in Chrome; say what to change.
3. **Optional:** whether report §5.4 should describe the new panels (the report is signed off).

## Risks and how they are handled

| Risk | Handling |
|---|---|
| A Streamlit detail behaves differently live (tabs resetting, keyed-container CSS, the no-fade selector) | Segmented control instead of tabs; every style checked in the live run (task 12) before hand-off |
| The redesign breaks something before the rehearsals | Abhishek commits first, so one `git checkout` restores the old dashboard; the API is untouched, so the demo works with either |
| Too much on one screen at projector size | Test at the runbook's 90% zoom on a 1440 px wide window; drop or shrink first the chart card, never the banner or timeline |
| LLM text injected into HTML | All API strings escaped (L-6), as today; a test per new HTML-producing helper |
| Timeline times wrong (UTC vs local) | All UI times through one local-time helper; tested |

## Not in this plan

Changes to alert detection, the telemetry, the API, or the report text (see the design's
parking-lot section).
