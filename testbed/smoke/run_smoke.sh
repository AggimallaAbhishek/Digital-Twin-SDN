#!/bin/bash
# P0.2 smoke test runner (run ON THE VM): clean -> start Ryu -> 2-AP/4-station pingall -> stop Ryu.
# Usage: testbed/smoke/run_smoke.sh        Logs: $LOG_DIR (default ~/p02), result line in smoke.out
#
# Note: `mn -c` force-kills any process whose command line contains words like "ryu-manager",
# "hostapd" or "ping", and deletes /tmp/*.log. That is why this runs as a script file and
# logs outside /tmp (see docs/setup.md, "Known problems").
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="${LOG_DIR:-$HOME/p02}"
RYU_MANAGER="${RYU_MANAGER:-$HOME/ryu-venv/bin/ryu-manager}"
mkdir -p "$LOG_DIR"

sudo mn -c > "$LOG_DIR/mnc.out" 2>&1
nohup "$RYU_MANAGER" ryu.app.simple_switch_13 > "$LOG_DIR/ryu.out" 2>&1 < /dev/null &
RYU=$!
sleep 3
sudo timeout 240 python3 "$HERE/smoke_topo.py" > "$LOG_DIR/smoke.out" 2>&1
RC=$?
kill "$RYU" 2>/dev/null
echo "EXIT=$RC" >> "$LOG_DIR/smoke.out"
grep -E "SMOKE_RESULT" "$LOG_DIR/smoke.out"
exit "$RC"
