# Frontend design images

Put design ideas, mock-ups and screenshots for the operator dashboard in this folder. Name them
`NN-<screen>-<variant>.png`, for example `01-overview-light.png` or `03-approval-dark.png`, so
they sort by screen.

The brief below is written to be pasted into a design tool or handed to a designer as-is. §12
has ready-made prompts.

---

# Design brief: "Campus Wi-Fi Twin", the operator dashboard

## 1. The project in one paragraph

**GenAI-Driven Digital Twin for Intelligent SDN-Based Wireless Network Optimization** is a
final-year university project: 5 people, a written report and a **live demo on a projector**.

An emulated campus Wi-Fi network (Mininet-WiFi with a Ryu SDN controller) runs **4 access
points (APs)** and **20 users** who walk between four campus zones, using **video calls, web
browsing and bulk downloads**. A **digital twin** (a software copy of the network kept in sync
from live telemetry about every second) predicts **what a change would do before it is made**.

Changes come from two places:
- an **optimiser** that spots trouble from load forecasts and anomaly detection;
- an **AI copilot** (a large language model) that turns plain-English requests into network
  policies, for example "Give video calls in the lecture hall priority".

The safety rules:
1. **Nothing reaches the network unless the twin accepts it.**
2. **Risky changes also need a human "yes".**
3. After a change is applied, the system **watches the real network for 30 seconds** and **rolls
   the change back by itself** if things got worse.

The dashboard is where all of this becomes visible.

## 2. Who looks at it

| Person | Situation | What they need |
|---|---|---|
| **Demo audience** (examiners, classmates) | Watching a projector from 3–8 m away, for about 12 minutes, most of them not network experts | The story at a glance: problem → AI proposes → twin checks → applied → it worked (or was undone) |
| **Operator** (a team member presenting) | Standing at the laptop, talking while clicking | Approve / deny / apply buttons that are easy to hit; ask the copilot a question; type an intent |
| **Examiner asking "how do you know it's safe?"** | Wants proof | Visible twin predictions next to measured results; what was refused and why |

The tone is **calm and trustworthy, like a control room, not a gaming UI**. Confident, plain
English, no jargon on the main surface.

## 3. The demo storyline the screen must carry (scenario `lecture_flash_crowd`, 10 min)

| Time | What happens in the network | What the screen should show |
|---|---|---|
| 0:00–2:00 | Normal day: 3 people in the lecture hall, 5 in the lab, 7 in the corridor, 5 in the library, all browsing the web | Green/calm banner "All access points are calm · 20 clients connected"; quiet timeline "All quiet: no change proposed and no alert yet." |
| 2:00–3:15 | A lecture starts: 6 people walk in from the corridor and 4 from the library; **13 people** end up in the lecture hall | User dots move across the map towards ap1; ap1's load climbs from calm to busy (amber) |
| 3:30 | Everyone in the hall starts streaming the lecture video | **ap1 congested** (red, about 180% of what it can carry; video loses about 49% of its packets); banner turns critical: "ap1 is congested in the lecture hall (100%, 13 clients)"; anomaly alerts appear: "ap1 looks unusual" |
| ~3:35 | The optimiser proposes "Move 3 clients ap1 → ap3"; the twin predicts the result | Timeline item "accepted · twin: latency 180 → 40 ms · loss 49.0% → 3.0%"; a dashed arrow on the map from ap1 to ap3 |
| ~3:40 | The change is applied and watched for 30 s | Banner extra: "The system is moving 3 clients to ap3."; item badge "watching 30 s" |
| ~4:10 | Watch ends: kept (or rolled back) | Item "✓ kept · latency: twin 40 ms · measured 44 ms"; the "last change" tile shows ✓ |
| any time | The operator types an intent or asks the copilot | Chat bubbles in the sidebar; the intent's actions with "twin accepted / refused" |
| any time | A high-impact change, such as a channel change | The item sits pinned at the top of the timeline with **Approve** and then **Apply** |

## 4. Campus geometry (draw the map to this)

- Campus area: **80 m wide × 70 m tall**. The origin is bottom-left; y grows upwards.
- **Four rectangular zones** in a 2 × 2 grid:

| Zone | x (m) | y (m) | Position on screen |
|---|---|---|---|
| Lecture hall | 0–40 | 35–65 | top left |
| Lab | 40–80 | 35–65 | top right |
| Corridor | 0–40 | 5–35 | bottom left |
| Library | 40–80 | 5–35 | bottom right |

- **Access points**: one in the centre of each zone. Each covers about **30 m** (a dashed ring of
  its channel colour). APs on the same channel interfere within **60 m**.

