# GNN performance models (RouteNet)

**Citation (IEEE):** K. Rusek, J. Suárez-Varela, P. Almasan, P. Barlet-Ros and A. Cabellos-Aparicio, "RouteNet: Leveraging Graph Neural Networks for Network Modeling and Optimization in SDN," *IEEE Journal on Selected Areas in Communications*, vol. 38, no. 10, pp. 2260–2270, Oct. 2020, doi: [10.1109/JSAC.2020.3000405](https://doi.org/10.1109/JSAC.2020.3000405). Preprint: [arXiv:1910.01508](https://arxiv.org/abs/1910.01508).

## Summary
RouteNet is a network model built on a graph neural network that learns how topology, routing and input traffic together determine per source–destination delay (mean and jitter) and loss. Because GNNs operate on graph-structured data, the model generalises to topologies, routing schemes and traffic intensities not seen in training; the paper reports a worst-case mean relative error of 15.4% on unseen scenarios. The authors also show the model used inside SDN optimisation, evaluating candidate routing configurations without running them on the network.

## What we reuse
- The role of a fast performance model inside the control loop: score candidate actions in the twin, apply only the best accepted one (our verifier, P3.4).
- The way accuracy is reported — relative error against measured KPIs on unseen scenarios — as the template for our twin validation (P3.5: throughput MAPE < 20%).

## Where we differ
- We use an analytical model instead of a GNN (scope cut, decisions Q1): no training data needed, explainable, fast enough for a 5 s loop. A RouteNet-style surrogate is listed as future work.
- RouteNet models wired paths; our bottleneck is the shared Wi-Fi medium (per-AP airtime and co-channel interference), which we add explicitly.
