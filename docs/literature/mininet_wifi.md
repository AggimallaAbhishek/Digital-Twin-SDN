# SDN for wireless: Mininet-WiFi

**Citation (IEEE):** R. R. Fontes, S. Afzal, S. H. B. Brito, M. A. S. Santos and C. E. Rothenberg, "Mininet-WiFi: Emulating Software-Defined Wireless Networks," in *Proc. 11th Int. Conf. on Network and Service Management (CNSM)*, Barcelona, Spain, Nov. 2015, pp. 384–389, doi: [10.1109/CNSM.2015.7367387](https://doi.org/10.1109/CNSM.2015.7367387).

## Summary
Mininet-WiFi extends the Mininet emulator with virtual Wi-Fi stations and access points while keeping Mininet's SDN/OpenFlow support and its lightweight, process-based virtualisation. It targets the lack of tools for rapid prototyping and experimental evaluation of SDN in wireless environments, and demonstrates its functionality with two IEEE 802.11 use cases. The paper received the best paper award at the 2nd Workshop on Management of SDN and NFV Systems, held with CNSM 2015.

## What we reuse
- Our whole testbed (P1.1–P1.6): 4 APs, 2 OVS switches and 20 stations emulated with Mininet-WiFi, `mac80211_hwsim` and wmediumd, controlled by Ryu over OpenFlow 1.3.
- Station positions and mobility in the emulator's radio model (our crowd mobility, P1.4).

## Where we differ / limitations we report
- Measured on our VM: each emulated AP carries ~4.6 Mbit/s regardless of the reported bitrate, and same-channel APs do not slow each other down. We therefore emulate co-channel interference explicitly with a documented capacity model (deviation #7) and state this as a limitation: radio behaviour is not real RF.
- Stations never roam on their own, so client re-association is scripted (decisions P1.4-A, P1.6 orphan rejoin).
