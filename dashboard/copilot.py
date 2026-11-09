"""The proposal card and the AI copilot (questions and intents) of the dashboard."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

import streamlit as st

from dashboard.cards import bubble, intent_body
from dashboard.client import ApiError
from dashboard.data import OPERATOR, SHOWN_CHATS, client, live, now, read_live, watch, watch_s
from dashboard.panels import (
    Live,
    Proposal,
    intent_view,
    proposal_view,
    route,
    still_waiting,
)
from dashboard.ui import html
from dashboard.views import (
    md_literal,
    plain_action,
    rich_html,
    safe_html,
    shorten,
    verdict_word,
)

# ---------------------------------------------------------------- proposal card


APPROVE_WORDS = {"approve": "Approve", "apply": "Apply now"}


def proposal_card(snap: Live, start: datetime | None) -> None:
    """The change that matters most now, with the operator's buttons when it waits."""
    view = proposal_view(snap, now(), watch(), start)
    if view is None:
        html(
            '<div class="eyebrow">Optimiser</div><div class="big-title">No change proposed</div>'
            '<p class="empty">The optimiser proposes one when an access point is congested; '
            "the twin checks it before anything changes.</p>"
        )
        return
    html(
        f'<div class="eyebrow">{safe_html(view.eyebrow)}</div>'
        f'<div class="big-title">{safe_html(view.title)}</div>{twin_boxes(view)}'
    )
    if view.kind == "waiting":
        decide_buttons(view)
    elif view.kind == "watching":
        html(f'<div class="progress"><i style="width:{view.progress:.0%}"></i></div>')
    elif view.note:
        tone = "bg-mint" if view.note.startswith("✓") else "bg-coral"
        html(f'<div class="result {tone}">{safe_html(view.note)}</div>')


def twin_boxes(view: Proposal) -> str:
    """The two "Twin predicts" boxes (latency, loss); coral when the twin rejected it."""
    if view.latency is None or view.loss is None:
        return ""
    css = "twin-box" if view.accepted else "twin-box bad"

    def box(label: str, after: float, before: float, unit: str, fmt: str) -> str:
        now_, was = fmt.format(after) + unit, fmt.format(before) + unit
        trend = "no change" if now_ == was else f"{'down' if after < before else 'up'} from {was}"
        return (
            f'<div class="{css}"><div class="k">Twin predicts {label}</div>'
            f'<div class="n">{now_}</div><div class="s">{trend}</div></div>'
        )

    return (
        '<div class="twin-boxes">'
        + box("latency", *view.latency, " ms", "{:.0f}")
        + box("loss", *view.loss, "%", "{:.1f}")
        + "</div>"
    )


# (label, style in the button's key: btn-<colour>-…, on_click, its args)
ButtonSpec = tuple[str, str, Callable[..., None], tuple[Any, ...]]


def decide_buttons(view: Proposal) -> None:
    """Deny (asked once more: a denied change can never be applied) and Approve / Apply."""
    action_id = view.action_id
    confirming = st.session_state.get("deny") == action_id
    if confirming:
        html('<p class="empty"><b>Deny this change?</b> It can\'t be applied afterwards.</p>')
    left: ButtonSpec
    right: ButtonSpec
    if confirming:
        left = ("Yes, deny", "white-yes", decide, (action_id, "deny", view.title))
        right = ("Keep it", "indigo-keep", ask_deny, (None,))
    else:
        go = APPROVE_WORDS.get(str(view.next_step), "Approve")
        if view.next_step == "approve" and view.title.startswith("Move "):
            go = "Approve move"
        left = ("Deny", "white-deny", ask_deny, (action_id,))
        right = (go, "indigo-go", decide, (action_id, str(view.next_step), view.title))
    for column, (label, style, on_click, args) in zip(
        st.columns([1, 1.6]), (left, right), strict=True
    ):
        column.button(label, key=f"btn-{style}-{action_id}", on_click=on_click, args=args)


def ask_deny(action_id: str | None) -> None:
    """Ask once more before a Deny (None: the operator kept the change)."""
    st.session_state["deny"] = action_id


DONE = {"approve": "Approved", "apply": "Applied", "deny": "Denied"}  # the toast after a step


def decide(action_id: str, step: str, what: str) -> None:
    """Send the operator's step to the API (the token stays in this process)."""
    st.session_state["deny"] = None
    try:
        client().operator(action_id, step, by=OPERATOR)
        st.toast(f"{DONE.get(step, step)}: {md_literal(what)}")
    except ApiError as exc:
        st.toast(md_literal(exc))
    read_live.clear()


