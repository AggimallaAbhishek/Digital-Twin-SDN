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

## Scenarios (for P1.6)

| ID | Purpose | Timeline (10 min, seeded) | Expected stress |
|---|---|---|---|
| `normal` | training data for forecaster/anomaly | Stations stay in their zones; mixed web + video + bulk traffic to srv1 | none |
| `lecture_flash_crowd` | **evaluation** | t=120 s: 10 corridor/library stations walk to lecture_hall over 60 s; t=180 s: they start video (3 Mbps each) | ap1 airtime saturates; ap2/ap3 underused |
| `ap_failure` | **evaluation** | t=240 s: ap2 (lab) goes down; its stations must re-associate to ap1/ap4 | coverage loss, load on neighbours |
| `cochannel_interference` | **evaluation** | t=180 s: ap3 is forced to channel 1, co-channel with ap1 and ap4 | interference, retries, throughput drop |

## Zone names for intents

Intents and `Policy.scope.zone` use exactly these names: `lecture_hall`, `lab`, `corridor`, `library`. These are the names the P5.4 intent test set will use.
