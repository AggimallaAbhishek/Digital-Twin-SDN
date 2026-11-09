#!/bin/bash
# Stop a testbed run still playing ON THE VM: SIGINT so it cleans up (probes, AP agent), then
# SIGKILL if it is still there after $STOP_WAIT_S seconds (default 30).
# Usage: testbed/stop_on_vm.sh            (exit 0: nothing left running; 2: could not signal)
#
# Called by testbed/run_on_vm.sh before every run, and by `make demo-stop` over ssh
# (experiments/demo.py). Why: a demo stopped from the Mac mid-way kept its scenario playing
# here; it held the AP agent's port, so the next run failed with "Address already in use" and
# the dashboard waited for telemetry (2026-11-09). One testbed network runs at a time, so any
# earlier testbed run is stopped, a batch's included.
#
# The pattern is anchored on the interpreter, so it never matches a script's own command line
# (which names the module as an argument), and bracketed, so it never matches pkill or pgrep.
set -u
RUN_PATTERN="${RUN_PATTERN:-^python3 -B -m [t]estbed[.]}"  # override: tests only
WAIT_S="${STOP_WAIT_S:-30}"

sudo pkill -INT -f "$RUN_PATTERN"
case $? in
  0) ;;                # signalled: wait for it to finish below
  1) exit 0 ;;         # nothing was running
  *) echo "stop_on_vm: could not signal an earlier run (pkill or sudo failed)" >&2; exit 2 ;;
esac
for _ in $(seq "$WAIT_S"); do
  pgrep -f "$RUN_PATTERN" > /dev/null || exit 0
  sleep 1
done
sudo pkill -KILL -f "$RUN_PATTERN"
exit 0
