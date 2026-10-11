# Live demo runbook (P6.2)

One person runs this from a cold start. Total: about 15 minutes, of which 11 are the scenario
playing live. Every step has a fallback; if a fallback fails too, go to the backup recording (P7.3).

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
| 0 to 2 min | Normal load: everyone browses | **The map.** Until the first telemetry arrives it says "no telemetry yet"; the queue and alerts show already. Four APs, rings in each AP's channel colour; ap1 and ap4 share channel 1 but are 50 m apart, so their rings barely touch. "This is the twin's view, rebuilt from telemetry every 5 seconds." Below the map, **Traffic KPIs per class** shows throughput, latency and loss for video, web and bulk. |
| 2 to 3 min | 10 students walk into the lecture hall | ap1's client count climbs on the map. **Ask the copilot** (sidebar): *"Why is ap1 getting busy?"* It answers from live telemetry and shows which tools it called. |
| 3.5 min | Everyone in the hall starts streaming the lecture | ap1's disc turns dark (congested). An **alert** appears within ~5 s. Click **Explain this alert**: the root-cause explainer names a crowd on ap1, with the numbers. |
| 3.5 to 8 min | The V3 loop steers clients to ap3/ap2 | **Recent actions** fills with `steer_clients … kept`. "Every change was simulated in the twin first; the loop proposes nothing new while a change is being watched and watches it for 30 s." **Twin vs what happened** fills in: predicted vs measured. |
| any time | — | **Type an intent** (sidebar): *"Give video calls in the lecture hall priority."* The policy compiles to a QoS action; the twin's verdict is shown. |
| any time | A high-impact change waits | Ask the copilot *"Would moving ap4 to channel 11 help?"*. A channel change is high impact: it appears under **Waiting for you**. **Approve** it, then click **Apply now** on the same card (approving alone does not change the network), or **Deny** it: nothing high-impact applies without a person. The applied change is watched for 30 s like the loop's own. |
| 10 min | Scenario ends | Load per AP and the video latency over the last 5 minutes show the recovery. |

## Talking points

- **The twin sits between the AI and the network.** Heuristics and the LLM only *propose*; the twin verifies; the executor applies only accepted actions and rolls back regressions.
- **The LLM never touches the network.** It reads through tools and can only ask the twin; approvals need the operator token, which the model never holds.
- **Measured, not claimed:** RCA diagnosed 3 of 3 live faults; the copilot answered 5 of 5 diagnostic questions; every LLM action has its twin verdict in the audit log (6 of 6).

## Fallbacks

| Problem | Do this |
|---|---|
| `make demo` says port 8000 or 8501 is in use | Another terminal runs `make api` or `make dashboard`: stop it (Ctrl-C there), then `make demo` again. A demo left running is stopped by `make demo` itself |
| `make demo` says the API or dashboard did not start | Read `logs/demo/api.log` / `dashboard.log`, then `make demo` again |
| Map shows "no telemetry" | The scenario has not started yet (agent wait ~1 min), or the collector failed: check the `make demo` output |
| Copilot or RCA slow / "no language model answered" | Cloud model down: the local model answers instead (slower). If both fail: show the replay results (`make rca-replay` output, `models/genai/v1/`) |
| No alert after the crowd | Point at the map (ap1 dark) and the load chart; the detector's threshold is set for precision |
| Loop does nothing | `logs/demo/api.log` shows each loop tick; verdicts are in **Recent actions** / `GET /actions` |
| Internet down | Fonts fall back to system fonts; the LLM falls back to the local model; everything else is local |
| Anything else | Stop and play the backup recording (P7.3) |
