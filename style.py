"""Look of the app: a light and a dark palette, small HTML pills, and the few lines of CSS that give keyed
containers a card style.

Shared by every page. Charts live in charts.py.
"""
import base64
import colorsys
import html
import re
from types import SimpleNamespace

import streamlit as st

from insights import band


def hsl(h, s, l):  # noqa: E741  the palette is written in HSL
    r, g, b = colorsys.hls_to_rgb(h / 360, l / 100, s / 100)
    return f"#{round(r * 255):02x}{round(g * 255):02x}{round(b * 255):02x}"


def rgba(hex_color, alpha):
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return f"rgba({r},{g},{b},{alpha})"


# Compared candidates keep one colour each.
SERIES = [hsl(252, 75, 60), hsl(205, 70, 48), hsl(160, 50, 40), "#e07229", "#dd3c5c", "#c19615"]

LIGHT = SimpleNamespace(
    dark=False, primary=hsl(228, 90, 62), ink=hsl(240, 15, 15), muted=hsl(240, 10, 45), grid=hsl(240, 25, 91),
    card="#ffffff", page=hsl(240, 45, 98.5), soft=hsl(240, 30, 95.5),
    shadow="0 1px 2px rgba(40,30,80,.04), 0 12px 28px -16px rgba(40,30,80,.16)",
    # score bands 0-4: weak, low, mid, good, strong (background, text)
    band_bg=[hsl(350, 80, 93), hsl(30, 90, 89), hsl(48, 92, 86), hsl(155, 55, 88), hsl(152, 60, 84)],
    band_fg=[hsl(348, 55, 38), hsl(26, 60, 33), hsl(40, 65, 28), hsl(160, 45, 25), hsl(158, 50, 22)],
    # pastel pairs (background, text)
    mint=(hsl(160, 55, 90), hsl(162, 45, 26)), lemon=(hsl(48, 90, 88), hsl(42, 60, 30)),
    rose=(hsl(350, 80, 93), hsl(348, 55, 40)), sky=(hsl(205, 80, 91), hsl(207, 55, 32)),
    sand=(hsl(38, 85, 88), hsl(38, 55, 30)), lavender=(hsl(252, 70, 93), hsl(252, 45, 40)),
    peach=(hsl(24, 90, 91), hsl(22, 55, 35)), grey=(hsl(240, 30, 95.5), hsl(240, 10, 40)),
)
DARK = SimpleNamespace(
    dark=True, primary=hsl(228, 94, 67), ink=hsl(240, 10, 96), muted=hsl(240, 4, 56), grid=hsl(240, 6, 16),
    card=hsl(240, 7, 8), page=hsl(240, 10, 4), soft=hsl(240, 6, 12),
    shadow="0 1px 2px rgba(0,0,0,.3), 0 12px 28px -16px rgba(0,0,0,.6)",
    band_bg=[hsl(348, 30, 23), hsl(28, 35, 21), hsl(46, 35, 20), hsl(158, 30, 21), hsl(156, 35, 24)],
    band_fg=[hsl(348, 60, 80), hsl(28, 60, 76), hsl(46, 60, 74), hsl(158, 45, 74), hsl(152, 50, 78)],
    mint=(hsl(158, 30, 21), hsl(158, 45, 74)), lemon=(hsl(46, 35, 20), hsl(46, 60, 74)),
    rose=(hsl(348, 30, 23), hsl(348, 60, 80)), sky=(hsl(205, 35, 22), hsl(205, 60, 78)),
    sand=(hsl(36, 35, 21), hsl(36, 60, 76)), lavender=(hsl(252, 30, 25), hsl(252, 70, 82)),
    peach=(hsl(24, 35, 21), hsl(24, 60, 76)), grey=(hsl(240, 6, 15), hsl(240, 5, 70)),
)
STATUS = {"met": "mint", "partial": "lemon", "missing": "rose"}  # requirement verdict -> pastel pair


# st.context.theme can be stale after the viewer switches theme, and the switch does not rerun the app
# (streamlit#11920), so every custom colour kept the old palette. This reports the theme the page really shows.
_THEME_JS = """
export default function({ data, setTriggerValue }) {
    const shown = () => {
        const [r, g, b] = getComputedStyle(document.querySelector('.stApp')).backgroundColor.match(/\\d+/g).map(Number);
        return 0.299 * r + 0.587 * g + 0.114 * b < 128 ? 'dark' : 'light';
    };
    let last = data;
    const id = setInterval(() => { const now = shown(); if (now !== last) { last = now; setTriggerValue('theme', now); } }, 300);
    return () => clearInterval(id);
}"""
_theme_watch = st.components.v2.component("theme_watch", js=_THEME_JS)


