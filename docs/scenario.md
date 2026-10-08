# Scenario: Campus Layout v1 (P0.5)

A small **virtual** campus (decisions Q2: no real hardware). It gives the emulation coordinates, gives the scenarios places, and gives the LLM intents zone names (*"…in the lab"*). The numbers live in [`config/campus_v1.yaml`](../config/campus_v1.yaml); this page explains them. **Status:** draft for team review (freezes with P0.6 on Oct 8).

## Layout (80 m × 70 m)

```text
 y=65 ┌───────────────────────────┬───────────────────────────┐
      │ LECTURE_HALL              │ LAB                       │
      │        (ap1) ch1          │        (ap2) ch6          │
      │        20,50              │        60,50              │
 y=35 ├───────────────────────────┼───────────────────────────┤
      │ CORRIDOR                  │ LIBRARY                   │
      │        (ap3) ch11         │        (ap4) ch1          │
      │        20,20              │        60,20              │
 y=5  └───────────────────────────┴───────────────────────────┘
     x=0                        x=40                         x=80
```

| AP | Zone | Position (m) | Channel | Uplink |
|---|---|---|---|---|
| ap1 | lecture_hall | (20, 50) | 1 | s1, 100 Mbps |
| ap2 | lab | (60, 50) | 6 | s2, 100 Mbps |
| ap3 | corridor | (20, 20) | 11 | s1, 100 Mbps |
| ap4 | library | (60, 20) | 1 | s2, 100 Mbps |

**Wired core:** `s1 ── s2` (100 Mbps). The server `srv1` (10.0.1.1) sits on s1 at 1 Gbps and is the endpoint for video, web and bulk traffic. The topology is a tree with no loops.

```text
            srv1
             │ 1 Gbps
     ap1 ── s1 ── ap3
             │ 100 Mbps
     ap2 ── s2 ── ap4
```

**Stations:** 20 (`sta1`–`sta20`, 10.0.0.1–20). They start in: lecture_hall 3, lab 5, corridor 7, library 5. Positions are seeded random points inside each zone (seed 7, 3 m margin), and each station associates to its zone's AP.

## Why these numbers

- **AP spacing (40 m horizontally, 30 m vertically).** The radio model is log-distance with exponent 4, which gives about **75 m** of AP range, and RSSI ≥ −75 dBm (the client-steering bound) within about **30 m**. Neighbouring coverage overlaps, so the optimizer has real choices (steer clients, change channel) that measurably help.
- **Channels 1/6/11 with one reuse.** 2.4 GHz has 3 non-overlapping channels and we have 4 APs, so ap1 and ap4 share channel 1 on the diagonal (50 m, the farthest pair). That gives the twin's co-channel penalty something real to model.
- **100 Mbps uplinks, s1–s2 core and a 1 Gbps server.** A crowded AP or the inter-switch link can become the bottleneck, which is what the scenarios stress.

## Radio model (measured, P1.6)

Calibration on the VM (2026-10-07) showed two things the layout above does not capture:

- **Each AP carries about 4.6 Mbit/s downlink**, whatever bitrate `iw` reports. One bulk flow gets 4.56 Mbit/s, three together share 4.62, and two 3 Mbit/s videos already overload an AP (2.44 Mbit/s each, ~450 ms delay). The AP radio, not the wired links, is the bottleneck.
- **Same-channel APs do not interfere** in mac80211_hwsim + wmediumd: ap1 and ap3 both on channel 1 still get 4.6 Mbit/s each.

So the scenario runner **emulates co-channel interference explicitly** (deviation #7): while APs that are up share a channel, each one's downlink is capped with `tc` at `4.6 / (1 + Σ w)`, where a same-channel neighbour weighs 1 at ≤ 30 m, 0 at ≥ 60 m, linear in between. The cap follows the live channels, so changing a channel really removes it. The numbers live in `config/campus_v1.yaml` (`radio_model`), and the twin (P3.3) uses the same model. With the default channels, ap1 and ap4 (50 m apart, both on channel 1) are capped at 3.45 Mbit/s.

Traffic is sized to this capacity: video calls default to **1 Mbit/s** (was 3), and web is background load (50 KB fetches, ~5 s think time, ~0.08 Mbit/s per station).

## Scenarios (P1.6, `experiments/scenarios/*.yaml`)

| ID | Purpose | Timeline (10 min, seed 42) | Expected stress |
|---|---|---|---|
| `normal` | training data for forecaster/anomaly | Everyone browses; one 1 Mbit/s video call each in the lab (sta4), corridor (sta9) and library (sta16); a 0.5 Mbit/s bulk transfer on sta5 | none: busiest AP (lab, ap2) ~1.9 of 4.6 Mbit/s |
| `lecture_flash_crowd` | **evaluation** | t=120–160 s: 6 corridor + 4 library stations leave for the lecture hall (all there by ~195 s); t=210 s: everyone in the hall (13 stations) streams the lecture at 0.4 Mbit/s | ap1 at ~180% of its 3.45 Mbit/s cap; ap2/ap3 nearby with spare capacity |
| `ap_failure` | **evaluation** | 0.6 Mbit/s video calls in the lab and lecture hall from t=10 s; t=240 s: ap2 (lab) goes down. After 5 s its stations join the nearest AP still up: sta4, sta5 → ap1; sta6–8 → ap4 | ap1 at ~99% of its cap |
| `cochannel_interference` | **evaluation** | 0.4 Mbit/s video calls in the corridor and lecture hall from t=10 s; t=180 s: ap3 is forced onto channel 1, co-channel with ap1 (30 m) and ap4 (40 m) | ap3 capped at 1.72 Mbit/s for ~3.4 Mbit/s of demand (~200%) |

Measured on the VM (3 runs of `lecture_flash_crowd`, seed 42): flows reach the same mean throughput within 1% from run to run. Congestion shows mostly as **loss** (video ~49%, delivering ~0.2 of 0.4 Mbit/s), not delay: the queue under each cap is `fq_codel`, which drops packets early instead of letting a long queue build.

## Zone names for intents

Intents and `Policy.scope.zone` use exactly these names: `lecture_hall`, `lab`, `corridor`, `library`. These are the names the P5.4 intent test set will use.
