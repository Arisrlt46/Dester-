"""DESTER dashboard: shared visual design tokens.

Pure constants -- no Streamlit or Plotly calls happen here. Everything in
this module is either a color/token dict, a Plotly template object, or a
CSS string, all consumed by app.py and charts.py.
"""

import plotly.graph_objects as go

# ---------------------------------------------------------------- Palette
# Two accent hues (teal = primary/"go"-leaning, amber = secondary/"no-go"-
# leaning) plus a neutral gray scale. Deliberately no red/green -- verdicts
# read as teal/amber, not a traffic light. Contrast-checked: #111827 text on
# both #0891b2 and #f59e0b clears WCAG AA (4.8:1 and 8.3:1 respectively);
# white text on amber does not (2.2:1), so cell/badge text stays dark ink on
# both fills rather than switching per color.
COLORS = {
    "teal": "#0891b2",
    "teal_dark": "#0e7490",
    "amber": "#f59e0b",
    "amber_dark": "#b45309",
    # Third categorical hue, added for the three-market comparison charts
    # (AUS-SLC/ATL-SAT/MIA-SEA). Validated alongside teal+amber via the
    # dataviz skill's palette validator (lightness band, chroma floor, CVD
    # separation all pass) -- still no red/green.
    "violet": "#7c3aed",
    "bg": "#f9fafb",
    "surface": "#ffffff",
    "border": "#e5e7eb",
    "text_secondary": "#374151",
    "text_primary": "#111827",
}

# Light -> dark, single hue (teal). Used for magnitude encoding (the feed
# waterfall gradient) -- never a rainbow, never used for identity.
TEAL_SCALE = [
    "#cffafe",
    "#a5f3fc",
    "#67e8f9",
    "#22d3ee",
    "#06b6d4",
    "#0891b2",
    "#0e7490",
    "#155e75",
]

FONT_FAMILY = (
    "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, "
    "sans-serif"
)


def teal_gradient(n):
    """n evenly-spaced shades along TEAL_SCALE, light to dark. n=1 returns
    the base teal."""
    if n <= 1:
        return [COLORS["teal"]]
    span = len(TEAL_SCALE) - 1
    return [TEAL_SCALE[round(i * span / (n - 1))] for i in range(n)]


# ---------------------------------------------------------------- Plotly
PLOTLY_TEMPLATE = go.layout.Template()
PLOTLY_TEMPLATE.layout = go.Layout(
    font=dict(family=FONT_FAMILY, color=COLORS["text_secondary"], size=13),
    title=dict(font=dict(family=FONT_FAMILY, color=COLORS["text_primary"], size=17)),
    paper_bgcolor=COLORS["surface"],
    plot_bgcolor=COLORS["surface"],
    colorway=[COLORS["teal"], COLORS["amber"]],
    xaxis=dict(
        gridcolor=COLORS["border"],
        zerolinecolor=COLORS["border"],
        linecolor=COLORS["border"],
        title=dict(font=dict(color=COLORS["text_secondary"])),
    ),
    yaxis=dict(
        gridcolor=COLORS["border"],
        zerolinecolor=COLORS["border"],
        linecolor=COLORS["border"],
        title=dict(font=dict(color=COLORS["text_secondary"])),
    ),
    legend=dict(font=dict(color=COLORS["text_secondary"])),
    margin=dict(t=60, l=60, r=30, b=50),
)

