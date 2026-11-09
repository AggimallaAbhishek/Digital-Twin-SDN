"""The "Blueprint + Sorbet" look (docs/superpowers/specs/2026-11-09-dashboard-blueprint-sorbet-
design.md §2): colour and font tokens, measured from the design image, and the page CSS.

Dark blueprint page, pastel "sorbet" cards with a 2 px navy border and a hard offset shadow.
Every colour that carries a status is paired with an icon or a word (never colour alone).
"""

from __future__ import annotations

# ---------------------------------------------------------------- tokens
PAGE = "#26354F"  # the page, under a blueprint grid
GRID = "#2D3C57"  # the grid lines
PANEL = "#1F2D45"  # header cells, the map sheet
RULE = "rgba(199, 202, 208, 0.7)"  # thin header and sheet borders
NAVY = "#0A1F4D"  # card borders, hard shadows, text on light
INK_ON_DARK = "#FFFFFF"
MUTED_ON_DARK = "#C9D2E3"
MUTED = "#4A5875"  # secondary text on light cards
YELLOW = "#FFE066"
CORAL = "#FF8A73"
CORAL_ZONE = "#FFC2B8"
CORAL_HATCH = "#FF9F8C"
MINT = "#BFF5DF"
MINT_BOX = "#B6EBD8"
SKY = "#A9D6FF"
LAVENDER = "#D9CCFF"
INDIGO = "#4B3BD6"
RED = "#E8432F"
RED_TEXT = "#C0301C"
GREEN = "#2F8157"
GREEN_DOT = "#5BE3A8"
GREY_ZONE = "#DDE2EA"
TRACK = "#EEF3FC"  # an empty bar
LINE = "#E3E8F0"  # chart guide lines on a white card
WHITE = "#FFFFFF"

DISPLAY = "'Chakra Petch', 'Hanken Grotesk', system-ui, sans-serif"  # titles, big numbers
BODY = "'Hanken Grotesk', system-ui, sans-serif"
FONTS_URL = (
    "https://fonts.googleapis.com/css2?family=Chakra+Petch:wght@600;700"
    "&family=Hanken+Grotesk:wght@400;500;600;700&display=swap"
)

TOKENS = {  # colour token -> hex, for the bg-<token> CSS classes and the SVG
    "white": WHITE,
    "coral": CORAL,
    "mint": MINT,
    "sky": SKY,
    "yellow": YELLOW,
    "lavender": LAVENDER,
    "grey": GREY_ZONE,
}
ZONE_TOKENS = {  # a zone's sorbet colour while its AP is calm (the design's four zones)
    "lecture hall": "lavender",
    "lab": "mint",
    "corridor": "sky",
    "library": "yellow",
}
ZONE_COLOURS = {zone: TOKENS[token] for zone, token in ZONE_TOKENS.items()}
OTHER_ZONE = WHITE  # a zone the design gives no colour
SHADOW = f"6px 6px 0 {NAVY}"
SHADOW_SM = f"4px 4px 0 {NAVY}"

