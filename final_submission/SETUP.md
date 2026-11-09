# Setup guide for the evaluator

What you need on your computer, and how to get from the unpacked ZIP to a working project. Most of
it takes a few minutes; you do **not** need the testbed VM, Docker or an LLM to check the paper's
results (Level A below).

## 1. What you can do, and what each needs

| Level | What you can do | What it needs | Time |
|---|---|---|---|
| **A. Check the results** (recommended) | Regenerate every table, figure and number of the paper from the recorded runs; run the unit tests | A normal computer with Python 3.11 and internet for the first install | about 5 to 10 minutes (about 2 minutes of work on a fast connection) |
| **A+. Compile the paper** | Build the paper PDF | Level A, plus Tectonic, or an Overleaf account (no local LaTeX) | a few minutes |
| **B. Re-run the experiments** | Run the 27 testbed runs again and the LLM evaluations | Level A, plus the Ubuntu testbed VM, Docker and Ollama (section 4) | about 7 hours |

## 2. System requirements

**Level A and A+ (the normal case):**

| | Requirement |
|---|---|
| Operating system | macOS or Linux (the project was developed and checked on macOS, Apple Silicon). Windows: use WSL 2 (Ubuntu) or Git Bash |
| Python | 3.11. You do not have to install it yourself: `uv` (below) downloads the right version |
| Tool to install | [`uv`](https://docs.astral.sh/uv/) (a recent version; checked with 0.12), or plain `pip` |
| Memory | 4 GB or more (an estimate: the analysis loads about 100 MB of data) |
| Disk | about 1.5 GB free: the ZIP is 64 MB, unpacked about 90 MB, and the Python environment about 700 MB |
| Internet | needed once, to download the Python packages (and, for A+, Tectonic's LaTeX packages) |
| Other | `make` (preinstalled on macOS and most Linux; on Windows use WSL) and `git` are convenient; without `make`, run the Python commands listed in `REPRODUCE.md` |
| To compile the PDF | Tectonic (checked with 0.17), **or** upload `Overleaf.zip` to Overleaf and compile there (nothing to install) |

**Level B only (re-running the experiments; not needed to check the results):**

| | Requirement |
|---|---|
| Testbed VM | Ubuntu 20.04 (verified on aarch64), 4 vCPU, 4 to 6 GB RAM, 21 GB disk, with Mininet-WiFi 2.7, Ryu 4.34, Open vSwitch, iperf3 and D-ITG. Build steps: `Source_Code/docs/setup.md` |
| Host services | Docker, for InfluxDB 2.7, Grafana 11.2 and Mosquitto 2.0 (`make up`) |
| LLM | [Ollama](https://ollama.com) with the cloud model `gpt-oss:120b-cloud` (needs internet and an Ollama sign-in) and the local fallback `qwen2.5:3b` (about 2.2 GB of memory) |
| Access | an SSH alias `sdnvm` from the host to the VM |

## 3. Step by step (Level A)

**3.1 Unpack and put the dataset in place**

```bash
unzip Final_Submission.zip
cd Final_Submission
bash install_dataset.sh        # copies Dataset/ into Source_Code/ (once)
cd Source_Code
```

On Windows without WSL, copy the contents of `Dataset/` into `Source_Code/` by hand, merging the
folders.

**3.2 Install the Python environment**

With `uv` (installs Python 3.11 and the pinned packages from `uv.lock`):

```bash
# if uv is missing:  macOS: brew install uv    Linux/WSL: curl -LsSf https://astral.sh/uv/install.sh | sh
uv sync
```

Or with `pip` (needs Python 3.11 already installed):

```bash
python3.11 -m venv .venv
. .venv/bin/activate
pip install -r ../requirements.txt
```

**3.3 Regenerate the results**

```bash
make results      # every table and figure of the evaluation -> experiments/results/
make paper-check  # exit 0: the paper's numbers and tables match the evaluation
make check        # lint, types, import boundaries and the unit tests (about 1 to 2 minutes)
```

Without `make` (with the pip route, inside the activated environment):

```bash
python -m experiments.analysis.results
python -m experiments.paper_build --check
pytest tests/unit -q --no-cov
```

**3.3b Compile the paper (optional)**

```bash
make paper        # needs Tectonic: brew install tectonic   (or see https://tectonic-typesetting.github.io)
```

or upload `Overleaf.zip` to Overleaf (New Project, Upload Project) and compile `main.tex`.

## 4. What you should see

- `make results` ends with a line `RESULTS .../experiments/results (missing: none)`. Its tables
  (`experiments/results/results.md`) are identical to the ones shipped in `Dataset/`, and the
  numbers match the paper's Table II.
- `make paper-check` prints nothing and exits with 0.
- `make check` ends with `passed` for all tests and `Contracts: ... kept, 0 broken`.

## 5. If something goes wrong

| Symptom | Fix |
|---|---|
| `uv: command not found` | install uv (section 3.2), or use the pip route |
| `make results` says a dataset is missing | run `bash install_dataset.sh` first; `Source_Code/data/evalv1-v1` must exist |
| `make paper` says `tectonic not found` | install Tectonic, or compile `Overleaf.zip` on Overleaf |
| Python is not 3.11 with the pip route | use `uv sync` (it fetches 3.11), or install Python 3.11 |
| `make: command not found` (Windows) | use WSL, or the plain Python commands in section 3.3 |
| First install is slow or fails | check your internet connection; `uv sync` downloads about 700 MB |

More detail: `REPRODUCE.md` (seeds, parameters, the equation-to-code map, re-running the
experiments). The project's own documentation is in `Source_Code/docs/`.
