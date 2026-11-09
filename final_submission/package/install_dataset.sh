#!/bin/bash
# Puts the dataset where the code expects it: copies Dataset/ into Source_Code/, so that
# data/, models/ and experiments/results/ sit in the project's own layout.
# Run once, from the folder this script is in:   bash install_dataset.sh
# (Without a shell: copy the contents of Dataset/ into Source_Code/ by hand, merging folders.)
set -eu
HERE="$(cd "$(dirname "$0")" && pwd)"
[ -d "$HERE/Dataset" ] && [ -d "$HERE/Source_Code" ] || { echo "run it next to Dataset/ and Source_Code/" >&2; exit 1; }
cp -R "$HERE/Dataset/." "$HERE/Source_Code/"
echo "Dataset installed into Source_Code/."
echo "Next:  cd Source_Code && uv sync && make results && make paper   (see ../REPRODUCE.md)"
