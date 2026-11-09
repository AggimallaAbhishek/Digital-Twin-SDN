---
title: "Revision Report: Google Deep Review rounds"
subtitle: "A Twin-Gated Control Loop for Campus Wi-Fi (IEEE conference paper)"
---

# How to read this report

For every round it lists **each review comment** exactly as Google Deep Review returned it, the
**modification made** in response (with the place in the paper and the files or experiments that
changed), and the **PDF that was uploaded**. A comment that was not acted on says why.

| Round | Uploaded PDF | Comments | Addressed | Declined (with reason) |
|---|---|---|---|---|
| Draft (before review) | `paper_draft_v0.pdf` | n/a | n/a | n/a |
| Round 1 | `paper_rev1.pdf` | (fill in) | (fill in) | (fill in) |
| Round 2 | `paper_rev2.pdf` | (fill in) | (fill in) | (fill in) |
| Round 3 (recommended) | `paper_rev3.pdf` | (fill in) | (fill in) | (fill in) |

Two complete review and revision rounds are required before submission; a third is recommended.

# Draft before review (self-check)

The first draft was built so that it can be checked against the implementation:

- Every number in the text comes from a generated file (`paper/generated/numbers.tex`), produced by
  `experiments/paper_build.py` from the recorded evaluation; `make paper-check` fails if the paper
  and the evaluation disagree. Tables II and III and Figs. 2 and 3 are generated the same way.
- Every equation and Algorithm 1 is mapped to the module that implements it
  (`final_submission/REPRODUCE.md`, "Equations and algorithm against the code").
- Negative results are reported as they are: H1 is inconclusive, the twin blocked few actions,
  and three rollbacks failed.
- Known weak points to expect from a reviewer: three seeds per cell (wide intervals); an unattended
  campaign (no operator for high-impact actions); one emulated campus; evaluation seeds that reuse the
  calibration dataset's seed numbers; five references added late (to be checked against their
  publisher records).

# Round 1

**Uploaded:** `paper_rev1.pdf` (date: ____)

| # | Review comment (verbatim) | Modification made | Where (section, equation, figure) | Files or experiments changed |
|---|---|---|---|---|
| 1.1 | (paste the comment) | (what was changed, or why it was not) | | |

# Round 2

**Uploaded:** `paper_rev2.pdf` (date: ____)

| # | Review comment (verbatim) | Modification made | Where | Files or experiments changed |
|---|---|---|---|---|
| 2.1 | (paste the comment) | | | |

# Round 3 (recommended)

**Uploaded:** `paper_rev3.pdf` (date: ____)

| # | Review comment (verbatim) | Modification made | Where | Files or experiments changed |
|---|---|---|---|---|
| 3.1 | (paste the comment) | | | |

# How a round is done

1. Compile the paper (`make paper`, or on Overleaf) and upload the PDF to
   <https://research.google/deepreview/>.
2. Paste each comment into the table above.
3. For each comment: change `paper/main.tex`; if a number, table or figure must change, change the
   code or re-run the experiment, then `make results` and `make paper` (the numbers are never
   edited by hand); if a comment needs a new experiment, record it in the last column.
4. Save the PDF that was uploaded as `paper_revN.pdf` in this folder, fill in the round's table,
   and upload the revised PDF as the next round.
5. `make submission` rebuilds `dist/Revision_Report.docx` from this file.
