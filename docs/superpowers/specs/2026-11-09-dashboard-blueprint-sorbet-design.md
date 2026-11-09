# Dashboard redesign: "Blueprint + Sorbet" (design + plan)

Date: 2026-11-09 · Source design: `frontend design images/Final — Blueprint + Sorbet@2x.png`
Supersedes the look of `2026-10-16-dashboard-redesign-design.md` (deviation #19). The behaviour
and safety rules stay.

## 1. Decisions (asked and answered 2026-11-09)

| Question | Decision |
|---|---|
| How to build it | **Restyle Streamlit.** Every panel becomes custom HTML/CSS plus inline SVG (map, bars). The operator token stays server-side, the API contract is unchanged, and so are the module boundaries. |
| The 6 tabs | **All six, from existing features.** Overview is the image; the other five reuse what exists, in the same style. |
| Demo clock and story steps | **`make demo` writes `logs/demo/run.json`** (scenario, start time, duration). The clock counts from it, and the steps light up from what actually happened. |
| One input for chat and intents | **Auto-route by wording.** Questions go to `/chat`, everything else to `/intents`; no extra LLM call. |

## 2. Visual system (measured from the image)

| Token | Hex | Use |
|---|---|---|
| `page` | `#26354F` + a blueprint grid of 1 px lines `#2D3C57` every 24 px | page background |
| `panel` | `#1F2D45` | header cells, map sheet |
| `rule` | `#C7CAD0` at 70% | thin header and sheet borders |
| `navy` | `#0A1F4D` | card borders (2 px), hard offset shadows (6 px 6 px 0), text on light |
| `yellow` | `#FFE066` | logo, the selected tab, "Load" tile, library zone, ap4, the "Create and apply policy" button |
| `coral` | `#FF8A73` | the step happening now, the anomaly card, the "before" bars, the ap1 chip when congested |
| `coral-zone` | `#FFC2B8` + diagonal hatch | a congested zone |
| `mint` | `#BFF5DF` (boxes `#B6EBD8`) | done steps, lab zone, ap2, twin-prediction boxes, "kept" |
| `sky` | `#A9D6FF` | "Clients" tile, corridor zone, ap3 |
| `lavender` | `#D9CCFF` | "Packet loss" tile, copilot card, "twin predicted" bars (dashed), proposal chips |
| `indigo` | `#4B3BD6` | client dots, the primary button (Approve), load bars, "measured" bars |
| `red` | `#E8432F` (text `#C0301C`) | congested AP disc, clients on it, the congested percentage |
| `green` | `#2F8157` | "twin check passed", the online dot |
| `white` | `#FFFFFF` | cards: proposal, access points, timeline, twin chart |

Shape:
- cards have a 16–18 px radius, a 2 px navy border and a **hard offset shadow `6px 6px 0
  #0A1F4D`**;
- chips and buttons have a 10–12 px radius and the same shadow at 4 px;
- upcoming steps have a dashed `#C7CAD0` outline on the page colour.

Type:
- display (titles, big numbers): **Chakra Petch 700**, the closest Google font to the image's
  chamfered grotesk;
- body: **Hanken Grotesk 400/600/700**.

Both are one token each in `dashboard/theme.py` (`DISPLAY`, `BODY`), so they are easy to swap.

## 3. Layout (Overview, the image, top to bottom)

1. **Header**: four cells in one bordered strip:
   - logo + "Campus Wi-Fi Twin" + subtitle;
   - **Scenario** (from `run.json`, else "No demo running");
   - **Demo clock** `03:40 / 10:00` (else `—`);
   - a **"● Live demo"** yellow pill + "SDN (Ryu) connected, twin in sync every 1 s". This line is
     honest:
     - green dot: the API answers and has a twin state;
     - amber: "API up, waiting for telemetry";
     - red: "API not answering".
2. **Tabs** as pills: Overview · Network map · Digital twin · AI copilot · Policies · History and
   logs (`st.pills`; the selected one is yellow with a shadow). Only the selected tab is drawn.
3. **Story strip**: six steps (§4.2). Shown only during a demo.
4. **Hero row**:
   - the **status card** (coral / yellow / mint / white by level), with an icon disc and a
     two-line text such as "Anomaly detected at 03:30" / "ap1 is congested in the lecture hall";
   - three **focus tiles** for the worst AP: Clients on apX (sky), Load on apX (yellow), Packet
     loss on apX (lavender).
5. **Main row**: the **floor plan sheet** (about 65%) | a column with the **proposal card**
   (white) over the **AI copilot card** (lavender).
6. **Bottom row**: **Access points** · **Event timeline** · **Twin prediction against measured**.

Pages are designed for 1920 px wide and stay usable down to 1280 px (columns keep their ratio;
the SVGs scale to their card).

## 4. Components and their states

### 4.1 Header status
| State | Shown |
|---|---|
| `run.json` present, not finished | Scenario title; clock `mm:ss / mm:ss` |
| finished (`now > start + duration`) | clock `10:00 / 10:00 · ended` |
| no `run.json` | "No demo running"; clock `—` |

### 4.2 Story steps (`config/dashboard.yaml`, per scenario)
Each step has a label, a planned window (seconds into the run) and a **trigger**:
- `clock`: reached when the demo clock reaches `from_s`;
- `congested`: the first congested load of any AP in the run, from the APs' load history (`GET /metrics` channel_util; `panels.congestion_onset`), or an AP congested now; anomaly alerts are not congestion (the detector also flags start-up transients). A step first seen after a later step reads as passed over ("about 3:30, done");
- `proposed`: the first action recorded in the run;
- `applied`: the first `applied_at` in the run;
- `outcome`: the first kept / rolled-back result (applied + watch).

The **latest reached step is "now"** (coral, "3:30, happening now"); earlier ones are **done**
(mint, "0:00–2:00, done"); later ones are **upcoming** (dashed, "about 3:35"). A scenario with no
story in the file shows no strip. `lecture_flash_crowd`: Normal day 0–120 · Crowd builds 120–195
· Congestion ~210 · Optimiser proposes ~215 · Apply and watch ~220–250 · Keep or roll back ~250.

### 4.3 Status card and focus tiles
- **Level** and **subject** come from the existing `status()` logic, which looks at the worst
  problem first. The headline is shorter, as in the image: "ap1 is congested in the lecture
  hall" · "ap3 is down (corridor)" · "3 clients have no access point" · "ap2 is busy in the lab"
  · "All access points are calm".
- **Eyebrow**: "Anomaly detected at 03:30" (the first alert of the current episode on that AP,
  in demo-clock time, else local time) · "Since 03:12" · "Status at 03:40".
- **Tiles** describe the **focus AP** (down, then congested, then busiest): clients, load
  (utilisation %), packet loss (mean `loss_pct` of the flows of its stations; `—` with none).
  The load shows the measured utilisation (0–100%), not the 180% demand in the mock-up, which
  the API does not report.

### 4.4 Floor plan (inline SVG, pure function `floor_plan_svg`)
- A sheet titled "Sheet 1 — Campus floor plan", legend: ● Client · ● On congested apX ·
  ✱ Proposed move · ◌ Coverage.
- Dimension lines "80 m" and "70 m" (`area_m`).
- **Zones** from `config/campus_v1.yaml`, each inset 0.8 m, rounded, with a hard shadow, filled
  with its sorbet colour (hall lavender, lab mint, corridor sky, library yellow). A zone whose AP
  is **congested** turns coral with a diagonal hatch and a radial glow; **busy** gets a yellow
  dashed inner border; **down** goes grey.
- **AP**: a disc (white, navy stroke, offset shadow; red with white text when congested; grey
  dashed when down) with its name, and a channel pill under it. The coverage ring is dashed,
  sized to its zone (true 30 m would leave every zone); the legend says "Coverage".
- **Clients** at their real positions:
  - indigo dots;
  - red dots on a congested AP;
  - **white dashed** for stations in the proposed or watched steer;
  - a red ✕ for a client without an AP.
- **Move**: a dashed navy line from the source AP to the target AP, with a navy label pill and
  yellow text: "Move 3 clients to ap3" (waiting) or "Moving 3 clients to ap3" (watched).
- Every text from the API is escaped (`html.escape`) before it goes into the SVG.

### 4.5 Proposal card
It shows the change that matters most now, in this order:

| What it shows | Content |
|---|---|
| **1. Waiting for the operator** | Source eyebrow ("Optimiser proposal" / "AI proposal" / "Operator change"), title, two mint boxes "Twin predicts latency 40 ms · down from 180 ms" and "Twin predicts loss 3.0% · down from 49.0%", buttons **Deny** + **Approve move** (or **Apply now** when approved) |
| **2. Being watched** | Mint boxes, plus "Applied at 03:40 · watching for 30 s" with a progress bar |
| **3. Latest result** (within 10 min) | "✓ Kept · measured 44 ms" (mint) or "↺ Rolled back · measured 95 ms" (coral) |
| **4. Nothing** | "No change proposed. The optimiser proposes one when an access point is congested." |

A rejected verdict shows coral boxes with the twin's first reason. **Deny** asks once inline
("Deny this change? It can't be applied afterwards.").

### 4.6 AI copilot card
- Title "AI copilot" + a status dot:
  - "Ready" (grey) before any call;
  - "Online" (green) after a successful call;
  - "Offline" (red) after a "no language model answered" error.
- The last two exchanges:
  - the operator's text: a navy bubble, right-aligned;
  - the reply: a white bubble.
- For an **intent**, the reply lists the actions in plain words, with a green "✓ Twin check
  passed: …" or a red "✕ Twin refused: …".
- **"Create and apply policy"** (yellow) appears when the intent produced twin-accepted actions
  that are still waiting. It approves each one that needs approval, then applies the set
  (`/actions/{id}/apply` applies the whole group), all through the operator token, server-side.
- One form: an input "Describe an intent or ask a question" and a navy send button.
- **Routing** (`route(text)`):
  - **ask** if the text ends with "?" or starts with why / what / how / which / who / when /
    where / is / are / does / do / did / can / could / should / will / would / explain / show / list / tell;
  - **intent** otherwise.
- A small chip on the bubble says "asked" or "intent".

### 4.7 Bottom row
- **Access points**: one row per AP:
  - a coloured chip (zone colour; coral when congested; grey when down);
  - "Lecture hall, channel 1, 13 clients";
  - a load bar: indigo, or a red hatched bar when congested;
  - the % on the right (red when congested), or "off" when down.
- **Event timeline**: up to 6 rows, newest last as in the image (chronological reading). Each row
  has a time chip coloured by kind:
  - first state: white;
  - congestion or alert: coral;
  - proposal: lavender;
  - applying: yellow;
  - kept: mint;
  - rolled back: coral.

  Then a bold title and a detail line. This reuses `timeline()` items, re-ordered and re-worded.
- **Twin prediction against measured**: for the latest change with a measurement, two SVG bar
  groups, **Latency (ms)** and **Packet loss (%)**, each with Before (coral), Twin predicted
  (lavender, dashed border) and Measured live (indigo), with value labels. Empty state: "No
  change has finished its 30 s watch yet."

### 4.8 The other tabs (same cards and tokens)
- **Network map**:
  - the floor plan, larger;
  - an AP table (channel, load, clients, tx power, shares airtime with);
  - clients without an AP;
  - the existing **load per AP** and **traffic per class** Altair charts, restyled (navy ink,
    indigo and sorbet series).
- **Digital twin**:
  - twin-vs-measured bars for the last 6 measured changes;
  - every verdict (accepted / rejected with its reasons, predicted KPIs).
- **AI copilot**:
  - the full conversation and the same input;
  - alert episodes with **Explain** and the root-cause reports (summary, causes with
    confidence, twin-checked suggestions).
- **Policies**:
  - intents sent this session, with their policy, actions and verdicts;
  - the ledger's `llm.intent` actions and their status.
- **History and logs**:
  - the full action ledger as a table (time, action, source, status, verdict, measured);
  - the alerts as a table.

## 5. Data flow

- One cached read per refresh for `/topology`, `/actions` and `/alerts`
  (`st.cache_data(ttl=3)`), shared by every panel. An `ApiError` is cached as "missing", never
  as a crash.
- The live part is an `st.fragment(run_every="5s")` around the selected tab.
- `logs/demo/run.json` is written by `experiments/demo.py` through a new optional
  `on_start(started_at)` callback in `run_batch.play`. It is called when the AP agent first
  answers, which is about 1 s before the VM's scenario clock starts (`testbed/run_scenario.py`
  starts the agent, then `t0`). It is marked finished when the run ends, and removed by
  `make demo-stop`.
