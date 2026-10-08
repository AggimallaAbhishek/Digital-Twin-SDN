# Setup Guide: Testbed VM (P0.2)

How to build the Mininet-WiFi + Ryu testbed VM from scratch. **Verified on 2026-10-06:** the smoke test passed 3 of 3 runs.

> Decisions behind this setup: [ADR-002](adr/002-controller.md) (Ryu) and [ADR-003](adr/003-vm-ubuntu-20-04.md) (Ubuntu 20.04).

## 1. Verified environment

| Component | Version |
|---|---|
| Host | macOS on Apple Silicon (arm64), UTM (QEMU backend) |
| Guest OS | Ubuntu 20.04.6 LTS server, kernel 5.4.0-216-generic, **aarch64** |
| VM resources | 4 vCPU, ~4 GB RAM (raise to 6 GB before Phase 2), 21 GB root |
| Python (system) | 3.8.10, pip upgraded to 24.3.1 |
| Mininet-WiFi | 2.7 (git `d0d3c94`, cloned 2026-10-06) |
| Mininet (installed by Mininet-WiFi) | 2.3.1b4 |
| hostapd / wpa_supplicant | 2.12-devel (built by the Mininet-WiFi installer) |
| wmediumd | v0.5 |
| Open vSwitch | 2.13.8 |
| Ryu | 4.34, in `~/ryu-venv` with `eventlet==0.30.2`, `setuptools<58` |
| Traffic | iperf3 (apt), D-ITG (apt `d-itg`: `ITGSend`/`ITGRecv`) |

## 2. Access from the Mac

The Mac uses a dedicated SSH key (`~/.ssh/id_ed25519_sdnvm`) and a host alias, so you can connect with `ssh sdnvm`:

```sshconfig
# ~/.ssh/config
Host sdnvm
  HostName 192.168.64.2
  User abhishek
  IdentityFile ~/.ssh/id_ed25519_sdnvm
  IdentitiesOnly yes
```

On the VM, add the public key to `~/.ssh/authorized_keys`. Passwordless sudo is enabled for the lab user (`/etc/sudoers.d/abhishek-nopasswd`); remove that file to undo it.

> Each team member uses their **own** key. Never share private keys (RULEBOOK §14).

## 3. Install steps (on the VM)

```bash
# 0. Base
sudo apt-get update
sudo apt-get install -y git openssh-server

# 1. Grow the root filesystem into the free space in the volume group (if the installer left some)
sudo vgs                                   # check VFree
sudo lvextend -r -l +100%FREE /dev/ubuntu-vg/ubuntu-lv

# 2. Remove the distro Mininet if present (Mininet-WiFi installs its own)
sudo apt-get remove -y mininet

# 3. Upgrade pip: the installer passes --break-system-packages, which pip 20 doesn't have
sudo -H python3 -m pip install --upgrade "pip>=23.1,<25"

# 4. FlightRadarAPI workaround (see Known problems #2), BEFORE running the installer
sudo -H python3 -m pip install "numpy<2" FlightRadarAPI beautifulsoup4
D=$(python3 -c "import FlightRadar24,os;print(os.path.dirname(os.path.dirname(FlightRadar24.__file__)))")
printf 'from FlightRadar24 import *  # noqa\nfrom FlightRadar24 import FlightRadar24API  # noqa\n' | sudo tee "$D/FlightRadarAPI.py"
python3 -c "from FlightRadarAPI import FlightRadar24API; print('shim ok')"

# 5. Mininet-WiFi with wireless deps, wmediumd, mininet-wifi deps, OpenFlow, OVS
git clone https://github.com/intrig-unicamp/mininet-wifi ~/mininet-wifi
cd ~/mininet-wifi
sudo util/install.sh -Wlnfv
#    If it fails part-way, do NOT re-run with -W (its hostapd patch step is not re-runnable).
#    Re-run only the remaining steps instead, e.g.:  sudo util/install.sh -lnfv

# 6. Traffic tools
sudo apt-get install -y iperf3 d-itg python3-venv

# 7. Ryu in its own venv (ADR-002)
python3 -m venv ~/ryu-venv
~/ryu-venv/bin/pip install --upgrade "pip<25" "setuptools<58" wheel
~/ryu-venv/bin/pip install ryu "eventlet==0.30.2"
~/ryu-venv/bin/ryu-manager --version          # ryu-manager 4.34
```

