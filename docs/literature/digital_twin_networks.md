# Network digital twins

**Citation (IEEE):** P. Almasan, M. Ferriol-Galmés, J. Paillisse, J. Suárez-Varela, D. Perino, D. López, A. A. Pastor Perales, P. Harvey, L. Ciavaglia, L. Wong, V. Ram, S. Xiao, X. Shi, X. Cheng, A. Cabellos-Aparicio and P. Barlet-Ros, "Network Digital Twin: Context, Enabling Technologies, and Opportunities," *IEEE Communications Magazine*, vol. 60, no. 11, pp. 22–27, Nov. 2022, doi: [10.1109/MCOM.001.2200012](https://doi.org/10.1109/MCOM.001.2200012). Preprint: [arXiv:2205.14206](https://arxiv.org/abs/2205.14206).

## Summary
The paper presents the network digital twin (NDT) as a renewed form of classical network modelling tools: an accurate, data-driven model of a real network that can run in real time. It describes a general NDT architecture and argues that modern machine learning makes some of its core components practical, then discusses the opportunities an NDT opens up for network operation.

## What we reuse
- The core idea of our system: a twin that mirrors live state and answers "what if" questions before a change reaches the network (PROJECT_PLAN §3).
- The split between a live state mirror (our `TwinState`, P3.1) and a performance model that predicts KPIs for a proposed change (our analytical simulator, P3.3).

## Where we differ
- Our twin's performance model is analytical (queueing + Wi-Fi airtime with a co-channel penalty), not ML-based; a learned model is future work (decisions Q1).
- We use the twin as a **safety gate**: every action, including LLM-proposed ones, needs an accepted twin verdict before it is applied.
- Wireless campus emulated in Mininet-WiFi rather than a production network *(check full text for the paper's evaluation setting)*.
