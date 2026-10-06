# CLAUDE.md

GenAI-Driven Digital Twin for Intelligent SDN-Based Wireless Network Optimization.

## Read first, every session
1. `docs/PHASE_PLAN.md`: the current phase, task IDs and their *Done when* lists. Work only on the task the user names.
2. `docs/RULEBOOK.md`: how to work. §9 has the rules for AI assistants.
3. `docs/PROJECT_PLAN.md`: design reference (architecture, schemas, safety model).

## Non-negotiables
- **Never run `git commit` or `git push`.** The user commits and pushes themselves. Leave changes in the working tree and report what changed.
- Stay inside the current task. Out-of-plan ideas go to the PHASE_PLAN parking lot, not into code.
- After every code change, run `make check` (or ruff + mypy + pytest on the affected module) and report the real result.
- Never weaken checks: no deleting or skipping tests, no loosened asserts, no new `# noqa` / `# type: ignore` without a reason, no lowering coverage or lint config.
- Bugs: reproduce → failing test → root cause → minimal fix → full suite (`systematic-debugging` skill).
- Don't change `common/schemas.py`, action bounds, safety thresholds or module boundaries without explicit user approval and an ADR.
- Nothing reaches the network without an accepted twin `Verdict`. The LLM never calls the controller or AP agent directly.
- Never read, print or write secrets from `.env`.

## Skills
Load the matching local skill before starting the work. The full trigger table is in `docs/RULEBOOK.md` §18.
- Designing something new → `brainstorming` · safety/core logic → `tdd` · any error or failing test → `systematic-debugging`
- Before hand-off → `/code-review`, then `/simplify` · API, LLM tools, secrets → `/security-review`
- Backend → `fastapi` · LLM layer (Claude) → `claude-api` · any chart → `dataviz` · dashboard UI → `frontend-design`, `impeccable`, `web-design-guidelines`
- Hooks/settings → `update-config` · report/slides → `anthropic-skills:docx` / `anthropic-skills:pdf` / `anthropic-skills:pptx`
