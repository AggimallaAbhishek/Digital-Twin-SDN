# ADR-003: Testbed VM runs Ubuntu 20.04 (not 22.04)

- **Status:** Accepted (Abhishek, 2026-10-06; confirmed 2026-10-07)
- **Phase / task:** P0.2
- **Deviation log:** PHASE_PLAN.md #1

## Context

The plan specified an Ubuntu 22.04 VM with 4 vCPU, 8 GB RAM and a 40 GB disk. The VM we actually have (UTM on an Apple Silicon Mac) is different:

| Item | Plan | Actual |
|---|---|---|
| OS | Ubuntu 22.04 | Ubuntu 20.04.6 LTS, kernel 5.4.0-216, aarch64 |
| Python | 3.11 (services) / pinned 3.9 (Ryu) | 3.8.10 (system) |
| vCPU | 4 | 4 |
| RAM | 8 GB | ~4 GB |
| Disk | 40 GB | 24 GB virtual disk; root grown from 10.5 to 21 GB |

Checks on this VM:
- `mac80211_hwsim` loads on the arm64 kernel. This was the main risk for Mininet-WiFi on ARM.
- Open vSwitch 2.13.8 is present.
- Ryu (unmaintained) works best on Python 3.6–3.8, and breaks with newer Python and `eventlet` versions.

## Decision

Keep **Ubuntu 20.04** for the testbed VM, and run Ryu on the system Python 3.8 inside a virtual environment. Services on the Mac side (twin, ML, GenAI, API) still use Python 3.11 as RULEBOOK §5.1 says. They talk to the VM only over REST and MQTT, so the Python versions don't need to match.

## Consequences

- **Positive:** no rebuild time. Mininet-WiFi is well tested on 20.04. Ryu needs no Python workarounds, which reduces the ADR-002 risk.
- **Negative:** Ubuntu 20.04 standard support ended in April 2025. That's acceptable because the VM is an isolated lab machine with no production exposure (RULEBOOK N-1). `common/` code that the VM imports must stay compatible with Python 3.8, or be vendored.
- **RAM:** ~4 GB is enough for Phase 0–1 smoke tests. Raise it to **6 GB** in UTM (VM shut down) before Phase 2 batch runs. 8 GB isn't practical on a 16 GB Mac that also runs Docker Desktop (8 GB).
- **Disk:** a 21 GB root is enough for Phase 0–2. Grow the UTM virtual disk later only if datasets are stored on the VM. They should be exported to the Mac instead (see `data/`).