| AP | Position (m) | Zone | Channel |
|---|---|---|---|
| ap1 | (20, 50) | lecture hall | 1 |
| ap2 | (60, 50) | lab | 6 |
| ap3 | (20, 20) | corridor | 11 |
| ap4 | (60, 20) | library | 1 (shares channel 1 with ap1, on the diagonal 50 m away) |

- **Users (stations)** `sta1` … `sta20` are dots that move smoothly when they walk. A user with
  no AP is a red ✕.
- Wired network behind the APs (optional in the drawing): two switches `s1` (ap1, ap3) and `s2`
  (ap2, ap4), linked to each other, and one server `srv1`.

## 5. Layout: one screen, no page navigation

The screen is designed at **1920 × 1080** and must also work at **1440 × 900** and **1280 ×
800**. No mobile version is needed. It refreshes itself every few seconds; there is no "refresh"
button.

```
┌───────────────┬──────────────────────────────────────────────────────────────┐
│ SIDEBAR       │ HEADER: ● live · twin state 14:03:22                          │
│ (~320 px)     │ GENAI-DRIVEN DIGITAL TWIN · SDN WI-FI (eyebrow)              │
│               │ Campus Wi-Fi twin (title)                                      │
│ 💬 Ask the    ├──────────────────────────────────────────────────────────────┤
│   network     │ STATUS BANNER  ● ap1 is congested in the lecture hall (100%,  │
│  [chat]       │                 13 clients). The system is moving 3 clients…  │
│               │ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐   four big-number tiles    │
│ 🎯 Tell the   │ │  1   │ │  0   │ │  1   │ │  ✓   │                            │
│   network     │ └──────┘ └──────┘ └──────┘ └──────┘                            │
│   what you    ├─────────────────────────────┬────────────────────────────────┤
│   want        │ WHAT IS HAPPENING (timeline)│ CAMPUS · TWIN VIEW (map)        │
│  [intent box] │ waiting items pinned on top │ 4 zones, 4 APs, 20 user dots,   │
│               │ with Approve / Deny / Apply │ coverage rings, steer arrow,    │
│               │ … up to 8 items             │ legend underneath               │
│               │    (about 45% of the width) │    (about 55% of the width)     │
│               ├─────────────────────────────┴────────────────────────────────┤
│               │ CHARTS: load per AP · traffic per class · twin vs measured    │
└───────────────┴──────────────────────────────────────────────────────────────┘
```

The top of the page (header, banner, tiles, timeline and map) must fit **above the fold at
1920 × 1080**. The charts may sit below and scroll.

## 6. Components, their content and every state

