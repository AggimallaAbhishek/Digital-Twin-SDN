"""P6.1 operator dashboard (Streamlit), "Blueprint + Sorbet" design
(docs/superpowers/specs/2026-11-09-dashboard-blueprint-sorbet-design.md; the image is
`frontend design images/Final — Blueprint + Sorbet@2x.png`).

    make dashboard     # streamlit on http://127.0.0.1:8501 (needs `make api`)

One live screen with six pages (Overview, Network map, Digital twin, AI copilot, Policies,
History and logs). It talks to the P3.6 API over HTTP only (dashboard/client.py); the operator
token stays in this server process (OPERATOR_TOKEN in .env) and never reaches the browser. Every
string from the API is escaped before it goes into HTML or SVG: reasons, answers and reports can
be written by the LLM (rule L-6). What each panel shows is decided in dashboard/panels.py and
dashboard/views.py (pure, unit-tested); the page modules lay it out (dashboard/README.md lists
them). This file picks the page.
"""

from __future__ import annotations

import streamlit as st

from dashboard.overview import header, overview
from dashboard.pages import copilot_page, digital_twin, history, network_map, policies
from dashboard.theme import CSS
from dashboard.ui import html

TABS = ("Overview", "Network map", "Digital twin", "AI copilot", "Policies", "History and logs")


def main() -> None:
    """The page: style, header, the six pages as pills, then the selected page."""
    st.set_page_config(page_title="Campus Wi-Fi Twin", page_icon="📶", layout="wide")
    html(CSS)
    header()
    with st.container(key="nav"):
        page = (
            st.pills("Page", TABS, default=TABS[0], key="page", label_visibility="collapsed")
            or TABS[0]
        )
    {
        "Overview": overview,
        "Network map": network_map,
        "Digital twin": digital_twin,
        "AI copilot": copilot_page,
        "Policies": policies,
        "History and logs": history,
    }[page]()


if __name__ == "__main__":  # `streamlit run` executes this file as __main__
    main()
