#!/bin/bash
# Claude Code PostToolUse hook (RULEBOOK §7, layer L1).
# After Claude edits a .py file in this repo: auto-fix lint + format, then type-check the file.
# Exit 2 sends remaining lint/type errors back to Claude so it fixes them immediately.
set -uo pipefail
ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
f="$(jq -r '.tool_response.filePath // .tool_input.file_path // empty')"
case "$f" in
  "$ROOT"/*.py) ;;
  *) exit 0 ;;
esac
[ -f "$f" ] || exit 0
cd "$ROOT" || exit 0
uv run --quiet ruff check --fix --quiet --force-exclude "$f" > /dev/null 2>&1
uv run --quiet ruff format --quiet --force-exclude "$f" > /dev/null 2>&1
errors="$(uv run --quiet ruff check --force-exclude --output-format=concise "$f" 2>&1)" || {
  echo "ruff found issues it could not auto-fix in ${f#"$ROOT"/}:" >&2
  echo "$errors" >&2
  exit 2
}
errors="$(uv run --quiet mypy --no-error-summary "$f" 2>&1)" || {
  echo "mypy errors in ${f#"$ROOT"/} (fix the cause; do not add ignores, RULEBOOK AI-5):" >&2
  echo "$errors" >&2
  exit 2
}
exit 0