# ---------------------------------------------------------------- CSS
# Injected once via st.markdown(..., unsafe_allow_html=True) right after
# st.set_page_config. Targets Streamlit's own emotion-generated DOM via its
# stable data-testid hooks (verified against the installed streamlit==1.50
# frontend bundle), not guessed class names.
CSS_INJECTION = f"""
<style>
.stApp {{
    background-color: {COLORS["bg"]};
}}

/* ---------- Hero ---------- */
.dester-hero-title {{
    font-family: {FONT_FAMILY};
    font-size: 2.6rem;
    font-weight: 700;
    color: {COLORS["text_primary"]};
    letter-spacing: -0.02em;
    margin-bottom: 0.1rem;
}}
.dester-hero-subtitle {{
    font-family: {FONT_FAMILY};
    font-size: 1.05rem;
    color: {COLORS["text_secondary"]};
    margin-bottom: 0.3rem;
}}
.dester-hero-context {{
    font-family: {FONT_FAMILY};
    font-size: 0.9rem;
    color: {COLORS["teal_dark"]};
    font-weight: 600;
    margin-bottom: 1.1rem;
}}

/* ---------- Metric cards ---------- */
div[data-testid="stMetric"] {{
    background-color: {COLORS["surface"]};
    border: 1px solid {COLORS["border"]};
    border-radius: 10px;
    padding: 1rem 1.1rem;
    box-shadow: 0 1px 2px rgba(17, 24, 39, 0.04);
}}
div[data-testid="stMetricLabel"] {{
    color: {COLORS["text_secondary"]};
}}
div[data-testid="stMetricValue"] {{
    color: {COLORS["text_primary"]};
}}

/* ---------- Narrative / info cards ---------- */
/* Replaces Streamlit's default heavy-blue st.info() fill with a subtle,
   bordered neutral card with a teal accent rule -- applies to every
   st.info() box (narrative + the Custom Market disclaimer alike) for a
   consistent, calmer read throughout, not just the narrative block. */
div[data-testid="stAlertContainer"] {{
    background-color: {COLORS["surface"]} !important;
    border: 1px solid {COLORS["border"]} !important;
    border-left: 4px solid {COLORS["teal"]} !important;
    border-radius: 8px !important;
    color: {COLORS["text_secondary"]} !important;
}}
div[data-testid="stAlertContainer"] p {{
    color: {COLORS["text_secondary"]} !important;
}}

/* ---------- Sidebar grouping ---------- */
section[data-testid="stSidebar"] {{
    background-color: {COLORS["surface"]};
    border-right: 1px solid {COLORS["border"]};
}}
section[data-testid="stSidebar"] h3 {{
    font-size: 0.78rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: {COLORS["text_secondary"]};
    margin-top: 1.1rem;
    margin-bottom: 0.4rem;
    border-bottom: 1px solid {COLORS["border"]};
    padding-bottom: 0.3rem;
}}

/* ---------- Sliders (v2c: were rendering in Streamlit's default red) --- */
div[data-testid="stSlider"] div[role="slider"] {{
    background-color: {COLORS["teal"]} !important;
    border-color: {COLORS["teal"]} !important;
}}
div[data-testid="stSlider"] div[role="slider"]:hover,
div[data-testid="stSlider"] div[role="slider"]:focus,
div[data-testid="stSlider"] div[role="slider"]:active {{
    background-color: {COLORS["teal_dark"]} !important;
    border-color: {COLORS["teal_dark"]} !important;
    box-shadow: 0 0 0 0.2rem rgba(8, 145, 178, 0.25) !important;
}}
/* The filled portion of the track (baseui's InnerTrack) isn't individually
   data-testid'd, so it's targeted structurally under the slider's own
   data-baseweb="slider" root. */
div[data-testid="stSlider"] div[data-baseweb="slider"] > div > div {{
    background: {COLORS["teal"]} !important;
}}
div[data-testid="stSlider"] [data-testid="stSliderTickBar"],
div[data-testid="stSlider"] [data-testid="stSliderThumbValue"] {{
    color: {COLORS["text_secondary"]} !important;
}}

/* ---------- Tabs ---------- */
div[data-testid="stTabs"] [data-baseweb="tab-highlight"] {{
    background-color: {COLORS["teal"]} !important;
}}
div[data-testid="stTabs"] [data-baseweb="tab-border"] {{
    background-color: {COLORS["border"]} !important;
}}
button[data-testid="stTab"] p {{
    color: {COLORS["text_secondary"]};
    font-weight: 500;
}}
button[data-testid="stTab"][aria-selected="true"] p {{
    color: {COLORS["text_primary"]};
    font-weight: 700;
}}

/* ---------- Hero visibility (v2c) --------------------------------------
   Streamlit's default main-content top padding is 6rem, well clear of the
   3.75rem-tall absolutely-positioned header -- but that's a lot of empty
   space before the hero's first line ever appears. Tightened to just
   clear the header (3.75rem) plus a small margin, so "DESTER" and the
   "Currently analyzing" line sit above the fold instead of scrolled past
   it. */
div[data-testid="stMainBlockContainer"] {{
    padding-top: 4.5rem !important;
}}
</style>
"""
