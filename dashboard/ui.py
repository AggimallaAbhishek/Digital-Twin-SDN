"""Small markup helpers shared by the dashboard's pages (every API string escaped first)."""

from __future__ import annotations

from typing import Any

import streamlit as st

from dashboard.views import safe_html


def html(markup: str, where: Any = st) -> None:  # Any: st or a container
    """Markup built here (every API string in it already escaped)."""
    where.markdown(markup, unsafe_allow_html=True)


def table_row(*cells: str) -> str:
    """One table row of cells already escaped."""
    return "<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>"


def table(head: tuple[str, ...], rows: str, empty: str = "Nothing yet.") -> str:
    """A grid table: a header row, then `rows` (or one row saying it is empty)."""
    header_row = "<tr>" + "".join(f"<th>{h}</th>" for h in head) + "</tr>"
    body = rows or f'<tr><td colspan="{len(head)}">{empty}</td></tr>'
    return f'<table class="grid">{header_row}{body}</table>'


def card(title: str, body: str, colour: str = "white", spaced: bool = True) -> str:
    """A sorbet card with its title; `spaced` adds the gap above it."""
    gap = ' style="margin-top:22px"' if spaced else ""
    return f'<div class="card bg-{colour}"{gap}><h3>{safe_html(title)}</h3>{body}</div>'
