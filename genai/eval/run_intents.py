"""P5.4: intent accuracy on the 30-intent test set (genai/eval/intents.jsonl, RULEBOOK L-7).

Each intent goes through the LLM client (genai/llm/client.py: main model, local fallback,
schema-constrained output, repair retries) with the prompt genai/prompts/intent_v1.md.

An intent is **correct** when the client returns a schema-valid Policy whose scope (zone and the
set of app classes), objectives and constraints all equal the expected ones, compared as sets.
`policy_id`, `intent_text` and `valid` are not scored. Accuracy = correct / 30.

    uv run python -m genai.eval.run_intents
    uv run python -m genai.eval.run_intents --config <llm.yaml with model: qwen2.5:3b>  # offline
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from common.schemas import Policy
from genai.llm.client import LLM_CONFIG, LLMClient, LLMOutputError, LLMUnavailableError

ROOT = Path(__file__).resolve().parents[2]
INTENTS = ROOT / "genai" / "eval" / "intents.jsonl"
PROMPT = ROOT / "genai" / "prompts" / "intent_v1.md"
PROMPT_VERSION = "intent_v1"


@dataclass(frozen=True)
class Case:
    """One test intent and the policy it should produce."""

    case_id: str
    intent: str
    expected: Policy


@dataclass(frozen=True)
class Outcome:
    """Which parts of the model's policy match the expected one."""

    valid: bool
    scope: bool
    objectives: bool
    constraints: bool

    @property
    def correct(self) -> bool:
        return self.valid and self.scope and self.objectives and self.constraints


def load_cases(path: Path = INTENTS) -> list[Case]:
    """Read the JSONL test set; every expected policy must pass the Policy schema."""
    cases: list[Case] = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        expected = {
            "policy_id": "pol_expected",
            "intent_text": row["intent"],
            "created_by": "llm.intent",
            **row["expected"],
        }
        try:
            policy = Policy.model_validate(expected)
        except ValidationError as exc:
            raise ValueError(f"{row['id']}: expected policy is not valid: {exc}") from exc
        cases.append(Case(row["id"], row["intent"], policy))
    ids = [c.case_id for c in cases]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate intent ids in the test set")
    return cases


def _objectives(policy: Policy) -> set[tuple[str, str, Any]]:
    return {
        (o.kpi, o.op, o.value if isinstance(o.value, str) else float(o.value))
        for o in policy.objectives
    }


def _constraints(policy: Policy) -> set[tuple[str, str, float, str]]:
    return {(c.kpi, c.op, float(c.value), c.scope) for c in policy.constraints}


def score(expected: Policy, got: Policy | None) -> Outcome:
    """Compare a model's policy (None if it produced no valid one) with the expected policy."""
    if got is None:
        return Outcome(valid=False, scope=False, objectives=False, constraints=False)

    def apps(p: Policy) -> set[str] | None:
        return set(p.scope.app_class) if p.scope.app_class else None

    return Outcome(
        valid=True,
        scope=got.scope.zone == expected.scope.zone and apps(got) == apps(expected),
        objectives=_objectives(got) == _objectives(expected),
        constraints=_constraints(got) == _constraints(expected),
    )


def accuracy(outcomes: list[Outcome]) -> float:
    """Share of fully correct outcomes (0 for none)."""
    return sum(o.correct for o in outcomes) / len(outcomes) if outcomes else 0.0


def main(argv: list[str] | None = None) -> None:
    """Run every intent through the LLM client and print accuracy and the misses."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--intents", type=Path, default=INTENTS)
    parser.add_argument("--config", type=Path, default=LLM_CONFIG, help="LLM config (models)")
    args = parser.parse_args(argv)

    cases = load_cases(args.intents)
    client = LLMClient.from_config(args.config)
    system = PROMPT.read_text()
    outcomes: list[Outcome] = []
    models: dict[str, int] = {}
    for case in cases:
        messages = [{"role": "system", "content": system}, {"role": "user", "content": case.intent}]
        try:
            result = client.complete_json(messages, Policy, prompt_version=PROMPT_VERSION)
        except (LLMOutputError, LLMUnavailableError) as exc:
            got, note = None, f"no valid policy: {exc}"
        else:
            got, note = result.value, ""
            models[result.model] = models.get(result.model, 0) + 1
        outcome = score(case.expected, got)
        outcomes.append(outcome)
        if not outcome.correct:
            print(f"MISS {case.case_id} {case.intent!r}: {outcome} {note}")
            if got is not None:
                scored = {"scope", "objectives", "constraints"}
                print(f"     got {got.model_dump_json(include=scored)}")

    n = len(outcomes)
    print(f"\nModels used: {models}")
    print("| Schema-valid | Scope | Objectives | Constraints | Correct | Accuracy |")
    print("|---|---|---|---|---|---|")
    print(
        f"| {sum(o.valid for o in outcomes)}/{n} | {sum(o.scope for o in outcomes)}/{n}"
        f" | {sum(o.objectives for o in outcomes)}/{n} | {sum(o.constraints for o in outcomes)}/{n}"
        f" | {sum(o.correct for o in outcomes)}/{n} | **{accuracy(outcomes):.1%}** |"
    )


if __name__ == "__main__":
    main()
