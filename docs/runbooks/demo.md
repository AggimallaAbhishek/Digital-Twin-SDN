# Live demo runbook (P6.2)

One person runs this from a cold start. Total: about 15 minutes, of which 11 are the scenario
playing live. Every step has a fallback; if a fallback fails too, show the evaluation's results instead (last row of Fallbacks).

## Before the audience arrives (10 minutes)

| Check | How | If it fails |
|---|---|---|
| Mac on power, **lid open**, sleep off for the session | System settings | A sleeping Mac stops the VM clock; the run is marked failed |
| The VM is up and idle | `ssh sdnvm uptime` | Start the VM in UTM, wait 1 minute, retry |
| Docker is running | `docker ps` | Start Docker Desktop, then `make up` |
| `.env` has `OPERATOR_TOKEN` set | open `.env` yourself (never share it on screen) | Without it the dashboard cannot approve, deny or apply |
| Cloud model answers | `make llm-check` | Fine: the copilot falls back to the local model (slower, weaker; say so) |
| Browser at http://127.0.0.1:8501, zoom 90% | | |

## Run it

```bash
make demo                      # flash crowd, seed 44; prints the dashboard URL
make demo-stop                 # afterwards: stop the API and the dashboard
```

Each `make demo` starts clean: it stops a demo left running and moves the previous action log
to `logs/demo/actions-<time>.db`, so rehearsal actions do not show in the real demo. It then
starts InfluxDB/Grafana, copies the testbed to the VM, starts the API (with the V3 control loop
and the alert monitor) and the dashboard, then plays the scenario on the VM. The dashboard
refreshes every 5 seconds. `make demo-stop` takes up to ~25 s: the API lets a loop tick finish.

## The story, minute by minute (lecture-hall flash crowd)

