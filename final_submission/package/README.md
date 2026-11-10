# Final submission: A Twin-Gated Control Loop for Campus Wi-Fi

IEEE conference paper, code, figures and data. Group 22, EC466 Software Defined Networks,
IIIT Dharwad. This ZIP is under 100 MB.

**Paper:** *A Twin-Gated Control Loop for Campus Wi-Fi: Verifying SDN and LLM-Proposed Actions in a
Digital Twin Before They Reach the Network*. A digital twin of an emulated campus Wi-Fi network
(Mininet-WiFi, Ryu) checks every action an optimizer or an LLM proposes before it reaches the
network; an executor applies it, watches the live KPIs and rolls it back on a regression. Three
controllers are compared over 27 runs.

## What is in this ZIP

| Item | What it is |
|---|---|
| `Overleaf.zip` | The paper's source (IEEE conference template, `main.tex`, `references.bib`, generated numbers, tables and figures). In Overleaf: New Project, Upload Project, choose this file; it compiles with pdfLaTeX. |
| `paper.pdf` | The compiled paper. |
| `Source_Code/` | All the code: the Mininet-WiFi testbed (`testbed/`), the controller and executor (`controller/`), the digital twin (`twin/`), forecasting, anomaly detection and optimizer (`ml/`), the LLM layer (`genai/`), the API (`api/`), the dashboard, the experiments and analysis scripts (`experiments/`), configuration (`config/`), tests and documentation. |
| `Figures/` | `paper/`: the paper's figures (vector PDF, generated from the results); `results/`: the evaluation's KPI plots; `report/`: the architecture diagrams of the project report. The architecture figure of the paper (Fig. 1) is drawn in TikZ inside `main.tex`. |
| `Dataset/` | The recorded evaluation behind every number and plot, in the project's folder layout (`data/`, `models/`, `experiments/results/`). **All data are synthetic**: produced by the Mininet-WiFi emulation, no real-network traces. See `Dataset/data/README.md`. `install_dataset.sh` copies it into `Source_Code/`. |
| `README.md` | This file. |
| `SETUP.md` | **Start here for installation**: the system requirements (OS, Python, memory, disk, internet, optional tools), step-by-step setup, what you should see, and fixes for common problems. |
| `REPRODUCE.md` | Step-by-step installation and execution, seeds, parameters, baseline configurations, the exact command for every figure and table, and the map from equations to code. |
| `requirements.txt` | Pinned Python dependencies (the project also has `pyproject.toml` and `uv.lock`). |
| `Revision_Report.docx` | The Google Deep Review revision report: each round's review comments and the modifications made. |
| `run_mac_linux.sh`, `run_windows.bat` | **One click to check everything** on macOS/Linux or Windows (the `.bat` starts `run_windows.ps1`): installs what is missing, regenerates every result, checks the paper's numbers. |
| `install_dataset.sh` | Puts the dataset where the code expects it (the runners do this for you). |

## Quick start (no Ubuntu, VM, Docker or LLM needed; details in `SETUP.md`)

Unpack the ZIP, then:

| Computer | Command |
|---|---|
| **Windows** | double-click `run_windows.bat` |
| **macOS** | in Terminal, inside the folder: `bash run_mac_linux.sh` |
| **Linux** | `bash run_mac_linux.sh` |

It installs `uv` (which fetches Python 3.11 and the packages, about 700 MB the first time),
regenerates every table and figure of the evaluation, and checks that the paper's numbers match.
Add `--tests` (Windows: `-Tests`) to run the unit tests too. Typing the steps by hand, the
`pip` route, the paper compile and fixes for common problems are in `SETUP.md`.

**No Ubuntu or Linux is needed** for any of this. Ubuntu 20.04 is needed only to re-run the
27 testbed runs themselves (about 7 hours; `SETUP.md` section 5), which checking the results does
not require.

`make results` rewrites `experiments/results/results.md`; its tables are identical to the ones in
the paper. Regenerating the recorded runs themselves (27 testbed runs, about 7 hours on the VM)
is described in `REPRODUCE.md`, Level B.

## Synthetic data, seeds and settings

- The datasets are synthetic (emulated). Calibration dataset `data/v1`: 12 runs, 4 scenarios, seeds
  42, 43, 44 (train, validation, test). Evaluation: `data/evalv1-v1`, `evalv2-v1`, `evalv3-v1`
  (V1 plain SDN, V2 heuristics without the twin, V3 full system), 3 scenarios x seeds 42, 43, 44.
- Other seeds: station positions 7 (`config/campus_v1.yaml`), Isolation Forest 42
  (`config/anomaly.yaml`). Model, loop and baseline settings are in `Source_Code/config/` and
  `Source_Code/experiments/batch_eval_v*.yaml`.
- No secret is included: `.env` is never packaged (`.env.example` lists the variables, all blank).
