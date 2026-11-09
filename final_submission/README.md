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
| **Step 2.** Google Deep Review, at least two rounds (a third recommended), with a revision report | `revisions/revision_report.md` (becomes `Revision_Report.docx`); the draft PDF is `revisions/paper_draft_v0.pdf`; save each uploaded revision as `revisions/paper_revN.pdf` |
| **Step 3.** `Overleaf_Source.zip` | `dist/Overleaf_Source.zip` |
| All implementation files (Python, Mininet and others) | `dist/Code_and_Data.zip` (`Digital-Twin-SDN/`: `common/ twin/ ml/ genai/ api/ controller/ telemetry/ testbed/ dashboard/ experiments/ config/ tests/`) |
| Step-by-step installation and execution instructions; `requirements.txt` / environment configuration | `REPRODUCE.md`, `requirements.txt`, `pyproject.toml` + `uv.lock` (pinned), `.env.example` (variables, all blank), `docker-compose.yml` |
| Required data files, or how to generate them; synthetic datasets identified | In the ZIP: `data/` and `models/` (all **synthetic**, from the Mininet-WiFi emulation); `REPRODUCE.md` section 0 and Level B |
| Parameters, random seeds, simulation settings, baseline configurations | `REPRODUCE.md` section 3; `config/*.yaml`, `experiments/scenarios/*.yaml`, `experiments/batch_eval_v*.yaml` (seeds 42, 43, 44) |
| Exact commands to regenerate the reported results and figures | `REPRODUCE.md` section 2: `make results`, `make paper` (a figure and table map is there) |

## Folder

```
final_submission/
├── README.md             this file
├── REPRODUCE.md          install, data, seeds, parameters, exact commands
├── requirements.txt      pinned dependencies (uv export of uv.lock)
├── paper/                main.tex, references.bib, generated/ (numbers, tables), figures/
├── revisions/            revision_report.md, paper_draft_v0.pdf, paper_revN.pdf (per round)
└── dist/                 built by `make submission` (git-ignored)
    ├── Overleaf_Source.zip
    ├── Code_and_Data.zip     (under the form's 100 MB limit; the build refuses a larger one)
    ├── paper.pdf
    ├── Revision_Report.docx
    └── SHA256SUMS.txt
```

## Submitting

1. Round the paper through Deep Review at least twice (steps in `revisions/revision_report.md`);
   after each round `make paper`, then upload the new PDF.
2. Fill in `revisions/revision_report.md` and put the final `paper_revN.pdf` next to it.
3. `make submission`. The final PDF for the form should be compiled on Overleaf from
   `dist/Overleaf_Source.zip` (Overleaf's pdfLaTeX gives the standard IEEE Times layout; the
   Tectonic build used by `make paper` is a close preview).
4. Upload the four files of `dist/` to <https://forms.gle/5DbSbyJUqFwpXSYM9>.

## Notes for the authors

- The acknowledgment discloses AI-assisted drafting (Claude Code), as IEEE asks; edit it if needed.
- Five references (Lantz, McKeown, Liu, Holt, Jain) and Kleinrock's book were added for this paper;
  check them against their publisher records before submission. The other five come from the
  project report, which checked them against Crossref.
- The paper's qualitative statements (why the failed rollbacks happened) come from the per-run
  analysis in the project report, Section 6.2; its counts are generated from the ledgers.
- No secret is in the package: `.env`, logs and keys are excluded and the build stops if one
  would be included.
