# 8. Conclusion and Future Work

<!-- Drafted in P7.1d (due Oct 28). -->

## 8.1 Conclusion

<!-- Written 2026-10-12 from Chapters 6 and 7. The H3 numbers are P5.4's; update them if `make intent-eval` at eval-v1 differs. -->

This project built a digital twin of an emulated campus Wi-Fi network and made it the gate that every automated change must pass. The research question asked whether verifying actions in the twin makes an AI-driven SDN controller both more effective and safer, and whether a language model can drive it safely from natural language.

**Effectiveness (H1) was not shown.** Plain SDN never recovered in any of its nine runs, so every comparison of recovery times is a lower bound, and the H1 verdict is inconclusive in all three scenarios. The controlled system clearly helped where congestion comes from load that can be spread. In the lecture flash crowd it more than doubled the affected flows' throughput and cut their loss from 44% to under 10%. It did not help after an AP failure, where the clients had already moved and a steer could make the video worse. It could not fix co-channel interference without an operator, because the fix is a high-impact channel change.

**Safety (H2) held, but mostly not because of the twin's predictions.** The twin blocked actions that would have hurt and that an optimiser acting directly applied, so H2 holds. Yet most harmful actions were ones the twin had accepted. Its steady-state model is accurate (4.5% throughput error), but it does not see the seconds right after a change. The twin's real contribution was as part of a gate: verify, apply only what is low-risk or approved, watch, and roll back. In the full system, no high-impact change reached the network without an operator, and every applied action had an accepted verdict. The one gap the campaign exposed is that a rollback can fail.

**The language model can be used safely as a translator (H3).** With schema-constrained output, validation, a deterministic compiler and the twin's check, the main model translated 30 of 30 test intents and the offline fallback 21 of 30. No invalid output reached the network. The model explained live faults correctly from the first alert, but it never acted on its own.

The answer to the research question is therefore qualified. A twin used as a gate makes automated control of a wireless network safer, and an LLM behind that gate is a safe way to state goals in natural language. Whether it also makes the network recover faster depends on the kind of fault, and on having an operator to approve the changes that matter most. Each failure was measured, not assumed: the steers that hurt, the rollbacks that failed and the changes left waiting. These failures mark where the work should go next.

## 8.2 Future work

The original design (PROJECT_PLAN, deliverables D5–D6) had four parts that the 25-day scope left out (PHASE_PLAN §3). Each now has a clear place in the system, because the twin's verdict is the one gate every proposal passes through.

- **A learned twin.** A graph neural network trained on the twin's own validation data, in the manner of RouteNet [2], could replace or check the analytical model where it is weakest: bulk TCP flows (12–21% error) and the transient while clients move. It would sit behind the same verifier interface. The analytical model would remain the fallback that can always explain its numbers.
- **A learning optimiser.** Reinforcement learning could propose moves the bounded heuristics cannot, such as a combined channel change and steer when no single steering target is left (the case that limited one flash-crowd seed, Section 7.2). The twin would act as its safety layer: an RL agent proposes, and the twin and the executor's watch decide, exactly as for the heuristics.
- **Grounded answers (RAG).** The copilot answers from live tools only. Retrieval over the runbooks, the decision log and past incidents would let it cite *why* the network is configured as it is, and what fixed a similar fault before.
- **Real hardware.** The same control plane could drive programmable access points (as in Odin [4]) instead of Mininet-WiFi [5]. The testbed layer (the AP agent and the switches) would change; the twin, the loop and the executor reach it only over REST and MQTT, so they would not. The twin would need recalibrating on the real radios, which the validation scripts (P3.5) already do from recorded runs.
- **Per-run isolation and more operators.** A run identifier per demo or experiment, and approvals from more than one operator with roles, would take the system from a single-operator laboratory towards a shared deployment (PHASE_PLAN parking lot).
