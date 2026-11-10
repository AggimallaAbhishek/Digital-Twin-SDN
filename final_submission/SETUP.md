# Setup guide for the evaluator

How to get from the unpacked ZIP to a working project, on **macOS, Windows or Linux**.

> **No Ubuntu or Linux is needed to check the paper's results.** Every table, figure and number
> of the paper is regenerated from the recorded runs on a normal Mac or Windows computer, in a few
> minutes. Ubuntu is needed only to *re-run the testbed experiments themselves* (about 7 hours;
> section 5), which is optional.

## 1. Fastest way: one click (Level A)

Unpack the ZIP, open the `Final_Submission` folder, then:

| Your computer | Do this |
|---|---|
| **macOS** | Open *Terminal*, type `cd ` (with a space), drag the `Final_Submission` folder into the window, press Enter, then run:<br>`bash run_mac_linux.sh` |
| **Windows 10/11** | Double-click **`run_windows.bat`**. (If Windows shows "Windows protected your PC", choose *More info*, then *Run anyway*.) Or in PowerShell, inside the folder: `powershell -ExecutionPolicy Bypass -File .\run_windows.ps1` |
| **Linux** | `bash run_mac_linux.sh` |

The script does four things, and you can run it again at any time (it skips what is done):

1. puts the dataset where the code expects it (`Dataset/` into `Source_Code/`);
2. installs [`uv`](https://docs.astral.sh/uv/) if you do not have it (`uv` then downloads Python 3.11 itself);
3. installs the pinned Python packages (the first run downloads about 700 MB);
4. regenerates every table and figure, then checks that the paper's numbers match the evaluation.

Add `--tests` (Mac/Linux: `bash run_mac_linux.sh --tests`) or `-Tests` (Windows:
`run_windows.bat -Tests`) to also run the unit tests, about 2 more minutes.

**What you should see at the end:** a line `RESULTS .../experiments/results (missing: none)`,
then `paper-check passed`, then `DONE`. The regenerated tables are in
`Source_Code/experiments/results/results.md` and are identical to the paper's Table II.

## 2. What each level needs

| Level | What you can do | What it needs | Time |
|---|---|---|---|
| **A. Check the results** (recommended) | Regenerate every table, figure and number of the paper from the recorded runs; run the unit tests | Mac, Windows or Linux, internet for the first install | about 5 to 10 minutes |
| **A+. Compile the paper** | Build the paper PDF | Level A, plus an Overleaf account (upload `Overleaf.zip`; nothing to install), or Tectonic | a few minutes |
| **B. Re-run the experiments** | Run the 27 testbed runs again and the LLM evaluations | Level A, plus an Ubuntu 20.04 VM, Docker and Ollama (section 5) | about 7 hours |

## 3. System requirements

**Level A and A+:**

| | Requirement |
|---|---|
| Operating system | macOS, Windows 10/11 or Linux. The project was developed and checked on macOS (Apple Silicon); the Windows runner follows the same steps but was not run on a Windows machine, so if it fails, use WSL 2 (section 4) |
| Python | 3.11. You do not install it yourself: `uv` downloads it |
| Memory | 4 GB or more |
| Disk | about 1.5 GB free (the ZIP is about 65 MB, unpacked about 90 MB, the Python environment about 700 MB) |
| Internet | needed once, for the Python packages |
| `make` | not needed: the runner scripts call Python directly |

**Level B only (not needed to check the results):**

| | Requirement |
|---|---|
| Testbed VM | Ubuntu 20.04 (verified on aarch64), 4 vCPU, 4 to 6 GB RAM, 21 GB disk, with Mininet-WiFi 2.7, Ryu 4.34, Open vSwitch, iperf3 and D-ITG. Build steps: `Source_Code/docs/setup.md` |
| Host services | Docker, for InfluxDB 2.7, Grafana 11.2 and Mosquitto 2.0 (`make up`) |
| LLM | [Ollama](https://ollama.com) with the cloud model `gpt-oss:120b-cloud` (needs internet and an Ollama sign-in) and the local fallback `qwen2.5:3b` (about 2.2 GB of memory) |
| Access | an SSH alias `sdnvm` from the host to the VM |

## 4. The same steps by hand (if you prefer to type the commands)

All commands are run in the unpacked `Final_Submission` folder.

**macOS**

```bash
bash install_dataset.sh                 # Dataset/ into Source_Code/ (once)
brew install uv                         # or: curl -LsSf https://astral.sh/uv/install.sh | sh
cd Source_Code
uv sync --frozen
make results                            # all tables and figures -> experiments/results/
make paper-check                        # the paper's numbers match the evaluation
make check                              # lint, types, import boundaries, unit tests (1 to 2 min)
```

**Windows (PowerShell)**

```powershell
robocopy Dataset Source_Code /E                      # Dataset into Source_Code (once)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
# open a new PowerShell window so that uv is on the PATH, then:
cd Source_Code
$env:PYTHONUTF8 = "1"
uv sync --frozen
uv run python -m experiments.analysis.results        # all tables and figures
uv run python -m experiments.paper_build --check     # the paper's numbers match the evaluation
uv run pytest tests/unit -q --no-cov                 # unit tests
```

(`winget install astral-sh.uv` also installs uv. `make` does not exist on Windows; the three
`uv run` lines are what `make results`, `make paper-check` and the tests run.)

**Windows with WSL 2 (fallback if the native steps fail).** In PowerShell as administrator,
`wsl --install -d Ubuntu`, restart, open the *Ubuntu* app, then follow the Linux commands below.
This is only a Linux shell for the Python steps; it is not the testbed VM. Copy the ZIP into the
Linux side first (`cp /mnt/c/Users/<you>/Downloads/Final_Submission.zip ~`).

**Linux (and WSL)**

```bash
sudo apt-get update && sudo apt-get install -y unzip curl make    # Ubuntu/Debian
bash install_dataset.sh
curl -LsSf https://astral.sh/uv/install.sh | sh && export PATH="$HOME/.local/bin:$PATH"
cd Source_Code && uv sync --frozen
make results && make paper-check && make check
```

**Without `uv` (any OS, Python 3.11 already installed)**

```bash
python3.11 -m venv .venv          # Windows: py -3.11 -m venv .venv
. .venv/bin/activate              # Windows: .venv\Scripts\Activate.ps1
pip install -r ../requirements.txt
python -m experiments.analysis.results
python -m experiments.paper_build --check
pytest tests/unit -q --no-cov
```

**Compile the paper (optional).** Upload `Overleaf.zip` to Overleaf (New Project, Upload Project)
and compile `main.tex`. Locally on Mac: `brew install tectonic`, then `make paper`.

## 5. Level B: re-running the experiments (Ubuntu needed here only)

The testbed (Mininet-WiFi) emulates the Wi-Fi network with Linux kernel features, so it must run
on **Ubuntu 20.04**. The usual way on a Mac or Windows laptop is a virtual machine; the host
keeps running the analysis, Docker and Ollama. This path was verified on macOS (Apple Silicon,
UTM) only; the Windows commands below are a best effort and were not tried.

| Step | macOS | Windows |
|---|---|---|
| Virtual machine software | `brew install --cask utm` (Apple Silicon; on Intel use VirtualBox) | `winget install Oracle.VirtualBox` |
| Ubuntu 20.04 image | Ubuntu 20.04 *server*, arm64 (Apple Silicon) or amd64 (Intel), from ubuntu.com | Ubuntu 20.04 *server*, amd64, from ubuntu.com |
| Docker | `brew install --cask docker` | `winget install Docker.DockerDesktop` |
| Ollama | `brew install ollama`, then `ollama signin` | `winget install Ollama.Ollama`, then `ollama signin` |
| Models | `ollama pull qwen2.5:3b` (the cloud model `gpt-oss:120b-cloud` needs the sign-in) | the same |
| Build the testbed in the VM | follow `Source_Code/docs/setup.md` (Mininet-WiFi, Ryu, iperf3, D-ITG) | the same |

WSL 2 is not a substitute for the VM: Mininet-WiFi needs the `mac80211_hwsim` virtual Wi-Fi
kernel module, which the standard WSL 2 kernel is not known to include. Use a full VM.

On the host, `make up` starts the services and `make campaign MODE=V1`, `V2` and `V3` run the
evaluation (`make` and `ssh` are needed there: macOS, Linux or WSL). Details, seeds and every
command: `REPRODUCE.md`, Level B.

## 6. If something goes wrong

| Symptom | Fix |
|---|---|
| Windows: "running scripts is disabled" | start it with `run_windows.bat` (it bypasses the policy), or `powershell -ExecutionPolicy Bypass -File .\run_windows.ps1` |
| Windows: "Windows protected your PC" | *More info*, then *Run anyway*: the file comes from the unzipped download |
| Windows: `uv` not found after the install | close the window and run `run_windows.bat` again (a new window sees the new PATH) |
| Mac: `bash: run_mac_linux.sh: No such file` | you are not in the `Final_Submission` folder: `cd` into it first |
| Mac: "command not found: brew" | install Homebrew from https://brew.sh, or skip it: the runner installs `uv` itself |
| `uv: command not found` (by hand) | use the install line for your OS in section 4 |
| It says a dataset is missing | run the runner again, or `bash install_dataset.sh`; `Source_Code/data/evalv1-v1` must exist |
| The first run is slow or stops | check the internet connection; the first install downloads about 700 MB; run the script again |
| The Windows runner fails with an error you cannot fix | use WSL 2 (section 4); it runs the same commands as on macOS |

More detail: `REPRODUCE.md` (seeds, parameters, the equation-to-code map, re-running the
experiments). The project's own documentation is in `Source_Code/docs/`.
