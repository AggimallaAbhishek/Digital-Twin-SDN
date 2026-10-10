"""P5.5 / P5.6 live results: score what the copilot and the explainer said during live runs.

    uv run python -m experiments.analysis.genai_live    # reads data/raw/genai-v1/*/genai.jsonl

A copilot answer is correct (genai/eval/copilot_questions.yaml) when it names the question's
entity (as a word: ap3, not ap13) and one of its keywords, the copilot called every required
tool, and, for a fix question, it suggested that action type on that AP and the twin accepted
it. A root-cause report is correct as in the replay eval (rca_eval.score). Writes
models/genai/v1/live.json.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import yaml

from api.wiring import ROOT
from experiments.analysis.rca_eval import score
from experiments.genai_actor import QUESTIONS, Question, load_questions

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


def main(argv: list[str] | None = None) -> int:
    """Score every genai.jsonl under the raw batch directory."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--raw", type=Path, default=RAW)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args(argv)
    questions = {q.id: q for q in load_questions(yaml.safe_load(QUESTIONS.read_text()))}
    answers, reports = [], []
    for log in sorted(args.raw.glob("*/genai.jsonl")):
        run_id = log.parent.name
        for entry in map(json.loads, log.read_text().splitlines()):
            base = {"run_id": run_id, "elapsed_s": entry["elapsed_s"], "error": entry.get("error")}
            if entry["kind"] == "question":
                q = questions[entry["id"]]
                scored = score_answer(q, entry["reply"]) if "reply" in entry else {"correct": False}
                answers.append(base | {"id": q.id, **scored, "reply": entry.get("reply")})
            else:
                scenario = run_id.split("-")[0]
                ok = "report" in entry and score(scenario, entry["report"])
                reports.append(base | {"scenario": scenario, "correct": ok, **entry})
    summary = {
        "copilot_correct": sum(a["correct"] for a in answers),
        "copilot_questions": len(answers),
        "rca_correct": sum(r["correct"] for r in reports),
        "rca_alerts": len(reports),
    }
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
