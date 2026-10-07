#!/bin/bash
# Run a testbed module ON THE VM with a fresh network and a Ryu controller.
# Usage: testbed/run_on_vm.sh <name> <python-module> [module args...]
#   e.g. testbed/run_on_vm.sh campus testbed.topologies.campus_v1 --check
# Steps: `mn -c` -> start Ryu ($RYU_APP, default simple_switch_13) -> sudo python3 -m <module>
#        -> stop Ryu. Logs: $LOG_DIR/<name>.out and $LOG_DIR/ryu-<name>.out (default ~/p02).
#
# Why a script: `mn -c` force-kills any process whose command line contains words like
# "ryu-manager", "hostapd" or "ping" (including an ssh one-liner), and deletes /tmp/*.log
# (docs/setup.md, Known problems #5-6).
set -u
[ $# -ge 2 ] || { echo "usage: $0 <name> <python-module> [args...]" >&2; exit 64; }
NAME="$1"; MODULE="$2"; shift 2
REPO="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="${LOG_DIR:-$HOME/p02}"
RYU_MANAGER="${RYU_MANAGER:-$HOME/ryu-venv/bin/ryu-manager}"
RYU_APP="${RYU_APP:-ryu.app.simple_switch_13}"
TIMEOUT_S="${TIMEOUT_S:-600}"
mkdir -p "$LOG_DIR"

sudo mn -c > "$LOG_DIR/mnc-$NAME.out" 2>&1
# Ryu runs from the repo root so repo apps (e.g. RYU_APP=controller.apps.twin_controller) import.
(cd "$REPO" && PYTHONPATH="$REPO" exec nohup "$RYU_MANAGER" $RYU_APP \
  > "$LOG_DIR/ryu-$NAME.out" 2>&1 < /dev/null) &
RYU=$!
sleep "${RYU_STARTUP_S:-3}"
# LOG_DIR is passed through sudo so modules write artefacts to the user's log dir, not /root.
cd "$REPO" && sudo LOG_DIR="$LOG_DIR" timeout "$TIMEOUT_S" python3 -B -m "$MODULE" "$@" \
  > "$LOG_DIR/$NAME.out" 2>&1
RC=$?
sudo chown -R "$(id -un)" "$LOG_DIR"  # artefacts written under sudo stay user-owned
pkill -f "[r]yu-manager $RYU_APP" 2>/dev/null || kill "$RYU" 2>/dev/null
wait "$RYU" 2>/dev/null  # reap the background job quietly (no "Terminated" message)
echo "EXIT=$RC" >> "$LOG_DIR/$NAME.out"
grep -E "_RESULT" "$LOG_DIR/$NAME.out"
exit "$RC"
