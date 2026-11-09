# ADR-007: The demo report may borrow the dashboard's wording and colours

- **Status:** Accepted (Abhishek, 2026-11-09)
- **Phase / task:** demo run report (`docs/superpowers/specs/2026-11-09-demo-run-report-design.md`), found by the graphify review of 2026-11-09
- **Deviation log:** PHASE_PLAN.md #21

## Context

RULEBOOK §4 makes `dashboard/` a leaf: it talks to the system only over HTTP, and nothing imports it. An import-linter contract enforces that for the core packages, but `experiments/` was not a root package for import-linter, so nothing checked what it imported. The imports below were already committed when the graphify review of 2026-11-09 found them; this ADR records the exception after the fact.

`experiments/demo_report.py` builds the HTML report of a demo run. It imports two things from the dashboard:

- `dashboard.views.describe`, so an action reads the same in the report as on the page (`set_ap_channel ap3 → channel 11`);
- `dashboard.theme`, so the report uses the page's colours and fonts.

Both modules use only the standard library. The other ways out were worse:

- **Move them to `common/`:** the dashboard may not import `common` (P6.1), so it could not use the moved code without breaking a second rule.
- **Copy them into the report:** the wording and colours of the two would drift apart.
- **A new shared package:** a new module boundary that touches the dashboard just before the demo.

## Decision

- `experiments.demo_report` may import **`dashboard.theme`** and **`dashboard.views`**, read-only.
- Nothing else in `experiments` may import the dashboard, and the report may not import any other dashboard module. `experiments` is now a root package for import-linter, and a contract enforces this with the two allowed imports listed as exceptions.
- `dashboard.theme` and `dashboard.views` stay standard-library only, so the report never pulls in Streamlit or the rest of the dashboard. A second contract enforces this (it forbids the other dashboard modules and the dashboard's third-party packages; `include_external_packages = true` makes those visible to import-linter).
- `dashboard/__init__.py` stays empty: `from dashboard import theme` runs it first, and no contract sees what it imports.
- The direction stays one-way: the dashboard still imports no project module.

## Consequences

- **Positive:** one wording and one palette for the page and the report, and `make check` now enforces the boundary.
- **Negative:** a change to `describe()` or a theme name must keep the demo report's tests passing (they run in `make check`). The second contract lists the forbidden modules by name, so a new `dashboard/*.py` module or a new third-party package used by the dashboard must be added to it. Forbidding the whole `dashboard` package does not work: import-linter does not check a module against its own parent package.