### 6.1 Header
- A green **live pill**: `● live · twin state 14:03:22` (local time of the twin's latest state).
  Before any data arrives it reads `● live · waiting for data`.
- **Eyebrow** (small uppercase label): `GENAI-DRIVEN DIGITAL TWIN · SDN WI-FI`.
- **Title**: `Campus Wi-Fi twin`.
- If the API is down, show an error strip: "the API is not answering … this page reconnects by
  itself."

### 6.2 Status banner: one sentence, the worst problem first
It has four levels, each with its own colour, dot and icon:

| Level | Example headline |
|---|---|
| `waiting` | "Waiting for data from the network…" |
| `calm` | "All access points are calm · 20 clients connected." |
| `attention` | "ap2 is busy in the lab (65%, 6 clients)." |
| `critical` | "ap3 is down (corridor)." · "ap1 is congested in the lecture hall (100%, 13 clients) and 1 more AP · 2 clients have no access point." · "3 clients have no access point." |

An optional second phrase says what the system is doing: "The system is moving 3 clients to
ap3." · "The system is checking: Move ap3 to channel 6." · "A change is waiting for you."

Load bands: calm below 60%, **busy** 60–80%, **congested** 80% and above.

### 6.3 Four big-number tiles (projector-readable from 8 m)

| Tile | Value | Label | Tone |
|---|---|---|---|
| 1 | `1` | "AP congested" / "APs congested" | critical when above 0, else calm |
| 2 | `0` | "clients without an AP" | critical when above 0 |
| 3 | `1` | "waiting for you" | action (accent) when above 0 |
| 4 | `✓` / `↺` / `✕` / `—` | "last change kept" / "last change rolled back" / "last rollback failed" / "no change yet" | good / warn / critical / calm |

Before data arrives, tiles 1 and 2 show `—`.

### 6.4 "What is happening" timeline (newest first, at most 8 items)
Changes **waiting for the operator are pinned on top**. Every other item is ordered by time.
Each item has a time, a title in plain words, an optional detail line and a **badge**.

| Kind | Title example | Detail example | Badge (tone) |
|---|---|---|---|
| **waiting** (boxed, the most prominent) | "Move ap3 to channel 6" | "optimizer.heuristic · high impact · twin: latency 120 → 35 ms · loss 12.0% → 1.5%" | "waiting for you" (action) + buttons **Approve** then **Apply**, and **Deny** |
| **checked**, accepted | "Move 3 clients ap1 → ap3" | "twin: latency 180 → 40 ms · loss 49.0% → 3.0%" | "accepted" (calm) |
| **checked**, rejected | "Set ap2 power to 20 dBm" | "twin: tx power step 6 dB on ap2: more than 3 dB (+1 more reason)" | "✕ rejected" (warn) |
| **checked**, denied | "Turn ap4 off" | (prediction) | "denied by the operator" (calm) |
| **applied** | "Move 3 clients ap1 → ap3" | — | "watching 30 s" (action; could be a progress ring) |
| **outcome**, kept | same title | "latency: twin 40 ms · measured 44 ms" | "✓ kept" (good) |
| **outcome**, rolled back | same title | "latency: twin 40 ms · measured 95 ms" | "↺ rolled back" (warn) |
| **outcome**, failed | same title | — | "✕ could not apply" / "✕ rollback failed" (critical) |
| **detected** (alert episode) | "ap1 looks unusual" | — | "12 alerts" (critical) + an **Explain** button |
| **detected**, older episodes | "3 earlier alert episodes" | "ap2, network, ap3" | (calm) |

Empty state: "All quiet: no change proposed and no alert yet."

The **plain-words action titles** the design must fit:
- "Move 3 clients ap1 → ap3"
- "Move ap3 to channel 11"
- "Set ap2 power to 17 dBm"
- "Turn ap4 off" / "Turn ap4 on"
- "Give video in the lecture hall priority"
- "Move bulk traffic to the background queue"
- "Put flow sta5-video back to best effort"
- "Cap flow sta7-bulk at 1.5 Mbit/s"

Where a change came from (`source`): `optimizer.heuristic` (the optimiser), `llm.intent` (the
AI), or an operator.

Impact: **low** is applied automatically; **medium** needs approval, except steering clients;
**high** always needs approval.

### 6.5 Root-cause report (opens under an alert after "Explain")
An AI-written report, which must look clearly AI-written:
- a **summary**, for example "ap2 went down; its 6 clients moved to ap1, which is now
  overloaded.";
- **likely causes**, each with a cause in words ("an access point down", "co-channel
  interference", "congestion", "a recent change", "something else"), the entity (ap2), a
  **confidence** (90%) and its evidence ("ap2 stopped reporting; ap1 clients 3 → 8");
- **suggested fixes**, each already checked by the twin: "Move 3 clients ap1 → ap3 · twin
  accepted";
- a small "by <model name>" footer;
- a **loading state** ("The explainer is reading the network…", which takes 5–20 s) and an
  **error state** ("cannot explain this alert: the alert is too old to explain").

### 6.6 Campus map ("Campus · twin view at 14:03:22")
- The 4 zones as soft areas with labels (lecture hall, lab, corridor, library).
- **AP markers** coloured by load band, with icon and text, never colour alone:
  - calm: blue `#2A78D6`;
  - busy: amber `#D18A00`;
  - congested: red `#D03B3B` with a soft red glow `#F6D6D6`;
  - down: hollow grey ring.

  Each shows its name, load % and client count, for example "ap1 · 100% · 13".
- **Coverage rings**: 30 m dashed circles in the channel colour (ch 1 `#2F5FD0`, ch 6 `#C2701A`,
  ch 11 `#1E9E6A`). Optionally highlight the ap1–ap4 shared channel.
- **User dots**, small, animating when people walk; a red ✕ for a user without an AP.
- **Steer arrow**: a dashed accent arrow from the source AP to the target AP, labelled "3
  clients", while a steer is being watched.
- Legend under the map: `● calm ● busy ● congested ○ down ✕ client without an AP - - → clients
  being moved · rings: 30 m coverage on ch 1 / 6 / 11`.
- Waiting state: "Waiting for data from the network… The map appears once the twin has a state."

### 6.7 Charts card (last 5 minutes, live)
1. **Load per AP**: four small line charts (ap1–ap4), 0–100%, with a **red line at 80%**
   ("congested above the red line").
2. **Traffic per class**: throughput (Mbit/s), latency (ms) and loss (%), each with three lines:
   **video** `#7B4FC4`, **web** `#C23B7A`, **bulk** `#4F6B12`. Mean over 10 s.
3. **Twin prediction vs what happened**: for the latest 3 changes, for throughput, latency and
   loss, three bars each: **before** (grey `#C9D2DE`), **twin predicted** (accent `#2A78D6`),
   **measured** (ink `#1C2433`). This is the "proof" chart: make it look important.

### 6.8 Sidebar
- **"💬 Ask the network"**: a chat with the copilot. Input placeholder: "Why is video slow in the
  lecture hall?".
  - Your question is a bubble on the right.
  - The answer is an AI bubble that can contain **bold** text, and has:
    - a "used get_topology, get_metrics" line (the live data it looked at);
    - optionally "suggested: Move 3 clients ap1 → ap3 · twin accepted".
  - Loading: "The copilot is looking at the network…".
  - Error: "The copilot could not answer: no language model answered…".
- **"🎯 Tell the network what you want"**: a one-line intent box. Placeholder: "Give video
  calls in the lecture hall priority." It has a primary button, **Send intent**. Results appear
  as action bubbles with a pill, "twin accepted" (good) or "twin refused" (warn), or a readable
  error.
- Optional: a small footer with the model in use ("cloud model, with a local fallback").

## 7. Sample data for realistic mock-ups

(Illustrative values in the right range for the demo, not a recording of one run.)

- **APs**:
  - ap1: congested, 100%, 13 clients, channel 1, 14 dBm
  - ap2: calm, 35%, 4 clients, channel 6
  - ap3: calm, 20%, 2 clients, channel 11
  - ap4: calm, 15%, 1 client, channel 1
- **Flows** (one per user and app), for example:
  - `sta4-video`: 0.21 Mbit/s, 180 ms latency, 49% loss
  - `sta12-web`: 0.10 Mbit/s, 20 ms, 0%
  - `sta9-bulk`: 1.8 Mbit/s, 35 ms, 0.5%
- **Twin verdict for "Move 3 clients ap1 → ap3"**: before latency 180 ms / loss 49% /
  throughput 0.21 Mbit/s; predicted 40 ms / 3% / 0.38 Mbit/s; measured after 30 s 44 ms / 4% /
  0.36 Mbit/s; impact medium; accepted.
- **A rejected verdict**: "Set ap2 power to 20 dBm": "tx power step 6 dB on ap2: more than
  3 dB".
- **Copilot Q&A**: "Why is video slow in the lecture hall?" → "**ap1 is overloaded**: 13 clients
  share it and video loses about half its packets. ap3 next door is at 20%; moving 3 clients
  there should help." (used get_topology, get_metrics; suggested: Move 3 clients ap1 → ap3 ·
  twin accepted).

## 8. Visual system (current, a starting point that may be improved)

| Token | Value | Use |
|---|---|---|
| Ink | `#1C2433` | text, "measured" bars |
| Muted | `#5B6475` | secondary text, eyebrows |
| Line | `#E3E8F0` | borders, grid lines |
| Accent | `#2A78D6` | primary buttons, "twin predicted", calm AP, steer arrow |
| Good | green (pill `#E1F5EA` on `#1F7A4D`) | kept, accepted, live |
| Warn | amber `#D18A00` | busy, rolled back, rejected |
| Critical | red `#D03B3B` | congested, down, users without an AP |
| Background | gradient `#EEF3FB` → `#F8F6F2` (160°) | page |
| Card | white, 14 px radius, soft shadow | every panel |
| Sidebar | `#F7F9FC` | |
| Font | IBM Plex Sans (with IBM Plex Mono for ids such as `sta4-video`) | |

The status colours have been checked for colour-vision deficiency against `#F7F9FC`; keep them
paired with icons (● ○ ✕ ✓ ↺) or words.

**Type scale for a projector**: big-number tiles 48–64 px, the banner headline 22–28 px, card
titles 14–16 px uppercase eyebrows, body 15–16 px, nothing under 13 px.

## 9. Interaction and motion

- Live updates every 2–5 s, with **no flicker or layout jump**: new timeline items slide in at
  the top, numbers tween, user dots glide.
- **Approve → Apply** is a two-step action for high-impact changes. **Deny is final**: a denied
  change can never be applied afterwards, so Deny deserves a light confirmation (an inline
  "Deny this change?" or a short undo window before it is sent), and the item then reads
  "denied by the operator".
- "Watching 30 s" can show a countdown ring; when it ends the item turns into ✓ kept or
  ↺ rolled back, with a short highlight.
- A congested AP's glow can **pulse slowly**. Respect `prefers-reduced-motion`.
- Buttons are at least 40 px tall, with clear focus rings, and keyboard-reachable.

## 10. Principles the design must follow

1. **The 5-second story**: problem → what the system proposes → what the twin predicted → what
   happened.
2. **Safety is visible**: every change shows that the twin checked it; changes needing a human
   are unmistakable.
3. **Measured vs predicted vs AI-written** look different. For example: measured is solid ink;
   predicted is accent with a "twin" label; AI text is in a tinted bubble with a ✦ or "AI" mark.
4. **Never colour alone**: always add an icon, shape or word.
5. **Honest states**: waiting, empty, loading, error and API-down all designed, not left blank.
6. **Readable from the back of the room**: high contrast, large numbers, short sentences.

## 11. Constraints

- It must be buildable in **Streamlit** (Python, custom HTML/CSS cards, Altair/Vega-Lite charts),
  **or** as a small separate web front end (React or plain HTML) over the same REST API:
  - `GET /topology`, `/metrics?entity=&metric=&window=`, `/alerts?since=`, `/actions`
  - `POST /chat`, `/intents`, `/twin/simulate`, `/alerts/explain`
  - `POST /actions/{id}/approve | deny | apply`
- The operator token never reaches the browser, so approve, deny and apply go through the server.
- All AI text is shown as text, never as HTML (prompt-injection safety).
- No login screen, settings page or multi-page navigation: one live screen.

## 12. What to ask the designer or tool for

**Screens (each in light and in a dark "control-room" theme):**
1. `01-overview-calm`: the normal day; all calm, quiet timeline, users spread out.
2. `02-overview-congested`: the flash crowd; ap1 red, banner critical, alerts, a proposed steer.
3. `03-approval`: a high-impact change pinned with Approve / Deny / Apply, prediction shown.
4. `04-watching-and-kept`: the steer arrow on the map, the 30 s countdown, then "✓ kept" with
   twin vs measured.
5. `05-rolled-back`: the same, but "↺ rolled back", where the prediction was wrong.
6. `06-root-cause`: an alert expanded into the AI report (causes, confidence, suggestions).
7. `07-copilot-and-intent`: a sidebar conversation and an intent with its twin verdict.
8. `08-waiting-and-errors`: no data yet, the API down, and the copilot unavailable.
9. `09-proof-chart`: a hero version of "twin predicted vs measured".

**Prompt for an image/UI generator (paste as-is):**

> High-fidelity desktop dashboard UI, 1920×1080, titled "Campus Wi-Fi twin": a live control
> room for an AI-managed campus Wi-Fi network with a digital twin. Left sidebar (~320 px) with a
> copilot chat "Ask the network" and an input "Tell the network what you want". The main area
> has:
> - a header with a green "● live" pill;
> - a large status banner "ap1 is congested in the lecture hall (100%, 13 clients) · The system
>   is moving 3 clients to ap3";
> - four big-number tiles (1 AP congested, 0 clients without an AP, 1 waiting for you,
>   ✓ last change kept);
> - two columns below: on the left a "What is happening" timeline with a pinned card "Move ap3
>   to channel 6 · high impact · twin: latency 120 → 35 ms" with Approve / Deny / Apply buttons,
>   then items "✓ kept" and "ap1 looks unusual · Explain"; on the right a 2×2 campus floor-plan
>   map (lecture hall, lab, corridor, library), one access point per zone with dashed coverage
>   rings, ap1 glowing red with a crowd of user dots, a dashed arrow from ap1 to ap3 labelled
>   "3 clients";
> - at the bottom, charts of load per AP with a red 80% line, and a "twin predicted vs measured"
>   bar chart.
>
> Style: calm, trustworthy, IBM Plex Sans, white cards with 14 px radius on a soft blue-to-warm
> gradient, accent #2A78D6, status amber #D18A00 and red #D03B3B, icons next to every colour,
> large projector-readable numbers, plenty of whitespace, no clutter.

**Dark-theme variant:** add "dark control-room theme, deep navy background #0E1726, cards
#16213A, the same accent and status colours brightened for contrast".

## 13. Ideas the team would love to see explored

- The map as a **floor plan** (walls, doors, seats in the lecture hall) or as a **load heat-map**.
- A **"before → twin → after" strip** per change, like a mini scoreboard.
- The **approval queue** as a distinct "needs you" lane, so it can't be missed.
- A **replay / scrubber** to step back through the last 10 minutes of the demo.
- A compact "system thinking" line that narrates each step in one sentence.