- The dashboard reads `config/dashboard.yaml` (the stories) and `logs/demo/run.json`. It imports
  nothing from the project (the P6.1 contract).

## 6. What does not change

- The API, the executor, the safety model, `common/schemas.py`, and the module boundaries.
- The token never reaches the browser; every API or LLM string is escaped (`safe_html`,
  `md_literal`, `html.escape` in SVG).
- `dashboard/client.py`.

## 7. Files

| File | Change |
|---|---|
| `dashboard/theme.py` (new) | colour and font tokens, the page CSS |
| `dashboard/svg.py` (new) | `floor_plan_svg`, `twin_bars_svg`, small SVG helpers: pure, tested |
| `dashboard/panels.py` (new) and `dashboard/views.py` | new pure logic in `panels.py`: `demo_clock`, `story_steps`, `congestion_onset`, `hero`, `focus_ap`, `ap_rows`, `event_rows`, `proposal_view`, `map_move`, `route`, `intent_view`, `still_waiting`; `views.py` keeps the shared wording (steer: "Move 3 clients from ap1 to ap3") and drops the old banner, tiles and timeline |
| `dashboard/app.py` | rewritten layout: header, pills nav, the six tabs, cards, the forms and buttons |
| `config/dashboard.yaml` (new) | the story steps per scenario |
| `experiments/run_batch.py`, `experiments/demo.py` | the `on_start` callback; write, finish and remove `run.json` |
| `tests/unit/test_dashboard_panels.py` (new), `tests/unit/test_dashboard_views.py`, `tests/unit/test_dashboard_svg.py` (new), `tests/unit/test_demo.py`, `tests/unit/test_run_batch.py` | tests for all the new pure logic, the SVG (structure, escaping, states) and `run.json` |
| `docs/PHASE_PLAN.md` | deviation #20 (the change log of deviations), and the parking lot |
| `dashboard/README.md` | updated |

## 8. Plan (in order; `make check` after each step)

1. **Theme + SVG**: `theme.py` tokens and CSS; `svg.py` floor plan and twin bars, test-first
   (states: calm, busy, congested, down, waiting steer, watched steer, client without an AP,
   escaping).
2. **View logic**, test-first: `demo_clock`, `story_steps` (+ `config/dashboard.yaml`), `hero`,
   `focus_ap`, `ap_rows`, `event_rows`, `proposal_view`, `route`, `intent_view`; the wording
   change and the updated tests.
3. **Demo run file**, test-first: `on_start` in `play`, `run.json` write / finish / remove in
   `demo.py`.
4. **App**: header, nav, the Overview page exactly as the image, then the five other tabs; the
   cached reads; the copilot form and "Create and apply policy"; the Deny confirmation.
5. **Check it live**: `make demo`, screenshots at 1920 and 1280 px (headless browser or the
   user's Chrome), compare with the image, fix the differences.
6. The mandatory loop: `/simplify` → `/code-review` → `systematic-debugging` → `make check`;
   docs (decisions, README).

Out of scope (parking lot if wanted): a separate web front end, a replay scrubber, a
dark/light switch (the design is dark only), and the demand-based "180%" load.
