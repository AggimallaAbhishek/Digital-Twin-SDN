"""P5.5 / P5.6 live eval actor (experiments/genai_actor.py) and its scoring (genai_live.py)."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

import pytest
import yaml

from experiments.analysis import genai_live
from experiments.analysis.genai_live import score_answer
from experiments.genai_actor import QUESTIONS, GenAIActor, Question, load_questions


def _questions() -> list[Question]:
    return load_questions(yaml.safe_load(QUESTIONS.read_text()))


def test_the_five_questions_load() -> None:
    questions = _questions()
    assert len(questions) == 5
    assert {q.scenario for q in questions} == {
        "ap_failure",
        "cochannel_interference",
        "lecture_flash_crowd",
    }
    assert questions[3].fix == {"type": "set_ap_channel", "ap": "ap3"}


def test_bad_questions_are_refused() -> None:
    raw = yaml.safe_load(QUESTIONS.read_text())
    raw["questions"][0]["scenario"] = "moon_landing"
    with pytest.raises(ValueError, match="scenario"):
        load_questions(raw)


class Fakes:
    def __init__(self, alerts: list[dict[str, Any] | None], fail: bool = False) -> None:
        self.alerts, self.fail = alerts, fail
        self.asked: list[str] = []
        self.explained: list[dict[str, Any]] = []

    def tick_monitor(self) -> dict[str, Any] | None:
        return self.alerts.pop(0) if self.alerts else None

    def ask(self, question: str) -> dict[str, Any]:
        if self.fail:
            raise RuntimeError("no model")
        self.asked.append(question)
        return {"answer": "ap2 is down", "evidence": [{"tool": "get_topology"}]}

    def explain(self, alert: dict[str, Any]) -> dict[str, Any]:
        self.explained.append(alert)
        return {"likely_causes": [{"category": "ap_down", "entity": "ap2"}]}


def _actor(tmp_path: Path, fakes: Fakes) -> GenAIActor:
    questions = [q for q in _questions() if q.scenario == "ap_failure"]
    return GenAIActor(
        questions,
        onset_s=240,
        tick_monitor=fakes.tick_monitor,
        ask=fakes.ask,
        explain=fakes.explain,
        log=tmp_path / "genai.jsonl",
        background=False,  # run jobs inline so the test sees them
    )


def _log(tmp_path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in (tmp_path / "genai.jsonl").read_text().splitlines()]


def test_questions_are_asked_once_when_due(tmp_path: Path) -> None:
    fakes = Fakes([])
    actor = _actor(tmp_path, fakes)
    for t in (100, 299, 300, 305, 390, 400):
        actor.tick(t)
    assert len(fakes.asked) == 2
    entries = _log(tmp_path)
    assert [e["kind"] for e in entries] == ["question", "question"]
    assert entries[0]["id"] == "q1_lab_outage"
    assert entries[0]["elapsed_s"] == 300
    assert entries[0]["reply"]["answer"] == "ap2 is down"


def test_the_first_alert_after_the_onset_is_explained_once(tmp_path: Path) -> None:
    early = {"ts": "t1", "entity": "ap1"}
    first, second = {"ts": "t2", "entity": "ap2"}, {"ts": "t3", "entity": "ap1"}
    fakes = Fakes([early, None, first, second])
    actor = _actor(tmp_path, fakes)
    for t in (200, 245, 250, 255, 260):  # monitor ticks every 5 s
        actor.tick(t)
    assert fakes.explained == [first]
    [entry] = [e for e in _log(tmp_path) if e["kind"] == "rca"]
    assert entry["alert"] == first
    assert entry["report"]["likely_causes"][0]["entity"] == "ap2"


def test_a_failing_job_is_logged_and_the_run_goes_on(tmp_path: Path) -> None:
    fakes = Fakes([], fail=True)
    actor = _actor(tmp_path, fakes)
    actor.tick(300)
    actor.tick(390)
    errors = [e["error"] for e in _log(tmp_path)]
    assert errors == ["RuntimeError: no model"] * 2


QUESTION = Question(
    "q4",
    "cochannel_interference",
    360,
    "fix?",
    "ap3",
    ("channel",),
    ("simulate_in_twin",),
    {"type": "set_ap_channel", "ap": "ap3"},
)


def _reply(answer: str, tools: list[str], suggested: list[Any]) -> dict[str, Any]:
    return {
        "answer": answer,
        "evidence": [{"tool": t} for t in tools],
        "suggested_actions": suggested,
    }


ACCEPTED_FIX = {
    "action": {"type": "set_ap_channel", "params": {"ap": "ap3", "channel": 11}},
    "verdict": {"accepted": True},
}


def test_an_answer_is_correct_with_entity_keyword_tools_and_an_accepted_fix() -> None:
    reply = _reply(
        "Move AP3 back to channel 11.", ["get_topology", "simulate_in_twin"], [ACCEPTED_FIX]
    )
    assert score_answer(QUESTION, reply) == {
        "entity": True,
        "keyword": True,
        "tools": True,
        "fix": True,
        "correct": True,
    }


@pytest.mark.parametrize(
    ("answer", "tools", "suggested", "failed"),
    [
        ("Move ap13 to channel 11.", ["simulate_in_twin"], [ACCEPTED_FIX], "entity"),  # not ap3
        ("ap3 is fine.", ["simulate_in_twin"], [ACCEPTED_FIX], "keyword"),
        ("ap3 channel 11.", ["get_topology"], [ACCEPTED_FIX], "tools"),
        (
            "ap3 channel 11.",
            ["simulate_in_twin"],
            [ACCEPTED_FIX | {"verdict": {"accepted": False}}],
            "fix",
        ),
    ],
)
def test_each_criterion_can_fail_the_answer(
    answer: str, tools: list[str], suggested: list[Any], failed: str
) -> None:
    result = score_answer(QUESTION, _reply(answer, tools, suggested))
    assert result[failed] is False
    assert result["correct"] is False


def test_a_failing_monitor_tick_is_logged_and_the_run_goes_on(tmp_path: Path) -> None:
    calls = []

    def broken() -> dict[str, Any] | None:
        calls.append(1)
        raise OSError("influx down")

    actor = GenAIActor(
        [],
        240,
        tick_monitor=broken,
        ask=Fakes([]).ask,
        explain=Fakes([]).explain,
        log=tmp_path / "genai.jsonl",
        background=False,
    )
    actor.tick(250)
    actor.tick(255)
    assert len(calls) == 2


def test_jobs_run_on_the_worker_thread(tmp_path: Path) -> None:
    done = threading.Event()
    fakes = Fakes([])

    def ask(question: str) -> dict[str, Any]:
        done.set()
        return fakes.ask(question)

    questions = [q for q in _questions() if q.id == "q1_lab_outage"]
    actor = GenAIActor(
        questions,
        240,
        tick_monitor=fakes.tick_monitor,
        ask=ask,
        explain=fakes.explain,
        log=tmp_path / "genai.jsonl",
    )
    actor.tick(300)
    assert done.wait(5)


def test_a_fix_needs_exactly_type_and_ap() -> None:
    raw = yaml.safe_load(QUESTIONS.read_text())
    raw["questions"][3]["fix"] = {"type": "set_ap_channel"}
    with pytest.raises(ValueError, match="fix"):
        load_questions(raw)


def test_the_live_results_are_scored_per_question_and_alert(tmp_path: Path) -> None:
    run = tmp_path / "raw" / "ap_failure-genai-s44"
    run.mkdir(parents=True)
    lines = [
        {
            "kind": "question",
            "id": "q1_lab_outage",
            "elapsed_s": 300,
            "reply": _reply("ap2 is down.", ["get_topology"], []),
        },
        {
            "kind": "question",
            "id": "q2_busiest_after_failure",
            "elapsed_s": 390,
            "error": "LLMUnavailableError: down",
        },
        {
            "kind": "rca",
            "elapsed_s": 245,
            "alert": {"entity": "ap2"},
            "report": {"likely_causes": [{"category": "ap_down", "entity": "ap2"}]},
        },
    ]
    (run / "genai.jsonl").write_text("".join(json.dumps(line) + "\n" for line in lines))
    out = tmp_path / "live.json"
    assert genai_live.main(["--raw", str(tmp_path / "raw"), "--out", str(out)]) == 0
    summary = json.loads(out.read_text())["summary"]
    assert summary == {
        "copilot_correct": 1,
        "copilot_questions": 2,
        "rca_correct": 1,
        "rca_alerts": 1,
    }
