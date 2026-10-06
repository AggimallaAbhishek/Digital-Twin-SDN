# common

Shared code for every module: **Pydantic schemas** (`schemas.py`, P0.6), config loading (`config.py`) and logging helpers.

- **Depends on:** the standard library and Pydantic only. No project module may be imported here (RULEBOOK §4).
- **Contracts:** `schemas.py` is **frozen after P0.6**. Changes need an ADR (RULEBOOK rule 5).
- **Python:** 3.11. Anything the VM-side Ryu app imports must stay 3.8-compatible, or be vendored (ADR-002).
- **Test:** `uv run pytest tests/unit -k schemas`
