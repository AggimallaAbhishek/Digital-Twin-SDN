# ADR-002: SDN controller is Ryu 4.34 in a pinned venv

- **Status:** Accepted (Abhishek, 2026-10-06; confirmed 2026-10-07)
- **Phase / task:** P0.2
- **Related:** ADR-003 (Ubuntu 20.04 VM), RULEBOOK §5.1, PROJECT_PLAN §9

## Context

The plan recommends Ryu, which is Python-based and easy to extend, with OS-Ken as the fallback because Ryu is no longer maintained and breaks with newer Python, `eventlet` and `setuptools` versions. The testbed VM runs Ubuntu 20.04 with Python 3.8 (ADR-003).

## Decision

Use **Ryu 4.34** in a dedicated virtual environment on the VM (`~/ryu-venv`, system Python 3.8), pinned to:

```
ryu==4.34
eventlet==0.30.2
setuptools<58
```

Ryu is kept out of the system Python so it can't clash with Mininet-WiFi's packages.

## Evidence

- `ryu-manager 4.34` starts and listens on 6653/6633.
- The P0.2 smoke test passed 3 of 3 runs with `ryu.app.simple_switch_13`: 4/4 stations associated, pingall 0% loss, about 100 packet-ins handled (see `docs/setup.md` §4).

## Consequences

- Controller apps (`controller/apps/`) must be **Python 3.8-compatible**. Shared schemas used inside the Ryu app have to avoid 3.9+ syntax, or be vendored.
- If a pin conflict or missing feature blocks us later, switch to **OS-Ken**, which has an almost identical API. That switch needs a new ADR that supersedes this one.
- Ryu's northbound REST (`ryu.app.ofctl_rest`) is available for P1.2.
