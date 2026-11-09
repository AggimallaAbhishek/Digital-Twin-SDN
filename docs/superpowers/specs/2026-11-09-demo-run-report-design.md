# Demo run report — design (2026-11-09)

Approved in chat by Abhishek on 2026-11-09 (format HTML, grounded AI summary, all four
sections, built automatically and on demand).

## Goal

When the 10-minute `make demo` scenario ends, write a report of what happened in that run and
open it in the browser; `make demo-report [DEMO_RUN=<stamp>]` rebuilds it.

## Output

`data/raw/demo/<stamp>/report.html`: one self-contained page (no scripts, no external files
apart from the theme's Google Fonts, which fall back to system fonts), in the dashboard's
Blueprint + Sorbet look; prints to PDF from the browser. Next to it, `report.json`: the facts
the page was built from, so a rebuild works after the next demo has archived the ledger and
the API has stopped.

## Sections

1. **Header**: scenario, seed, run id, start and end (UTC; the end is the scenario's
   "finished" event), git commit, PASS/FAIL (the collector's checks *and* the scenario's exit),
   data-quality numbers (records, max lag, max gap).
2. **AI summary** (labelled, with the model): headline, what happened (2–5 points), an
   assessment of the control loop's actions, caveats. Written by the copilot's LLM
   (`LLMClient.complete_json`, prompt `genai/prompts/demo_report_v1.md`) from the facts JSON
   only (missing sources by name, not their errors). No model, or an invalid reply → "AI summary unavailable"; the report still builds.
3. **Key numbers**: throughput, latency p50/p95 and loss per class: `summary.json`, or, when
   the scenario did not exit cleanly (it may have left an earlier run's file), computed from the
   run's own InfluxDB `kpi` rows with the VM's formula (`testbed/scenario_plan.py summarize_kpis`).
4. **Timeline** (mm:ss from the scenario start): the scenario's events (grouped: arrivals and
   interference caps and rejoins within 10 s of the first become one line), the alerts (per
   entity, each within 30 s of the one before)
   and the actions, in one list.
5. **Control-loop actions**: each action — what (type and parameters), why (its reason), the
   twin's verdict (accepted, predicted vs baseline), its status (kept / rolled back /
   rejected / …) with the executor's note, and the measured KPIs.
6. **Charts** (inline SVG, 10 s bins): per-AP channel utilisation and clients; latency and
   loss per traffic class; actions and alerts marked. Native SVG tooltips, line-end labels and a
   data table under each chart (palettes validated with the dataviz validator; the AP palette
   warns on contrast, so labels and tables are required).

## Sources

The run window is the scenario's start ("started" event, else the manifest) to its planned end
plus 30 s (`TAIL_S`): the loop's last action and alert belong to it. Files and replies are
parsed into models at the boundary (`Manifest`, `Collector`, `Alert`); a start time without a
timezone is refused.

| Fact | Source | When missing |
|---|---|---|
| manifest, outcome, per-class numbers, scenario events | the run folder (`manifest.json`, `collector.json`, `summary.json`, `events.jsonl`) | section says "not available" |
| actions | the action ledger (`logs/actions.db`, read-only), `created_at` inside the run window | "no ledger" |
| alerts | the API `GET /alerts` (kept in the API's memory only), inside the run window | "API not reachable" |
| time series | InfluxDB `ap_stats` and `kpi` of the run id, in the run window | charts left out, with a note |

## Components

`experiments/demo_report.py`:
- `collect(run_dir, sources) -> facts` (a JSON dict; all I/O behind `Sources`, faked in tests)
- `summarise(facts, llm) -> summary | None` (the model gets the facts with each chart line's peak
  instead of every point)
- `render(facts, summary) -> str` (every value HTML-escaped)
- `build(run_dir, ...) -> Path` (reload `report.json` if every source was read, else collect
  again; summarise if there was no summary; render; write)
- `main()`: `--run <stamp>` (default the newest `data/raw/demo/*`), `--refresh`, `--no-open`.

`experiments/demo.py` calls `build` after `play()`; a failure is logged and never fails the demo.

## Fixed along the way

Every demo uses run id `live`, so the VM appended each run's `events.jsonl` and `kpi.jsonl` to
the same `~/p02/runs/live/` since Oct 10; a killed run's partial line made the summary crash
(scenario exit 1) and the demo copied back a `summary.json` from Oct 16. A run now clears its
folder's outputs first (`testbed/scenario_plan.py clear_run_outputs`).

## Safety

The LLM only reads the facts and writes text; it calls no tool, the controller or the AP agent.

## Tests

Fixture run folders, a temporary SQLite ledger, fake API / InfluxDB / LLM: sections and numbers,
escaping, the grouping of events, a missing source, a failing LLM, the newest-run lookup,
the demo hook never raising, the run-folder reset.
