"""P5.5 / P5.6 live eval: the copilot and the root-cause explainer played alongside a batch run.

    genai_eval: true      # in a batch config (experiments/batch_genai_v1.yaml)

For each run the actor builds the real API in-process over that run's live telemetry
(api/app.py: twin sync, metrics, the alert monitor; the executor's ledger in the run's
directory). Batch runs are evaluation runs, so the twin simulator is on whatever the B-5 flag
says, as in loop_actor.py; nothing is ever applied (no operator token, and the copilot and the
explainer only propose). During the run:

- each of the scenario's questions (genai/eval/copilot_questions.yaml) is sent to POST /chat
  once its `at_s` has passed;
- the alert monitor ticks every 5 s, and the first alert after the scenario's disruption is
  handed to the root-cause explainer (genai/rca/).

LLM calls take seconds, so they run in one worker thread and the collector loop never waits.
Every result goes to <run_dir>/genai.jsonl (experiments/analysis/genai_live.py scores it).
"""

from __future__ import annotations

import functools
import json
import logging
import queue
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from http import HTTPStatus
from pathlib import Path
from typing import Any

import yaml

from api.alerts import build_alert_monitor, influx_rows
from api.app import Services, TwinSimulator, create_app
from api.metrics import influx_metrics
from api.wiring import ROOT, build_executor, build_twin, load_yaml
from common.influx import InfluxConnection
from experiments.batch import load_scenario
from experiments.dataset import disruption
from experiments.inprocess import inprocess_send
from genai.agent.copilot import Copilot, load_copilot_config
from genai.llm.client import LLMClient
from genai.rca.explainer import explain
from genai.tools.http_backend import HttpBackend
from genai.tools.tools import ToolLayer

log = logging.getLogger("experiments.genai_actor")
QUESTIONS = ROOT / "genai" / "eval" / "copilot_questions.yaml"
SCENARIOS = ("ap_failure", "cochannel_interference", "lecture_flash_crowd", "normal")
MONITOR_S = 5.0
Reply = dict[str, Any]  # Any: JSON


@dataclass(frozen=True)
class Question:
    """One diagnostic question, when to ask it, and what a correct answer holds."""

    id: str
    scenario: str
    at_s: float
    question: str
    entity: str
    keywords: tuple[str, ...]
    tools: tuple[str, ...]
    fix: dict[str, str] | None = None


def load_questions(raw: Mapping[str, Any]) -> list[Question]:
    """Validate genai/eval/copilot_questions.yaml; ValueError names the bad field."""
    questions = []
    for q in raw["questions"]:
        if q["scenario"] not in SCENARIOS:
            raise ValueError(f"{q['id']}: unknown scenario {q['scenario']!r}")
        fix = q.get("fix")
        if fix is not None and set(fix) != {"type", "ap"}:
            raise ValueError(f"{q['id']}: fix needs exactly type and ap")
        questions.append(
            Question(
                str(q["id"]),
                q["scenario"],
                float(q["at_s"]),
                str(q["question"]),
                str(q["entity"]),
                tuple(q["keywords"]),
                tuple(q["tools"]),
                dict(fix) if fix else None,
            )
        )
    return questions


