#!/bin/bash
# P0.2 smoke test (run ON THE VM): 2 APs, 4 stations, Ryu simple_switch_13, pingall.
# Expected: SMOKE_RESULT assoc=4/4 loss=0.0% -> PASS. Logs in ~/p02/smoke.out.
exec "$(cd "$(dirname "$0")/.." && pwd)/run_on_vm.sh" smoke testbed.smoke.smoke_topo "$@"
