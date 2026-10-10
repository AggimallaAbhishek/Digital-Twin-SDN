"""P5.5 / P5.6 live results: score what the copilot and the explainer said during live runs.

    uv run python -m experiments.analysis.genai_live    # reads data/raw/genai-v1/*/genai.jsonl

A copilot answer is correct (genai/eval/copilot_questions.yaml) when it names the question's
entity (as a word: ap3, not ap13) and one of its keywords, the copilot called every required
tool, and, for a fix question, it suggested that action type on that AP and the twin accepted
it. A root-cause report is correct as in the replay eval (rca_eval.score). The Phase 5 exit gate
("100% of LLM actions have a twin verdict in the audit log") is counted from each run's ledger
(<run_dir>/actions.db). Writes models/genai/v1/live.json.
"""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

from api.wiring import ROOT
from controller.executor.ledger import Ledger
from experiments.analysis.rca_eval import score
from experiments.genai_actor import QUESTIONS, SCENARIOS, Question, load_questions

RAW = ROOT / "data" / "raw" / "genai-v1"
OUT = ROOT / "models" / "genai" / "v1" / "live.json"


def score_answer(question: Question, reply: dict[str, Any]) -> dict[str, Any]:
    """Each criterion, and whether all of them hold (`fix` is None when not asked for)."""
    answer = reply["answer"].lower()
    used = {e["tool"] for e in reply["evidence"]}
    fix = None
    if question.fix is not None:
        fix = any(
            s["action"]["type"] == question.fix["type"]
            and s["action"]["params"].get("ap") == question.fix["ap"]
            and s["verdict"].get("accepted") is True
            for s in reply["suggested_actions"]
        )
    result = {
        "entity": re.search(rf"\b{re.escape(question.entity)}\b", answer) is not None,
        "keyword": any(k.lower() in answer for k in question.keywords),
        "tools": set(question.tools) <= used,
        "fix": fix,
    }
    return result | {"correct": all(v is not False for v in result.values())}


def audit_gate(entries: list[dict[str, Any]], in_log: Callable[[str], bool]) -> dict[str, int]:
    """LLM proposals of a run's log, and how many are in the audit log with a verdict. A proposal
    the tool layer refused as invalid never became an action, so it is counted apart."""
    proposals = [
        s
        for e in entries
        for s in (e.get("reply") or e.get("report") or {}).get("suggested_actions", [])
    ]
    actions = [s["action"]["action_id"] for s in proposals if "error" not in s["verdict"]]
    return {
        "llm_actions": len(actions),
        "llm_actions_with_verdict_in_audit_log": sum(in_log(a) for a in actions),
        "llm_proposals_refused_as_invalid": len(proposals) - len(actions),
    }


def scenario_of(run_id: str) -> str:
    """The scenario a run id starts with (`<scenario>-<tag>-s<seed>`)."""
    for scenario in sorted(SCENARIOS, key=len, reverse=True):
        if run_id.startswith(f"{scenario}-"):
            return scenario
    raise ValueError(f"run id {run_id!r} names no known scenario")


def main(argv: list[str] | None = None) -> int:
    """Score every genai.jsonl under the raw batch directory."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--raw", type=Path, default=RAW)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args(argv)
    questions = {q.id: q for q in load_questions(yaml.safe_load(QUESTIONS.read_text()))}
    answers, reports = [], []
    gate = dict.fromkeys(audit_gate([], bool), 0)
    for log in sorted(args.raw.glob("*/genai.jsonl")):
        run_id = log.parent.name
        entries = [json.loads(line) for line in log.read_text().splitlines()]
        ledger_path = log.parent / "actions.db"
        ledger = Ledger(ledger_path) if ledger_path.exists() else None

        def in_log(action_id: str, ledger: Ledger | None = ledger) -> bool:
            return ledger is not None and ledger.get(action_id) is not None

        for key, n in audit_gate(entries, in_log).items():
            gate[key] += n
        for entry in entries:
            base = {"run_id": run_id, "elapsed_s": entry["elapsed_s"], "error": entry.get("error")}
            if entry["kind"] == "question":
                q = questions[entry["id"]]
                scored = score_answer(q, entry["reply"]) if "reply" in entry else {"correct": False}
                answers.append(base | {"id": q.id, **scored, "reply": entry.get("reply")})
            else:
                scenario = scenario_of(run_id)
                ok = "report" in entry and score(scenario, entry["report"])
                reports.append(base | {"scenario": scenario, "correct": ok, **entry})
    summary = {
        "copilot_correct": sum(a["correct"] for a in answers),
        "copilot_questions": len(answers),
        "rca_correct": sum(r["correct"] for r in reports),
        "rca_alerts": len(reports),
    } | gate
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps({"summary": summary, "answers": answers, "rca": reports}, indent=1)
    )
    for a in answers:
        print(
            f"{a['run_id']} {a['id']}: {'OK' if a['correct'] else 'WRONG'} {a.get('error') or ''}"
        )
    for r in reports:
        print(f"{r['run_id']} rca: {'OK' if r['correct'] else 'WRONG'} {r.get('error') or ''}")
    print(f"GenAI live: {summary} -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
