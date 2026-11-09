# Final submission: IEEE paper, code, data and reproducibility

**Paper:** *A Twin-Gated Control Loop for Campus Wi-Fi: Verifying SDN and LLM-Proposed Actions in a
Digital Twin Before They Reach the Network* (IEEE conference format, 6 pages).
Group 22, EC466 Software Defined Networks, IIIT Dharwad.

Everything here is built from the repository as it is: `make submission` rebuilds the ZIPs and the
PDF into `dist/`, so nothing is copied by hand and nothing can drift from the code.

## What the instructions asked for, and where it is

| Requirement | Where |
|---|---|
| **Step 1.** Paper in the IEEE Overleaf template: abstract, introduction, related work; problem scenario, system model, mathematical formulation; proposed algorithm; baselines and experimental setup; results, graphs, performance analysis; conclusion; references in IEEE format | `paper/main.tex` (IEEEtran `conference` class), `paper/references.bib` (IEEE style) |
| The paper reflects the implementation: equations, algorithm, figures and results | Every number, table and plot is generated from the recorded evaluation (`paper/generated/`, `paper/figures/`); `make paper-check` fails if the paper and the evaluation disagree; the equation-to-code map is in `REPRODUCE.md` |
| **Step 2.** Google Deep Review, at least two rounds (a third recommended), with a revision report | `revisions/revision_report.md` (becomes `Revision_Report.docx`); the draft that was reviewed is kept unchanged in `revisions/round0_draft/`; round 1 is done (`revisions/round1_deep_review.md` holds the comments, `revisions/paper_rev1.pdf` the revision, 7 pages); save each next uploaded revision as `revisions/paper_revN.pdf` |
| **Step 3.** One ZIP, at most 100 MB: *Overleaf.zip, source code, figures, dataset (or a link), README, anything else* | `dist/Final_Submission.zip`: `Overleaf.zip`, `Source_Code/`, `Figures/`, `Dataset/`, `README.md`, plus `paper.pdf`, `Revision_Report.docx`, `REPRODUCE.md`, `requirements.txt`, `install_dataset.sh` (its own README is `package/README.md`) |
| All implementation files (Python, Mininet and others) | `Source_Code/` in the ZIP: `common/ twin/ ml/ genai/ api/ controller/ telemetry/ testbed/ dashboard/ experiments/ config/ tests/` |
| Step-by-step installation and execution instructions; system requirements; `requirements.txt` / environment configuration | `SETUP.md` (requirements and setup for the evaluator), `REPRODUCE.md`, `requirements.txt`, `pyproject.toml` + `uv.lock` (pinned), `.env.example` (variables, all blank), `docker-compose.yml` |
| Required data files, or how to generate them; synthetic datasets identified | `Dataset/` in the ZIP: `data/` and `models/` (all **synthetic**, from the Mininet-WiFi emulation); `REPRODUCE.md` section 0 and Level B |
| Parameters, random seeds, simulation settings, baseline configurations | `REPRODUCE.md` section 3; `config/*.yaml`, `experiments/scenarios/*.yaml`, `experiments/batch_eval_v*.yaml` (seeds 42, 43, 44) |
| Exact commands to regenerate the reported results and figures | `REPRODUCE.md` section 2: `make results`, `make paper` (a figure and table map is there) |

## Folder

```
final_submission/
├── README.md             this file
├── REPRODUCE.md          install, data, seeds, parameters, exact commands
├── requirements.txt      pinned dependencies (uv export of uv.lock)
├── paper/                main.tex, references.bib, generated/ (numbers, tables), figures/
├── revisions/            revision_report.md, round0_draft/ (the reviewed draft, unchanged),
│                         roundN_deep_review.md (the comments), paper_revN.pdf (per round)
├── package/              README.md and install_dataset.sh: the top of the submission ZIP
└── dist/                 built by `make submission` (git-ignored)
    ├── Final_Submission.zip  THE FILE TO UPLOAD (under 100 MB; the build refuses a larger one)
    ├── Overleaf.zip          loose copies of parts of it:
    ├── paper.pdf
    ├── Revision_Report.docx
    └── SHA256SUMS.txt
```

Inside `Final_Submission.zip`: `README.md`, `Overleaf.zip`, `paper.pdf`, `Revision_Report.docx`,
`REPRODUCE.md`, `requirements.txt`, `install_dataset.sh`, `Source_Code/`, `Dataset/` (the recorded
evaluation, in the project's layout; the installer copies it into `Source_Code/`) and `Figures/`.

## Submitting

1. Round the paper through Deep Review at least twice (steps in `revisions/revision_report.md`);
   after each round `make paper`, then upload the new PDF.
2. Fill in `revisions/revision_report.md` and put the final `paper_revN.pdf` next to it.
3. Compile the final paper on Overleaf from `dist/Overleaf.zip` (Overleaf's pdfLaTeX gives the
   standard IEEE Times layout; the Tectonic build used by `make paper` is a close preview) and save
   that PDF as `revisions/paper_final.pdf`. Then `make submission`: if that file exists it becomes
   `paper.pdf` in the ZIP, otherwise the Tectonic preview does.
4. Upload `dist/Final_Submission.zip` to <https://forms.gle/5DbSbyJUqFwpXSYM9>.

## Notes for the authors

- The acknowledgment discloses AI-assisted drafting (Claude Code), as IEEE asks; edit it if needed.
- Fifteen of the 20 references were added for this paper, not taken from the project report:
  Lantz, McKeown, Liu, Holt, Jain, Kleinrock (draft) and, after Deep Review round 1, Kephart,
  Clemm (RFC 9315), Fogel (Batfish), Khurshid (VeriFlow), Wang (NetConfEval), Bianchi, Heusse,
  IEEE 802.11-2020 and Ferriol-Galmés (RouteNet-Fermi). Check each against its publisher record
  before submission (the review's citation checker passed the nine it was given). The other five
  come from the project report, which checked them against Crossref.
- The paper's qualitative statements (why the failed rollbacks happened) come from the per-run
  analysis in the project report, Section 6.2; its counts are generated from the ledgers.
- No secret is in the package: `.env`, logs and keys are excluded and the build stops if one
  would be included.