### Verify the install

```bash
sudo modprobe mac80211_hwsim radios=2 && echo HWSIM_OK
cd ~ && python3 -c "import mn_wifi.net as n; print('mn_wifi', n.VERSION)"   # 2.7
mn --version; wmediumd -V; hostapd -v; ovs-vsctl --version | head -1
```

## 4. Smoke test (P0.2 exit criterion)

The test uses 2 APs (channels 1 and 6), 4 stations, wmediumd interference mode, a log-distance propagation model and Ryu `simple_switch_13`.

```bash
# copy the repo's testbed/ to the VM (or clone the repo there), then on the VM:
testbed/smoke/run_smoke.sh
# expected: SMOKE_RESULT assoc=4/4 loss=0.0% -> PASS
```

Logs go to `~/p02/` (`smoke.out`, `ryu.out`, `mnc.out`).

## 4b. Running a scenario (P1.6)

From the Mac, with the VM up and reachable as `sdnvm`:

```bash
make scenario-vm SCENARIO=lecture_flash_crowd        # one unattended 10-min run (~11 min)
make scenario-repro-vm SCENARIO=lecture_flash_crowd  # 3 runs with the same seed, throughput within ±5%
```

- **Scenarios** live in `experiments/scenarios/`: `normal`, `lecture_flash_crowd`, `ap_failure` and `cochannel_interference` (docs/scenario.md). The targets copy them, the testbed and the config to the VM, and set the VM clock from the Mac.
- **Results:**
  - The last line printed is `SCENARIO_RESULT run_id=… -> PASS`.
  - The run's files are in `~/p02/runs/<run_id>/` on the VM: `manifest.json`, `events.jsonl`, `kpi.jsonl` and `summary.json` (testbed/README.md).
- **To record telemetry,** run the collector on the Mac while the scenario plays:

  ```bash
  make up
  make collect SCENARIO_ID=lecture_flash_crowd RUN_ID=<run_id> DURATION_S=600
  ```

  Then watch Grafana → *Digital Twin SDN / Raw KPIs* (telemetry/README.md).
- **One run at a time:** every target starts with `mn -c`, so it stops anything else running on the VM (RULEBOOK N-2).

## 5. Known problems and fixes

