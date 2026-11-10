#!/bin/bash
# One command to check the project on macOS or Linux. No Ubuntu VM, Docker or LLM is needed.
#
#   bash run_mac_linux.sh            install, regenerate every result, check the paper's numbers
#   bash run_mac_linux.sh --tests    the same, then run the unit tests (about 2 more minutes)
#
# Run it from the unpacked Final_Submission/ folder. Safe to run again: it skips what is done.
set -eu

HERE="$(cd "$(dirname "$0")" && pwd)"
RUN_TESTS=0
[ "${1:-}" = "--tests" ] && RUN_TESTS=1

say() { printf '\n==> %s\n' "$1"; }
fail() { printf '\nERROR: %s\n' "$1" >&2; exit 1; }

[ -d "$HERE/Dataset" ] && [ -d "$HERE/Source_Code" ] ||
  fail "run this script from the unpacked Final_Submission folder (it must sit next to Dataset/ and Source_Code/)"

say "1/4  Putting the dataset where the code expects it"
if [ -d "$HERE/Source_Code/data/evalv1-v1" ]; then
  echo "already done"
else
  cp -R "$HERE/Dataset/." "$HERE/Source_Code/"
  echo "copied Dataset/ into Source_Code/"
fi

say "2/4  Checking for uv (it installs Python 3.11 and the packages for you)"
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
if command -v uv >/dev/null 2>&1; then
  echo "found: $(uv --version)"
else
  command -v curl >/dev/null 2>&1 || fail "curl is missing. Install uv by hand (https://docs.astral.sh/uv/) and run this script again"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
  command -v uv >/dev/null 2>&1 || fail "uv was installed but is not on the PATH. Open a new terminal and run this script again"
fi

cd "$HERE/Source_Code"

say "3/4  Installing the Python environment (first time: a few minutes and about 700 MB of downloads)"
uv sync --frozen

say "4/4  Regenerating the results and checking them against the paper"
uv run python -m experiments.analysis.results
uv run python -m experiments.paper_build --check
echo "paper-check passed: the paper's numbers match the evaluation"

if [ "$RUN_TESTS" = 1 ]; then
  say "Unit tests"
  uv run pytest tests/unit -q --no-cov
fi

cat <<EOF

DONE.
  Results (tables, plots):   $HERE/Source_Code/experiments/results/results.md
  The paper:                 $HERE/paper.pdf
  Re-run the unit tests:     bash run_mac_linux.sh --tests
  Compile the paper yourself: upload Overleaf.zip to Overleaf (nothing to install)
EOF
