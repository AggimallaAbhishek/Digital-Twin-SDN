"""P5.5 / P5.6 live eval actor (experiments/genai_actor.py) and its scoring (genai_live.py)."""

from __future__ import annotations

import dataclasses
import functools
import json
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

from experiments.analysis import genai_live
from experiments.analysis.genai_live import audit_gate, score_answer
from experiments.genai_actor import QUESTIONS, GenAIActor, Question, Worker, load_questions


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
    def __init__(self, fail: bool = False) -> None:
        self.raised: list[dict[str, Any]] = []  # alerts the monitor holds
        self.since: list[float] = []
        self.fail = fail
        self.asked: list[str] = []
        self.explained: list[dict[str, Any]] = []

    def alerts_since(self, seconds: float) -> list[dict[str, Any]]:
        self.since.append(seconds)
        return list(self.raised)

    def ask(self, question: str) -> dict[str, Any]:
        if self.fail:
            raise RuntimeError("no model")
        self.asked.append(question)
        return {"answer": "ap2 is down", "evidence": [{"tool": "get_topology"}]}

    def explain(self, alert: dict[str, Any]) -> dict[str, Any]:
        self.explained.append(alert)
        return {"likely_causes": [{"category": "ap_down", "entity": "ap2"}]}


def _run_now(job: Callable[[], None]) -> None:
    job()


def _actor(tmp_path: Path, fakes: Fakes) -> GenAIActor:
    questions = [q for q in _questions() if q.scenario == "ap_failure"]
    return GenAIActor(
        questions,
        onset_s=240,
        alerts_since=fakes.alerts_since,
        ask=fakes.ask,
        explain=fakes.explain,
        submit=_run_now,  # jobs inline, so the test sees them
        log=tmp_path / "genai.jsonl",
    )


def _log(tmp_path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in (tmp_path / "genai.jsonl").read_text().splitlines()]


def test_questions_are_asked_once_when_due(tmp_path: Path) -> None:
    fakes = Fakes()
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
    fakes = Fakes()
    actor = _actor(tmp_path, fakes)
    actor.tick(200)  # before the onset: the monitor's alerts are not even read
    actor.tick(245)  # nothing raised since the onset yet
    first, second = {"ts": "t2", "entity": "ap2"}, {"ts": "t3", "entity": "ap1"}
    fakes.raised = [first, second]
    actor.tick(250)
    actor.tick(255)
    assert fakes.since == [5, 10]  # only alerts raised since the onset count
    assert fakes.explained == [first]
    [entry] = [e for e in _log(tmp_path) if e["kind"] == "rca"]
    assert entry["alert"] == first
    assert entry["report"]["likely_causes"][0]["entity"] == "ap2"


def test_a_failing_job_is_logged_and_the_run_goes_on(tmp_path: Path) -> None:
    actor = _actor(tmp_path, Fakes(fail=True))
    actor.tick(300)
    actor.tick(390)
    errors = [e["error"] for e in _log(tmp_path)]
    assert errors == ["RuntimeError: no model"] * 2


def test_the_worker_runs_jobs_in_order_and_ends_with_the_run() -> None:
    stop, done = threading.Event(), list[int]()
    worker = Worker(stop)
    for n in range(3):
        worker.submit(functools.partial(done.append, n))
    stop.set()  # the run ended: what is queued still runs, then the thread ends
    worker.thread.join(timeout=5)
    assert not worker.thread.is_alive()
    assert done == [0, 1, 2]


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
        "llm_actions": 0,
        "llm_actions_with_verdict_in_audit_log": 0,
        "llm_proposals_refused_as_invalid": 0,
    }


def test_every_llm_action_must_have_its_verdict_in_the_audit_log() -> None:  # P5 exit gate
    def proposal(action_id: str, verdict: dict[str, Any]) -> dict[str, Any]:
        return {"action": {"action_id": action_id}, "verdict": verdict}

    entries: list[dict[str, Any]] = [
        {
            "kind": "question",
            "reply": _reply("x", [], [proposal("act_copilot_1", {"accepted": True})]),
        },
        {
            "kind": "rca",
            "report": {
                "suggested_actions": [
                    proposal("act_rca_1", {"accepted": False}),
                    proposal("act_rca_2", {"error": "invalid arguments"}),  # never became an action
                ]
            },
        },
        {"kind": "question", "error": "LLMUnavailableError: down"},
    ]
    in_log = {"act_copilot_1"}
    assert audit_gate(entries, in_log.__contains__) == {
        "llm_actions": 2,
        "llm_actions_with_verdict_in_audit_log": 1,
        "llm_proposals_refused_as_invalid": 1,
    }


def test_the_scenario_comes_from_the_run_id() -> None:
    assert genai_live.scenario_of("cochannel_interference-genai-s44") == "cochannel_interference"
    assert genai_live.scenario_of("ap_failure-s43") == "ap_failure"
    with pytest.raises(ValueError, match="scenario"):
        genai_live.scenario_of("moon-s1")


def test_unicode_spaces_in_an_answer_count_as_spaces() -> None:
    # found live: gpt-oss writes "channel\u202f11" (narrow no-break space)
    reply = _reply("Move ap3 to channel\u202f11.", ["simulate_in_twin"], [ACCEPTED_FIX])
    question = dataclasses.replace(QUESTION, keywords=("channel 11",))
    assert score_answer(question, reply)["keyword"] is True