class GenAIActor:
    """Asks the questions when due and explains the first alert after the onset."""

    def __init__(  # noqa: PLR0913 - the run's schedule and its three live parts
        self,
        questions: list[Question],
        onset_s: float | None,
        *,
        tick_monitor: Callable[[], Reply | None],
        ask: Callable[[str], Reply],
        explain: Callable[[Reply], Reply],
        log: Path,
        background: bool = True,
    ) -> None:
        self._pending = sorted(questions, key=lambda q: q.at_s)
        self._onset, self._tick_monitor, self._ask, self._explain = (
            onset_s,
            tick_monitor,
            ask,
            explain,
        )
        self._log, self._lock = log, threading.Lock()
        self._next_monitor, self._explained = 0.0, False
        self._jobs: queue.Queue[Callable[[], None]] | None = None
        if background:
            self._jobs = queue.Queue()
            threading.Thread(target=_work, args=(self._jobs,), daemon=True).start()

    def tick(self, elapsed_s: float) -> None:
        """Called by run_batch while the run plays (elapsed_s ~ scenario time)."""
        while self._pending and self._pending[0].at_s <= elapsed_s:
            q = self._pending.pop(0)
            entry: Reply = {"kind": "question", "id": q.id, "question": q.question}
            self._submit(entry, elapsed_s, "reply", functools.partial(self._ask, q.question))
        if elapsed_s < self._next_monitor:
            return
        self._next_monitor = elapsed_s + MONITOR_S
        try:
            alert = self._tick_monitor()
        except Exception:  # a failed telemetry query must not stop the run
            log.exception("alert monitor tick failed")
            return
        after_onset = self._onset is not None and elapsed_s > self._onset
        if alert is not None and after_onset and not self._explained:
            self._explained = True
            rca: Reply = {"kind": "rca", "alert": alert}
            self._submit(rca, elapsed_s, "report", functools.partial(self._explain, alert))

    def _submit(self, entry: Reply, elapsed_s: float, key: str, job: Callable[[], Reply]) -> None:
        def run() -> None:
            line = entry | {"elapsed_s": elapsed_s, "utc": datetime.now(UTC).isoformat()}
            try:
                line[key] = job()
            except Exception as exc:  # one failed LLM call is a result to report, not a crash
                log.exception("genai job %s failed", entry["kind"])
                line["error"] = f"{type(exc).__name__}: {exc}"
            with self._lock, self._log.open("a") as f:
                f.write(json.dumps(line, default=str) + "\n")

        if self._jobs is None:
            run()
        else:
            self._jobs.put(run)


def _work(jobs: queue.Queue[Callable[[], None]]) -> None:
    """The worker thread: run the LLM jobs one at a time, for the rest of the process."""
    while True:
        jobs.get()()


def build_actor(run_id: str, scenario: str, run_dir: Path) -> GenAIActor:
    """The live actor for one batch run (InfluxDB from .env, the LLM from config/llm.yaml)."""
    conn = InfluxConnection.from_env()
    twin = build_twin(conn, run_id)

    def clock() -> datetime:
        return datetime.now(UTC)

    monitor = build_alert_monitor(influx_rows(conn, run_id), clock)
    if monitor is None:
        raise ValueError("the alert monitor needs data/v1 to fit its detector")
    client = LLMClient.from_config()
    copilot = load_copilot_config(load_yaml("copilot.yaml"))
    backend_box: list[Any] = []  # the backend needs the app, the app's /chat needs the backend

    def chat(question: str) -> Reply:
        return Copilot(client, ToolLayer(backend_box[0]), copilot).ask(question)

    services = Services(
        state=twin.sync.refresh,
        simulator=TwinSimulator(twin.sync.refresh, twin.context),
        sim_enabled=True,  # evaluation run (see the module docstring)
        executor=build_executor(conn, run_id, run_dir / "actions.db"),
        operator_token=None,  # nothing can be approved or applied
        intents=None,
        metrics=influx_metrics(conn, run_id, clock),
        clock=clock,
        alerts=monitor.recent,
        chat=chat,
    )
    send = inprocess_send(create_app(services))
    backend = HttpBackend("http://inprocess", send=send)
    backend_box.append(backend)

    def ask(question: str) -> Reply:
        status, body = send("POST", "/chat", {"question": question})
        if status != HTTPStatus.OK:
            raise RuntimeError(f"POST /chat answered {status}: {body}")
        reply: Reply = body
        return reply

    def rca(alert: Reply) -> Reply:
        return explain(client, backend, ToolLayer(backend), alert, clock=clock)

    onset = disruption(load_scenario(scenario))
    raw = yaml.safe_load(QUESTIONS.read_text())
    questions = [q for q in load_questions(raw) if q.scenario == scenario]
    return GenAIActor(
        questions,
        onset.at_s if onset else None,
        tick_monitor=monitor.tick,
        ask=ask,
        explain=rca,
        log=run_dir / "genai.jsonl",
    )