# ---------------------------------------------------------------- page CSS
CSS = f"""
<style>
@import url('{FONTS_URL}');
html {{ font-size: 16px; }}
html, body, .stApp, .stMarkdown, button, input {{ font-family: {BODY}; }}
.stApp {{ background-color: {PAGE};
  background-image: linear-gradient({GRID} 1px, transparent 1px),
    linear-gradient(90deg, {GRID} 1px, transparent 1px);
  background-size: 24px 24px; color: {INK_ON_DARK}; }}
[data-testid="stHeader"] {{ background: transparent; }}
[data-testid="stMainBlockContainer"] {{ padding: 1.6rem 2.2rem 3rem; max-width: 1920px; }}
/* no fading while a fragment re-runs every few seconds */
[data-stale="true"], .stale-element {{ opacity: 1 !important; filter: none !important;
  transition: none !important; }}
.stMarkdown p, .stMarkdown li {{ color: inherit; }}
h1, h2, h3 {{ font-family: {DISPLAY}; }}

/* ---- header strip ---- */
.hdr {{ display: grid; grid-template-columns: 2.1fr 1.05fr 0.95fr 1.15fr;
  border: 1.5px solid {RULE};
  background: {PANEL}; margin-bottom: 1.1rem; }}
.hdr > div {{ padding: 18px 22px; border-right: 1.5px solid {RULE}; display: flex;
  flex-direction: column; justify-content: center; min-width: 0; }}
.hdr > div:last-child {{ border-right: 0; }}
.hdr .brand {{ flex-direction: row; align-items: center; justify-content: flex-start;
  gap: 18px; }}
.hdr .logo {{ width: 60px; height: 60px; flex: none; border-radius: 50%; background: {YELLOW};
  box-shadow: 3px 3px 0 {NAVY}; display: flex; align-items: center; justify-content: center; }}
.hdr .name {{ font-family: {DISPLAY}; font-weight: 700; font-size: 2.05rem; line-height: 1.05;
  color: {INK_ON_DARK}; }}
.hdr .sub {{ color: {MUTED_ON_DARK}; font-size: 1rem; }}
.hdr .k {{ color: {MUTED_ON_DARK}; font-size: .85rem; }}
.hdr .v {{ font-weight: 700; font-size: 1.3rem; color: {INK_ON_DARK}; }}
.hdr .clock {{ font-family: {DISPLAY}; font-weight: 700; font-size: 2rem; line-height: 1; }}
.hdr .clock small {{ font-size: 1rem; color: {MUTED_ON_DARK}; font-weight: 600; }}
.live-pill {{ display: inline-flex; align-items: center; gap: 7px; background: {YELLOW};
  color: {NAVY}; border-radius: 999px; padding: 4px 14px; font-weight: 700; font-size: .95rem;
  box-shadow: 3px 3px 0 {NAVY}; width: fit-content; margin-bottom: 8px; }}
.live-pill i {{ width: 9px; height: 9px; border-radius: 50%; background: {RED}; }}
.conn {{ display: flex; gap: 9px; align-items: baseline; color: {INK_ON_DARK}; font-size: .95rem; }}
.conn i {{ width: 9px; height: 9px; border-radius: 50%; flex: none; }}
.conn.ok i {{ background: {GREEN_DOT}; }} .conn.wait i {{ background: {YELLOW}; }}
.conn.down i {{ background: {RED}; }}

/* ---- tabs: st.pills as the design's pill buttons ---- */
.st-key-nav [data-testid="stButtonGroup"] {{ gap: 14px; flex-wrap: wrap; }}
.st-key-nav button {{ background: transparent !important; color: {INK_ON_DARK} !important;
  border: 1.5px solid {RULE} !important; border-radius: 12px !important;
  padding: 10px 20px !important;
  min-height: 46px; font-weight: 700 !important; }}
.st-key-nav button p {{ font-size: 1.05rem !important; font-weight: 700 !important; }}
.st-key-nav button[kind="pillsActive"], .st-key-nav button[aria-checked="true"] {{
  background: {YELLOW} !important; color: {NAVY} !important; border-color: {YELLOW} !important;
  box-shadow: {SHADOW_SM}; }}

/* ---- story strip ---- */
.steps {{ display: grid; grid-template-columns: repeat(6, 1fr); gap: 16px; margin: 1.1rem 0; }}
.step {{ border-radius: 12px; padding: 11px 16px; min-height: 66px; }}
.step b {{ display: block; font-size: 1.02rem; }}
.step span {{ font-size: .85rem; }}
.step.done {{ background: {MINT}; color: {NAVY}; border: 2px solid {NAVY};
  box-shadow: {SHADOW_SM}; }}
.step.now {{ background: {CORAL}; color: {NAVY}; border: 2px solid {NAVY};
  box-shadow: {SHADOW_SM}; }}
.step.now span {{ font-weight: 700; }}
.step.next {{ border: 2px dashed {RULE}; color: {INK_ON_DARK}; }}
.step.next span {{ color: {MUTED_ON_DARK}; }}

/* ---- sorbet cards ---- */
.card {{ border: 2px solid {NAVY}; border-radius: 18px; box-shadow: {SHADOW}; color: {NAVY};
  padding: 20px 24px; }}
.card h3 {{ font-family: {DISPLAY}; font-weight: 700; font-size: 1.55rem; margin: 0 0 14px;
  color: {NAVY}; padding: 0; }}
.bg-white {{ background: {WHITE}; }} .bg-coral {{ background: {CORAL}; }}
.bg-mint {{ background: {MINT}; }} .bg-sky {{ background: {SKY}; }}
.bg-yellow {{ background: {YELLOW}; }} .bg-lavender {{ background: {LAVENDER}; }}
.bg-grey {{ background: {GREY_ZONE}; }}
.hero {{ display: grid; grid-template-columns: 2.05fr 1fr 1fr 1fr; gap: 22px;
  margin-bottom: 1.6rem; }}
.hero .status {{ display: flex; gap: 18px; align-items: center; min-height: 104px; }}
.hero .icon {{ width: 54px; height: 54px; border-radius: 50%; background: {NAVY}; flex: none;
  display: flex; align-items: center; justify-content: center; color: {YELLOW}; font-size: 1.5rem;
  }}
.hero .eye {{ font-weight: 700; font-size: .98rem; }}
.hero .head {{ font-family: {DISPLAY}; font-weight: 700; font-size: 1.85rem; line-height: 1.15; }}
.tile .num {{ font-family: {DISPLAY}; font-weight: 700; font-size: 2.9rem; line-height: 1; }}
.tile .lbl {{ font-weight: 700; font-size: 1rem; margin-top: 6px; }}

/* Streamlit containers keyed card-<colour>-…: the cards that hold widgets */
[class*="st-key-card-"] {{ border: 2px solid {NAVY}; border-radius: 18px; box-shadow: {SHADOW};
  padding: 20px 24px; color: {NAVY}; }}
[class*="st-key-card-white"] {{ background: {WHITE}; }}
[class*="st-key-card-lavender"] {{ background: {LAVENDER}; }}
[class*="st-key-card-"] .stMarkdown, [class*="st-key-card-"] p {{ color: {NAVY}; }}
.st-key-sheet {{ background: {PANEL}; border: 1.5px solid {RULE}; padding: 22px 26px; }}
.sheet-head {{ display: flex; justify-content: space-between; align-items: center; gap: 16px;
  flex-wrap: wrap; margin-bottom: 8px; }}
.sheet-head h3 {{ font-family: {DISPLAY}; font-weight: 700; font-size: 1.55rem;
  color: {INK_ON_DARK};
  margin: 0; padding: 0; }}
.legend {{ display: flex; gap: 18px; flex-wrap: wrap; font-size: .92rem; color: {INK_ON_DARK}; }}
.legend span {{ display: inline-flex; align-items: center; gap: 7px; }}
.legend .dot {{ width: 11px; height: 11px; border-radius: 50%; border: 2px solid {NAVY}; }}
.legend .ring {{ width: 13px; height: 13px; border-radius: 50%;
  border: 1.5px dashed {INK_ON_DARK}; }}
svg.plan, svg.bars {{ width: 100%; height: auto; display: block; }}
svg text {{ font-family: {BODY}; }}
svg .disp {{ font-family: {DISPLAY}; font-weight: 700; }}

/* ---- proposal ---- */
.eyebrow {{ color: {INDIGO}; font-weight: 700; font-size: 1rem; }}
.big-title {{ font-family: {DISPLAY}; font-weight: 700; font-size: 1.75rem; line-height: 1.15;
  margin: 2px 0 16px; color: {NAVY}; }}
.twin-boxes {{ display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-bottom: 18px; }}
.twin-box {{ border: 2px solid {NAVY}; border-radius: 14px; padding: 12px 16px;
  background: {MINT_BOX}; }}
.twin-box.bad {{ background: {CORAL_ZONE}; }}
.twin-box .k {{ font-weight: 700; font-size: .9rem; }}
.twin-box .n {{ font-family: {DISPLAY}; font-weight: 700; font-size: 2.15rem; line-height: 1.1; }}
.twin-box .s {{ font-size: .9rem; }}
.result {{ border: 2px solid {NAVY}; border-radius: 14px; padding: 12px 16px; font-weight: 700; }}
.progress {{ height: 12px; border: 2px solid {NAVY}; border-radius: 999px; background: {TRACK};
  overflow: hidden; margin-top: 8px; }}
.progress i {{ display: block; height: 100%; background: {INDIGO}; }}

/* buttons, keyed btn-<style>-… */
[class*="st-key-btn-"] button {{ border: 2px solid {NAVY} !important;
  border-radius: 12px !important;
  min-height: 52px; width: 100%; color: {NAVY} !important; background: {WHITE} !important; }}
[class*="st-key-btn-"] button p {{ font-family: {DISPLAY}; font-weight: 700 !important;
  font-size: 1.15rem !important; }}
[class*="st-key-btn-indigo"] button {{ background: {INDIGO} !important; color: {WHITE} !important;
  box-shadow: {SHADOW_SM}; }}
[class*="st-key-btn-yellow"] button {{ background: {YELLOW} !important; box-shadow: {SHADOW_SM}; }}
[class*="st-key-btn-"] button:hover {{ transform: translate(-1px, -1px); }}
[class*="st-key-btn-"] button:focus-visible {{ outline: 3px solid {INDIGO}; outline-offset: 3px; }}

/* ---- copilot ---- */
.copilot-head {{ display: flex; justify-content: space-between; align-items: center;
  margin-bottom: 12px; }}
.copilot-head h3 {{ margin: 0 !important; }}
.online {{ display: inline-flex; align-items: center; gap: 8px; font-weight: 700; }}
.online i {{ width: 13px; height: 13px; border-radius: 50%; border: 2px solid {NAVY}; }}
.online.ok i {{ background: {GREEN}; }} .online.off i {{ background: {RED}; }}
.online.idle i {{ background: #9AA4B5; }}
.bubble {{ border: 2px solid {NAVY}; border-radius: 14px; padding: 12px 16px; margin: 0 0 12px;
  background: {WHITE}; font-size: 1.02rem; line-height: 1.45; overflow-wrap: anywhere; }}
.bubble.you {{ background: {NAVY}; color: {WHITE}; margin-left: 2.2rem;
  border-radius: 14px 14px 4px 14px; }}
.bubble .chip {{ display: inline-block; font-size: .72rem; font-weight: 700;
  text-transform: uppercase;
  letter-spacing: .05em; border-radius: 6px; padding: 1px 7px; margin-bottom: 6px;
  background: {LAVENDER}; color: {NAVY}; }}
.bubble .ok {{ color: {GREEN}; font-weight: 700; margin-top: 8px; }}
.bubble .no {{ color: {RED_TEXT}; font-weight: 700; margin-top: 8px; }}
.bubble .tools {{ color: {MUTED}; font-size: .85rem; margin-top: 6px; }}
[class*="st-key-ask-"] [data-testid="stForm"] {{ border: 0; padding: 0; }}
/* the copilot card stretches to the floor plan's height, its input at the bottom (design) */
/* (the column already stretches; the card's own layout wrapper is what must grow) */
[data-testid="stLayoutWrapper"]:has(> .st-key-card-lavender-copilot) {{ flex: 1 1 auto; }}
.st-key-card-lavender-copilot {{ height: 100%; justify-content: space-between; }}
[class*="st-key-ask-"] input {{ border: 2px solid {NAVY} !important; border-radius: 14px !important;
  background: {WHITE} !important; color: {NAVY} !important; min-height: 52px; font-size: 1rem; }}
[class*="st-key-ask-"] [data-testid="stTextInputRootElement"] {{ border: 0 !important;
  background: transparent !important; }}
[class*="st-key-ask-"] [data-testid="stFormSubmitButton"] button {{ background: {NAVY} !important;
  color: {YELLOW} !important; border-radius: 14px !important; min-height: 52px; width: 100%;
  border: 2px solid {NAVY} !important; }}
[class*="st-key-ask-"] [data-testid="stFormSubmitButton"] button p {{ color: {YELLOW} !important;
  font-size: 1.3rem; }}

/* ---- bottom row ---- */
.aprow {{ display: grid; grid-template-columns: 64px 1fr 78px; gap: 14px; align-items: center;
  margin-bottom: 16px; }}
.chip-ap {{ border: 2px solid {NAVY}; border-radius: 12px; height: 54px; display: flex;
  align-items: center; justify-content: center; font-weight: 700; font-size: 1.05rem; }}
.aprow .what {{ font-size: .98rem; margin-bottom: 6px; }}
.bar {{ height: 16px; border: 2px solid {NAVY}; border-radius: 999px; background: {TRACK};
  overflow: hidden; }}
.bar i {{ display: block; height: 100%; background: {INDIGO}; }}
.bar i.hot {{ background: repeating-linear-gradient(135deg, {RED} 0 8px, {CORAL} 8px 16px); }}
.pct {{ font-family: {DISPLAY}; font-weight: 700; font-size: 1.45rem; text-align: right; }}
.pct.hot {{ color: {RED_TEXT}; }}
.ev {{ display: grid; grid-template-columns: 92px 1fr; gap: 14px; margin-bottom: 12px; }}
.ev .t {{ border: 2px solid {NAVY}; border-radius: 999px; text-align: center; font-weight: 700;
  font-size: .95rem; padding: 4px 0; height: fit-content; background: {WHITE}; }}
.ev .t.coral {{ background: {CORAL}; }} .ev .t.lavender {{ background: {LAVENDER}; }}
.ev .t.yellow {{ background: {YELLOW}; }} .ev .t.mint {{ background: {MINT}; }}
.ev b {{ display: block; font-size: 1.02rem; }}
.ev span {{ color: {MUTED}; font-size: .95rem; }}
.keys {{ display: flex; gap: 16px; flex-wrap: wrap; font-size: .95rem; margin-bottom: 10px; }}
.keys span {{ display: inline-flex; align-items: center; gap: 7px; }}
.keys i {{ width: 15px; height: 15px; border: 2px solid {NAVY}; border-radius: 4px; }}
.empty {{ color: {MUTED}; font-size: 1rem; line-height: 1.5; }}
.on-dark {{ color: {INK_ON_DARK}; }}
table.grid {{ width: 100%; border-collapse: collapse; color: {NAVY}; font-size: .95rem; }}
table.grid th {{ text-align: left; font-weight: 700; border-bottom: 2px solid {NAVY};
  padding: 6px 8px; }}
table.grid td {{ border-bottom: 1px solid #D5DBE6; padding: 6px 8px; vertical-align: top; }}
table.grid code {{ color: {NAVY}; background: {TRACK}; }}
@media (prefers-reduced-motion: reduce) {{ * {{ transition: none !important;
  animation: none !important; }} }}
</style>
"""
