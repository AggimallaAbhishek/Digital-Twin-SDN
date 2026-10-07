"""P5.1 Done when: schema-valid output on test prompts, every call logged. Needs Ollama running.

make llm-client-check
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from common.schemas import Policy
from genai.eval.compare_models import CASES, SYSTEM_PROMPT
from genai.llm.client import LLMClient, LLMConfig, ollama_transport

pytestmark = [pytest.mark.llm, pytest.mark.enable_socket]

PROMPT_VERSION = "p0.7/compare_models"


def _messages(intent: str) -> list[dict[str, str]]:
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": intent}]


def _logged(log_path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in log_path.read_text().splitlines()]


@pytest.mark.parametrize("intent", [case[0] for case in CASES])
def test_test_prompts_give_schema_valid_policies(tmp_path: Path, intent: str) -> None:
    log_path = tmp_path / "llm_calls.jsonl"
    client = LLMClient.from_config(log_path=log_path)

    result = client.complete_json(_messages(intent), Policy, prompt_version=PROMPT_VERSION)

    assert isinstance(result.value, Policy)
    entries = _logged(log_path)
    assert entries[-1]["valid"] is True
    assert entries[-1]["model"] == result.model
    print(f"{result.model} fell_back={result.fell_back} attempts={len(entries)}: {intent}")


def test_unreachable_main_model_falls_back_to_local(tmp_path: Path) -> None:
    config = dataclasses.replace(LLMConfig.load(), model="no-such-model:latest")
    log_path = tmp_path / "llm_calls.jsonl"
    client = LLMClient(config, transport=ollama_transport(config.base_url), log_path=log_path)

    result = client.complete_json(_messages(CASES[0][0]), Policy, prompt_version=PROMPT_VERSION)

    assert result.fell_back is True
    assert result.model == config.fallback_model
    entries = _logged(log_path)
    assert entries[0]["model"] == "no-such-model:latest"
    assert "HTTP 404" in str(entries[0]["error"])
    assert entries[-1]["valid"] is True