| Scenario time | What happens | What to show and say |
|---|---|---|
| 0 to 2 min | Normal load: everyone browses | **The banner** at the top says it in words: "All access points are calm · 20 clients connected", with four big numbers below (APs congested, clients without an AP, changes waiting for you, the last change's result). Until the first telemetry arrives it says "Waiting for data from the network…". **The map**: four APs, discs coloured by load (blue calm, amber busy, red congested), faint rings in each AP's channel colour; ap1 and ap4 share channel 1 but are 50 m apart, so their rings barely touch. "This is the twin's view, rebuilt from telemetry every 5 seconds." Under it, the chart card's **Traffic KPIs** shows throughput, latency and loss for video, web and bulk. |
| 2 to 3 min | 10 students walk into the lecture hall | ap1's client count climbs on the map. **Ask the copilot** (sidebar): *"Why is ap1 getting busy?"* It answers from live telemetry and shows which tools it called. |
| 3.5 min | Everyone in the hall starts streaming the lecture | ap1's disc turns red and glows; the banner reads "ap1 is congested in the lecture hall (100%, … clients)". In **What is happening** a "detected · ap1 looks unusual" item appears within ~5 s (repeated alerts are grouped into one, with a count). Click **Explain** on it: the root cause opens right there, naming a crowd on ap1, with the numbers. |
| 3.5 to 8 min | The V3 loop steers clients to ap3/ap2 | The banner adds "The system is moving N clients to ap3" and the map draws a dashed arrow. **What is happening** tells each change's story: "twin checked · Move 2 clients ap1 → ap3 · accepted" with the predicted latency and loss, then "applied · watching 30 s", then "after the watch · ✓ kept" (or "↺ rolled back") with twin vs measured latency. A change the twin rejected shows why. "Every change was simulated in the twin first; the loop proposes nothing new while a change is being watched and watches it for 30 s." The chart card's **Twin vs measured** shows the latest 3 changes as bars. |
| any time | — | **Type an intent** (sidebar): *"Give video calls in the lecture hall priority."* The policy compiles to a QoS action; the twin's verdict is shown. |
| any time | A high-impact change waits | Ask the copilot *"Would moving ap4 to channel 11 help?"*. A channel change is high impact: it is pinned at the top of **What is happening** as "waiting for you" (the "waiting for you" number turns blue). **Approve** it, then click **Apply now** on the same item (approving alone does not change the network), or **Deny** it: nothing high-impact applies without a person. The applied change is watched for 30 s like the loop's own. |
| 10 min | Scenario ends | The chart card's **Load per AP** and **Traffic KPIs** (last 5 minutes) show the recovery; the timeline keeps the whole story. |

## Talking points

- **The twin sits between the AI and the network.** Heuristics and the LLM only *propose*; the twin verifies; the executor applies only accepted actions and rolls back regressions.
- **The LLM never touches the network.** It reads through tools and can only ask the twin; approvals need the operator token, which the model never holds.
- **Measured, not claimed:** RCA diagnosed 3 of 3 live faults; the copilot answered 5 of 5 diagnostic questions; every LLM action has its twin verdict in the audit log (6 of 6).

## Questions examiners are likely to ask

Short, honest answers from the evaluation (27 runs, report Chapter 6). Say the weak results before you are asked; the numbers are in the report.

| Question | Answer |
|---|---|
| Does the full system recover faster than plain SDN (H1)? | **Not shown.** Plain SDN never recovered in any of its 9 runs, so every comparison is a lower bound and H1 is *inconclusive* in all three scenarios (§6.2). What we can show: in the flash crowd the loop more than doubles the affected flows' throughput (0.20 → 0.53 Mbit/s) and cuts their loss from 44% to under 10%. |
| Why did V2 (no twin) beat V3 under interference? | The fix is a channel change, which is high impact and always waits for an operator. The campaign ran unattended, so V3's accepted channel changes (8) were never approved. V2 applied 9 with nobody watching, which is the risk the gate exists to prevent. In this demo you approve it live. |
| Does the twin actually block anything (H2)? | Yes, but few. It rejected 3 of V2's 64 actions, and 2 of those then measurably hurt; in V3 its 4 rejections never reached the network. Most measured harm came from actions it *accepted*: it predicts the steady state, not the first 30 s. That is why the watch and rollback are part of the gate (§6.3). |
| What went wrong after the AP failure? | Our own bug, found in the data. The loop moved a station off ap2 shortly before ap2 failed. The watch blamed the failure on that move, and the rollback tried to move the station back onto the dead AP, which left it with no AP. The fix is known: never roll back onto an AP that is down (§7.1). This demo's scenario has no AP failure. |
| How accurate is the twin? | 4.5% throughput error over 586 held-out situations (video 4.0%), 0.09 ms per simulation, within 1.04 s of the network (§6.3). Bulk TCP is its weakest case (12–21%). |
| Can the LLM break the network? | No. Its output is schema-validated, compiled by deterministic code into bounded actions and checked in the twin; it never holds the operator token. 30 of 30 intents correct on the main model, 21 of 30 on the offline model (§6.4). |
| Why only three seeds? | Time: each run takes ~11 min of emulation. The 95% intervals are therefore wide, and we claim differences only where they do not overlap (§6.1, §7.3). |
| Is this a real network? | No, Mininet-WiFi on one machine. The comparison between variants is fair (only the controller differs), but the absolute numbers do not transfer to real radios (§7.2). |

## Fallbacks

| Problem | Do this |
|---|---|
| `make demo` says port 8000 or 8501 is in use | Another terminal runs `make api` or `make dashboard`: stop it (Ctrl-C there), then `make demo` again. A demo left running is stopped by `make demo` itself |
| `make demo` says the API or dashboard did not start | Read `logs/demo/api.log` / `dashboard.log`, then `make demo` again |
| Banner and map say "Waiting for data from the network…" | The scenario has not started yet (agent wait ~1 min), or the collector failed: check the `make demo` output |
| Copilot or RCA slow / "no language model answered" | Cloud model down: the local model answers instead (slower). If both fail: show the replay results (`make rca-replay` output, `models/genai/v1/`) |
| No alert after the crowd | Point at the map (ap1 red, the banner says it is congested) and the chart card's **Load per AP**; the detector's threshold is set for precision |
| Loop does nothing | `logs/demo/api.log` shows each loop tick; verdicts are in **What is happening** / `GET /actions` |
| Internet down | Fonts fall back to system fonts; the LLM falls back to the local model; everything else is local |
| Anything else | Stop the demo and walk through the evaluation instead: Figures 6.1–6.3 and Tables 6.1–6.5 in the report (`experiments/results/results.md`), with the twin's accuracy (§6.3) |
