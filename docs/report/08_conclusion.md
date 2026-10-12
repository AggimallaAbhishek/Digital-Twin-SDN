# 8. Conclusion and Future Work

<!-- Drafted in P7.1d (due Oct 28). -->

## 8.1 Conclusion

_To be written._

## 8.2 Future work

The original design (PROJECT_PLAN, deliverables D5–D6) had four parts that the 25-day scope left out (PHASE_PLAN §3). Each now has a clear place in the system, because the twin's verdict is the one gate every proposal passes through.

- **A learned twin.** A graph neural network trained on the twin's own validation data, in the manner of RouteNet [2], could replace or check the analytical model where it is weakest: bulk TCP flows (12–21% error) and the transient while clients move. It would sit behind the same verifier interface. The analytical model would remain the fallback that can always explain its numbers.
- **A learning optimiser.** Reinforcement learning could propose moves the bounded heuristics cannot, such as a combined channel change and steer when no single steering target is left (the case that limited one flash-crowd seed, Section 7.2). The twin would act as its safety layer: an RL agent proposes, and the twin and the executor's watch decide, exactly as for the heuristics.
- **Grounded answers (RAG).** The copilot answers from live tools only. Retrieval over the runbooks, the decision log and past incidents would let it cite *why* the network is configured as it is, and what fixed a similar fault before.
- **Real hardware.** The same control plane could drive programmable access points (as in Odin [4]) instead of Mininet-WiFi [5]. The testbed layer (the AP agent and the switches) would change; the twin, the loop and the executor reach it only over REST and MQTT, so they would not. The twin would need recalibrating on the real radios, which the validation scripts (P3.5) already do from recorded runs.
- **Per-run isolation and more operators.** A run identifier per demo or experiment, and approvals from more than one operator with roles, would take the system from a single-operator laboratory towards a shared deployment (PHASE_PLAN parking lot).
