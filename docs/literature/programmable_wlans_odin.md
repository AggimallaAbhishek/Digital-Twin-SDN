# Programmable WLANs and load balancing (Odin)

**Citation (IEEE):** L. Suresh, J. Schulz-Zander, R. Merz, A. Feldmann and T. Vazão, "Towards Programmable Enterprise WLANs with Odin," in *Proc. 1st Workshop on Hot Topics in Software Defined Networks (HotSDN '12)*, Helsinki, Finland, 2012, pp. 115–120, doi: [10.1145/2342441.2342465](https://doi.org/10.1145/2342441.2342465). Code: [github.com/lalithsuresh/odin](https://github.com/lalithsuresh/odin).

## Summary
Odin is an SDN framework that makes enterprise WLANs programmable, so services such as mobility management, interference management and load balancing can be written as applications on a central controller. Its key difficulty is that in Wi-Fi the *client*, not the infrastructure, decides which AP to associate with, and the association state machine plus the broadcast medium create a lot of per-client state. Odin solves this with a light virtual AP (LVAP) abstraction per client, needs no client-side changes, and supports WPA2 Enterprise.

## What we reuse
- The problem framing our flash-crowd and AP-failure scenarios rely on: clients are "sticky" and do not rebalance on their own, so load balancing needs infrastructure-driven steering (our `steer_clients` action and the P1.4/P1.6 finding that emulated stations never roam).
- Load balancing and interference management as controller applications rather than per-AP firmware.

## Where we differ
- We steer clients with explicit re-association (disconnect + connect to a chosen BSSID) instead of LVAPs, so a steer costs a ~4 s reconnection that the twin must account for.
- Every steering decision is checked in the twin first (state-dependent bounds: ≤ 30% of an AP's clients per action, target RSSI ≥ −75 dBm).