| # | Symptom | Cause | Fix |
|---|---|---|---|
| 1 | Installer fails: `no such option: --break-system-packages` | Ubuntu 20.04 ships pip 20; the flag needs pip ≥ 23 | Step 3: upgrade pip to `<25` (pip 25 drops Python 3.8) |
| 2 | `ModuleNotFoundError: No module named 'FlightRadarAPI'` while installing Mininet-WiFi | `mn_wifi/net.py` imports `FlightRadarAPI`, but every FlightRadarAPI release available for Python 3.8 ships the module as `FlightRadar24`. It also needs `beautifulsoup4`, which it doesn't declare. | Step 4: install `beautifulsoup4` and the two-line `FlightRadarAPI.py` shim. Only the optional flight-tracking example uses this module. |
| 3 | Re-running `install.sh -W…` exits 1 with `Reversed (or previously applied) patch detected` | The hostapd patch step isn't re-runnable | Re-run without `-W` (`-lnfv`). The `.rej` files left in `hostap/` are harmless. |
| 4 | Stations show `associatedTo=ap1` in Python, but `iw dev staX-wlan0 link` says `Not connected`, and pingall is 100% dropped | Mininet-WiFi 2.7 sends one `iw connect` during `build()` with no retry, and marks the station associated even when it fails (a race with hostapd start-up on this VM) | Our topologies call `ensure_associated()` after `ap.start()`. It checks the kernel link and retries (see `testbed/smoke/smoke_topo.py`). **Every topology in `testbed/` must do this.** |
| 5 | An SSH session or script dies suddenly (exit 255) during cleanup | `mn -c` and `net.stop()` run `pkill -9 -f` on patterns like `ryu-manager`, `controller`, `hostapd`, `ping`, `wpa_supplicant`, which also matches **any** shell whose command line contains those words | Run testbed commands from script files (`run_smoke.sh`). Don't put those words in a one-line `ssh host '…'` command that also runs cleanup. |
| 6 | Log files in `/tmp` disappear | `mn -c` deletes `/tmp/*.log` | Write logs outside `/tmp` (we use `~/p02/`, and `testbed/logs/` later) |
| 7 | Ryu 4.34 errors with newer eventlet or setuptools | Ryu is unmaintained | Pin `eventlet==0.30.2` and `setuptools<58` in the venv (ADR-002) |
| 8 | `pingall` on the 20-station campus shows ~1–3% loss on random station↔station pairs; a different set every run | wmediumd's interference mode drops frames based on SNR/interference, like real Wi-Fi. Station↔station pings cross two radio hops. Without interference mode, loss is 0% | Expected behaviour, not a fault. `testbed/connectivity.py` checks **reachability** (failed pairs retried with 3 pings) separately from the **loss rate** (budget 5% in `config/campus_v1.yaml`, deviation #4) |
| 9 | `make sync-vm` fails with `rm: cannot remove ... __pycache__ ...: Permission denied` | Modules run with `sudo python3` wrote root-owned bytecode caches | `run_on_vm.sh` runs `python3 -B` (no caches) and `chown`s its log dir back to the user. One-time cleanup: `sudo find ~/Digital-Twin-SDN -name __pycache__ -prune -exec rm -rf {} +` |
| 10 | `ap.setChannel(6)` returns instantly but the AP stays on its old channel | Mininet-WiFi 2.7 runs `hostapd_cli chan_switch` through a path that silently does nothing on this VM | The AP agent runs `hostapd_cli -i <intf> chan_switch 5 <freq>` itself and confirms with `iw dev <intf> info` (`testbed/ap_logic.py`). Don't use `hostapd_cli disable/enable`: it drops every client and they don't reconnect |
| 11 | A station steered to another AP is associated (per `iw`) but can't reach anything for ~30 s | The L2-learning controller kept the station's old flows; return traffic refreshed their idle timeout, so they never expired | Fixed in P1.3: `twin_controller` detects the MAC on a new port (`ryu_logic.learn_mac`) and deletes the learned flows to/from it on every datapath (REST-installed flows are kept) |
| 12 | VM timestamps are hours off after a reboot; `timedatectl` says `System clock synchronized: no` | NTP (UDP port 123) gets no reply from this network, over IPv4 or IPv6 (tested 2026-10-08 with a raw NTP query; preferring IPv4 in `/etc/gai.conf` did not help and was reverted), so `systemd-timesyncd` never syncs. HTTPS works | `make sync-vm` (run by every VM target) also runs `make vm-clock`, which sets the VM clock from the Mac and prints the remaining skew (about 0.1 s). The collector (P2.1) needs this: it compares VM record timestamps with Mac time |
| 13 | A long run fails the collector's lag/gap check with the *same* ~2-minute gap on every source, no failed polls, and the VM clock behind afterwards | The Mac slept (idle, or lid closed on battery): the VM paused with it, so its clock stopped, and the collector froze. Seen 2026-10-08: `pmset -g log` showed `Wake from Deep Idle` 131 s into a 30-min run | The scenario, collector and batch Make targets run under `caffeinate -i`, but that can't stop **clamshell sleep on battery** (seen again 13:46 local, 30% battery: 15 min asleep). Keep the lid open and the Mac on power during runs. `make batch` marks any run during which the Mac slept (wall clock running ahead of the monotonic clock, or VM clock > 2 s behind afterwards) as failed, and re-running `make batch` repeats only the failed runs. Run `make vm-clock` after any sleep |
