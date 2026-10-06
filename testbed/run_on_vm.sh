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
nohup "$RYU_MANAGER" $RYU_APP > "$LOG_DIR/ryu-$NAME.out" 2>&1 < /dev/null &
RYU=$!
sleep 3
cd "$REPO" && sudo timeout "$TIMEOUT_S" python3 -m "$MODULE" "$@" > "$LOG_DIR/$NAME.out" 2>&1
RC=$?
kill "$RYU" 2>/dev/null
echo "EXIT=$RC" >> "$LOG_DIR/$NAME.out"
grep -E "_RESULT" "$LOG_DIR/$NAME.out"
exit "$RC"
