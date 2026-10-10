"""P5.6 root-cause explainer: an anomaly alert -> a plain-English diagnosis (PROJECT_PLAN §5.3).

    report = explain(LLMClient.from_config(), backend, ToolLayer(backend), alert)
    # {summary, likely_causes[{cause, category, entity, evidence, confidence}],
    #  suggested_actions[{action, verdict}], related_docs[], evidence, model}

The model reads the evidence summary (genai/rca/evidence.py) and answers in the RCAReport schema
(validated, at most 2 repairs: RULEBOOK L-2); no valid report is an error, never a guess. The
`category` of each cause is one of a fixed few, so the P5.6 eval can score the diagnosis. Each
suggested fix goes through the normal twin check (`simulate_in_twin`); nothing is applied.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from genai.llm.client import LLMResult
from genai.rca.evidence import gather
from genai.tools.backend import Backend
from genai.tools.tools import ToolLayer, proposal

PROMPT = Path(__file__).resolve().parents[1] / "prompts" / "rca_v1.md"
PROMPT_VERSION = "rca_v1"
RCA_DOCS = ("docs/scenario.md", "docs/runbooks/services.md", "docs/dataset.md")
Category = Literal["ap_down", "cochannel_interference", "congestion", "bad_action", "other"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Cause(_Strict):
    """One likely cause, with the evidence numbers behind it."""

    cause: Annotated[str, Field(min_length=1, max_length=200)]
    category: Category
    entity: Annotated[str, Field(pattern=r"^(ap[0-9]+|network)$")]
    evidence: Annotated[str, Field(min_length=1, max_length=500)]
    confidence: Annotated[float, Field(ge=0, le=1)]


class Suggestion(_Strict):
    """A fix for the twin to check (the copilot stamps id, source and time)."""

    type: Literal["steer_clients", "set_ap_channel", "set_ap_tx_power"]
    params: dict[str, Any]  # Any: validated as the action type's params by the tool layer
    reason: Annotated[str, Field(min_length=1, max_length=300)]


class RCAReport(_Strict):
    """The model's answer (PROJECT_PLAN §5.3 output, plus a category per cause)."""

    summary: Annotated[str, Field(min_length=1, max_length=500)]
    likely_causes: Annotated[list[Cause], Field(min_length=1, max_length=3)]
    suggested_actions: Annotated[list[Suggestion], Field(max_length=2)]
    related_docs: Annotated[list[str], Field(max_length=5)]


class ReportClient(Protocol):
    """What the explainer needs of genai.llm.client.LLMClient."""

    def complete_json(
        self, messages: Sequence[dict[str, str]], schema: type[RCAReport], *, prompt_version: str
    ) -> LLMResult[RCAReport]: ...


def explain(  # noqa: PLR0913 - the alert, its sources and the clock
    client: ReportClient,
    backend: Backend,
    tools: ToolLayer,
    alert: dict[str, Any],
    *,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    prompt: Path = PROMPT,
) -> dict[str, Any]:  # Any: JSON
    """The root-cause report for `alert`; LLM errors propagate (better no report than a guess)."""
    evidence = gather(backend, alert)
    messages = [
        {"role": "system", "content": prompt.read_text()},
        {"role": "user", "content": f"Evidence:\n{json.dumps(evidence, default=str)}"},
    ]
    result = client.complete_json(messages, RCAReport, prompt_version=PROMPT_VERSION)
    report = result.value
    suggested = []
    for s in report.suggested_actions:
        action = proposal("rca", s.type, s.params, s.reason, clock())
        suggested.append(
            {"action": action, "verdict": tools.call("simulate_in_twin", {"action": action})}
        )
    return {
        "summary": report.summary,
        "likely_causes": [c.model_dump() for c in report.likely_causes],
        "suggested_actions": suggested,
        "related_docs": [d for d in report.related_docs if d in RCA_DOCS],
        "evidence": evidence,
        "model": result.model,
    }