# ---------------------------------------------------------------- AI copilot


def copilot_card(shown: int | None = SHOWN_CHATS, key: str = "ov") -> None:
    """The copilot: the latest exchanges, then one box for a question or an intent."""
    status = st.session_state.get("llm")
    dot = {"ok": ("ok", "Online"), "off": ("off", "Offline")}.get(str(status), ("idle", "Ready"))
    with st.container(key=f"chatlog-{key}"):  # the card spaces this and the box apart (CSS)
        html(
            '<div class="copilot-head"><h3>AI copilot</h3>'
            f'<span class="online {dot[0]}"><i></i>{dot[1]}</span></div>'
        )
        history: list[dict[str, Any]] = st.session_state.setdefault("chat", [])
        first = 0 if shown is None else max(0, len(history) - shown)
        if not history:
            html(
                '<p class="empty">Ask why something is happening, or say what you want: "Give '
                'video calls in the lecture hall priority." The twin checks every change first.</p>'
            )
        for n in range(first, len(history)):
            exchange(n, history[n], key)
    with (
        st.container(key=f"ask-{key}"),
        st.form(f"ask-form-{key}", clear_on_submit=True, border=False),
    ):
        text_col, send_col = st.columns([5, 1])
        text = text_col.text_input(
            "Ask or tell",
            placeholder="Describe an intent or ask a question",
            label_visibility="collapsed",
        )
        if send_col.form_submit_button("➤", help="Send") and text.strip():
            send(text.strip())


def send(text: str) -> None:
    """A question to the copilot, anything else to the intent engine (panels.route)."""
    kind = route(text)
    path, body = ("/chat", {"question": text}) if kind == "ask" else ("/intents", {"text": text})
    with st.spinner("The copilot is looking at the network…"):
        try:
            reply = client().post(path, body)
            st.session_state["llm"] = "ok"
        except ApiError as exc:
            reply = {"error": str(exc)}
            if "language model" in str(exc):
                st.session_state["llm"] = "off"
    st.session_state.setdefault("chat", []).append(
        {"kind": kind, "text": text, "reply": reply, "applied": False}
    )
    read_live.clear()


def exchange(n: int, item: dict[str, Any], key: str) -> None:
    """One exchange: the operator's words, then the copilot's reply (and its button)."""
    html(f'<div class="bubble you">{safe_html(item["text"])}</div>')
    reply = item["reply"]
    chip = "asked" if item["kind"] == "ask" else "intent"
    if "error" in reply and item["kind"] == "ask":
        html(bubble(chip, f"The copilot could not answer: {safe_html(reply['error'])}"))
        return
    if item["kind"] == "ask":
        tools = sorted({e["tool"] for e in reply.get("evidence", [])})
        used = f'<div class="tools">used {safe_html(", ".join(tools))}</div>' if tools else ""
        tips = "".join(
            '<div class="tools">suggested: '
            f"{safe_html(plain_action(s['action']))} · twin {safe_html(verdict_word(s['verdict']))}"
            "</div>"
            for s in reply.get("suggested_actions", [])
        )
        html(bubble(chip, rich_html(shorten(reply.get("answer", ""))) + used + tips))
        return
    view = intent_view(reply)
    html(bubble(chip, intent_body(view)))
    snap = live()
    waiting = snap is not None and still_waiting(view.applicable, snap.actions)
    if waiting and not item["applied"]:  # not once applied, denied or decided elsewhere
        st.button(
            "Create and apply policy",
            key=f"btn-yellow-policy-{key}-{n}",
            on_click=apply_policy,
            args=(n, view.applicable),
        )
    elif item["applied"]:
        watching = f"✓ Applied · the executor watches it for {watch_s()} s"
        html(f'<div class="result bg-mint">{watching}</div>')


def apply_policy(n: int, action_ids: tuple[str, ...]) -> None:
    """The operator's yes for an intent's twin-accepted set: approve each action that needs
    it, then apply the set (the API applies the whole verified group)."""
    api = client()
    try:
        records = {r["action_id"]: r for r in api.get("/actions")["actions"]}
        for action_id in action_ids:
            r = records.get(action_id)
            if r and r["status"] == "verified" and r["verdict"].get("needs_approval"):
                api.operator(action_id, "approve", by=OPERATOR)
        api.operator(action_ids[0], "apply", by=OPERATOR)
        st.session_state["chat"][n]["applied"] = True
        st.toast("Applied: the policy's changes")
    except ApiError as exc:
        st.toast(md_literal(exc))
    read_live.clear()