def palette():
    return DARK if (st.session_state.get("theme") or st.context.theme.type) == "dark" else LIGHT


def watch_theme(P):
    """Redraw with the right palette when the viewer switches between light and dark."""
    with st.sidebar:
        shown = _theme_watch(key="theme_watch", data="dark" if P.dark else "light", on_theme_change=lambda: None).theme
    if shown and shown != ("dark" if P.dark else "light"):
        st.session_state["theme"] = shown
        st.rerun()


def esc(text):
    """Show model or CV text literally inside st.markdown (no bold, links, emoji codes or $math$)."""
    return re.sub(r"([\\`*_\[\]<>$~|#:])", r"\\\1", str(text))


def chip(text, colors, bold=False, outline=None, size="0.82rem", tip=None):
    """A rounded pill. colors = (background, text); tip is the hover text (default: the text, which
    a long pill cuts short)."""
    bg, fg = colors
    border = f"border:1.5px solid {outline};" if outline else ""
    return (f'<span style="background:{bg};color:{fg};{border}font-weight:{600 if bold else 500};border-radius:999px;'
            f'padding:2px 10px;margin:0 4px 4px 0;display:inline-block;font-size:{size};line-height:1.55;'
            f'white-space:nowrap;max-width:100%;overflow:hidden;text-overflow:ellipsis;vertical-align:top" '
            f'title="{html.escape(str(tip or text))}">{html.escape(str(text))}</span>')


def band_colors(value, P, top=100):
    b = band(value, top)
    return P.band_bg[b], P.band_fg[b]


def match_pill(c, P):
    """'B+ · 73%' coloured by the Requirement Match band (pipeline MatchPill)."""
    return chip(f"{c['grade']} · {c['fit']}%", band_colors(c["fit"], P), bold=True)


def gap_pill(c, P):
    """'Match' when every must-have is met, else 'Gap · N must-haves' (pipeline eligibility column)."""
    if c["gaps"] == 0:
        return chip("All must-haves", P.mint)
    return chip(f"Gap · {c['gaps']} must-have{'s' if c['gaps'] > 1 else ''}", P.lemon)


def svg_icon(paths, color, size=18, stroke=2):
    """A line icon as an <img>: st.html strips inline <svg>, but keeps a data-URI image."""
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" '
           f'stroke="{color}" stroke-width="{stroke}" stroke-linecap="round" stroke-linejoin="round">'
           + "".join(f'<path d="{d}"/>' for d in paths) + "</svg>")
    return f'<img alt="" src="data:image/svg+xml;base64,{base64.b64encode(svg.encode()).decode()}" style="display:block">'


def initials(name):
    parts = [p for p in re.split(r"\s+", name.strip()) if p[:1].isalpha()]
    return ("".join(p[0] for p in parts[:2]) or "?").upper()


def avatar(name, P, size=32):
    bg, fg = P.lemon if not P.dark else P.lavender
    return (f'<span style="display:inline-flex;align-items:center;justify-content:center;width:{size}px;height:{size}px;'
            f'border-radius:999px;background:{bg};color:{fg};font-weight:700;font-size:{size * 0.38:.0f}px;flex:none">'
            f'{html.escape(initials(name))}</span>')


def apply_css(P):
    """Containers created with key="card..." get the card look; nothing else is restyled."""
    st.html(f"""<style>
    [class*="st-key-card"] {{ background:{P.card}; border-radius:1rem; box-shadow:{P.shadow}; }}
    [class*="st-key-pair"] > div > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] > [data-testid="stVerticalBlock"] > div,
    [class*="st-key-pair"] > div > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] > [data-testid="stVerticalBlock"] > div > [class*="st-key-card"]
        {{ flex:1 1 auto; }}  /* views.pair: every card in the row as tall as the tallest */
    [class*="st-key-row"] {{ background:{P.card}; border-radius:0.9rem; }}
    [class*="st-key-row"]:hover {{ box-shadow:{P.shadow}; }}
    h1, h2, h3 {{ letter-spacing:-0.02em; }}
    .st-key-theme_watch {{ display:none; }}  /* watch_theme draws nothing; this drops its gap in the sidebar */
    </style>""")
