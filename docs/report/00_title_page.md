::: {custom-style="Title"}
GenAI-Driven Digital Twin for Intelligent SDN-Based Wireless Network Optimization
:::

<!-- Headings centred through pandoc's "Author" style (based on Title: centred, 12 pt); Word tables are full width. Title page details given by Abhishek 2026-10-13. Switch to the department template if one exists (decisions Q4b). -->

::: {custom-style="Author"}
&nbsp;

**Group 22**

&nbsp;

**Submitted by**
:::

| Name | Roll No. | Semester |
|---|---|---|
| Aggimalla Abhishek | 23BDS004 | 7th Semester |
| N. Likhith Naik | 23BDS037 | 7th Semester |
| Sundaram | 23BDS060 | 7th Semester |
| Sambhav Mishra | 23BDS050 | 7th Semester |
| Bikram Hawaldar | 23BCS033 | 7th Semester |

::: {custom-style="Author"}
&nbsp;

**Course details**
:::

| Item | Details |
|---|---|
| Course | EC466 Software Defined Networks |
| Faculty | Dr. Jagadeesha R B, Department of Electronics and Communication Engineering |
| Institute | Indian Institute of Information Technology Dharwad |

```{=openxml}
<w:p><w:r><w:br w:type="page"/></w:r></w:p>
```

## Abstract

<!-- Written 2026-10-12 from Chapters 6-8 (P7.1d). Keep its numbers in step with Chapter 6. -->

Automated control of campus Wi-Fi is risky: a controller learns the effect of a change only after real users feel it, and a large language model (LLM) that turns operator requests into policy can be wrong. We built a digital twin of an emulated software-defined Wi-Fi network (Mininet-WiFi and Ryu; 4 access points, 20 stations) and made it the gate for every change. A heuristic optimiser and an LLM propose actions. An analytical model predicts each action's effect on throughput, latency, loss and fairness, and only accepted actions are applied, high-impact ones after an operator's approval. Each change is then watched and rolled back if the network gets worse. The twin predicts throughput within 4.5%, in under a millisecond. In 27 runs (three controllers, three disruptions, three seeds), the full system more than doubled throughput and cut loss from 44% to under 10% in a lecture-hall flash crowd. Faster recovery than plain SDN was not shown: plain SDN never recovered, so every comparison is a lower bound. The twin blocked harmful actions that an unchecked optimiser applied, but most harm came from actions it accepted; watching and rolling back caught those, but in three runs a rollback set off by an AP failure targeted the failed AP and cut a station off. The LLM translated 30 of 30 test intents (21 of 30 offline), and no invalid output reached the network. A twin works best as part of a safety gate, not as a prediction alone.
