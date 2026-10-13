# Project report

One Markdown file per chapter, in reading order. Our own structure until a department template is confirmed (decisions Q4b); the content moves over unchanged if one appears.

| File | Chapter | Task | Due | Status |
|---|---|---|---|---|
| [00_title_page.md](00_title_page.md) | Title page, abstract | P7.1a / P7.1d (abstract) | Oct 15 / Oct 28 | Title page done (course, faculty, department, institute; Oct 13); abstract written Oct 12 |
| [01_introduction.md](01_introduction.md) | 1. Introduction | P7.1a | Oct 15 | Drafted |
| [02_related_work.md](02_related_work.md) | 2. Related Work | P7.1a | Oct 15 | Drafted; unconfirmed claims softened to what the abstracts state (2026-10-13) |
| [03_architecture.md](03_architecture.md) | 3. System Architecture | P7.1b | Oct 20 | Drafted (Oct 10): layers, components, data flow, interfaces; 3 diagrams, 3 tables |
| [04_method.md](04_method.md) | 4. Method | P7.1c | Oct 25 | Drafted (Oct 10): twin, model, ML, heuristics, LLM roles, safety; awaiting review |
| [05_implementation.md](05_implementation.md) | 5. Implementation and Testbed | P7.1b | Oct 20 | Drafted (Oct 10): testbed, scenarios + interference model, telemetry + dataset, engineering; 1 diagram, 1 table |
| [06_results.md](06_results.md) | 6. Evaluation and Results | P7.1d | Oct 28 | Drafted (Oct 12–13) from the campaign (`make results`) and finished tasks; awaiting review |
| [07_discussion.md](07_discussion.md) | 7. Discussion and Limitations | P7.1d | Oct 28 | Drafted (Oct 12–13): limitations, failed rollback, threats to validity; awaiting review |
| [08_conclusion.md](08_conclusion.md) | 8. Conclusion and Future Work | P7.1d | Oct 28 | Drafted (Oct 12): 8.1 conclusion, 8.2 future work; awaiting review |
| [99_references.md](99_references.md) | References | P7.1a | Oct 15 | 5 entries (IEEE style) |

## Rules

- Every number in Chapter 6 comes from a script output or figure in `experiments/` (P6.6). No hand-typed results.
- Citations are numbered `[n]` in IEEE style and listed in `99_references.md`. Only cite papers in `docs/literature/`.
- `[check]` marks a claim that has to be confirmed against the paper's full text. None may remain at submission.
