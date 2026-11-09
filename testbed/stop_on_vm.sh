#!/bin/bash
# Stop a testbed run still playing ON THE VM: SIGINT so it cleans up (probes, AP agent), then
# SIGKILL if it is still there after $STOP_WAIT_S seconds (default 30). Returns once the run and
# its run_on_vm.sh wrapper are gone: the old wrapper still pkills "ryu-manager <app>" after its
# run ends, which would kill the next run's Ryu.
# Usage: testbed/stop_on_vm.sh   (exit 0: nothing left running; 2: could not stop it, see stderr)
#
# Called by testbed/run_on_vm.sh before every run, and by `make demo` / `make demo-stop` over ssh
# (experiments/demo.py). Why: a demo stopped from the Mac mid-way kept its scenario playing
# here; it held the AP agent's port, so the next run failed with "Address already in use" and
# the dashboard waited for telemetry (2026-11-09). One testbed network runs at a time, so any
# earlier testbed run is stopped, a batch's included.
#
# The pattern is anchored on the interpreter, so it never matches a command line that only
# names the module as an argument (the wrappers, the ssh line carrying this script, pkill).
set -u
RUN_PATTERN="${RUN_PATTERN:-^python3 -B -m testbed[.]}"  # override: tests only (macOS argv)
WRAPPER_PATTERN='[r]un_on_vm[.]sh'
TICKS=$(( ${STOP_WAIT_S:-30} * 10 ))  # polled every 0.1 s
KILL_TICKS=50  # after SIGKILL: the wrapper's chown and Ryu stop

fail() { echo "stop_on_vm: $*" >&2; exit 2; }
# -n: never prompt; sudo -n exits 1 when it would need a password, like pkill finding nothing
sudo -n true 2> /dev/null || fail "could not signal an earlier run (sudo needs a password)"
sudo -n pkill -INT -f "$RUN_PATTERN"
case $? in
  0) ;;          # signalled: wait for it to finish below
  1) exit 0 ;;   # nothing was running
  *) fail "could not signal an earlier run (pkill failed)" ;;
esac

gone() {  # the run, and every wrapper other than the one that called this script
  ! pgrep -f "$RUN_PATTERN" > /dev/null && ! pgrep -f "$WRAPPER_PATTERN" | grep -qvx "$PPID"
}
wait_gone() { for _ in $(seq "$1"); do gone && return 0; sleep 0.1; done; return 1; }

wait_gone "$TICKS" && exit 0
sudo -n pkill -KILL -f "$RUN_PATTERN"
wait_gone "$KILL_TICKS" || fail "an earlier run is still there after SIGKILL"
