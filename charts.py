"""Charts and HTML pieces of the pages.

Every function takes `P`, the light or dark palette from style.py. Altair charts have a transparent background and no
title (the page writes the heading). Run `python charts.py` for the self-check (no server needed).
"""
import calendar
import html
import re

import altair as alt
import pandas as pd
import plotly.graph_objects as go

from insights import BAND_LABELS, DIM_FULL, DIMS, band
from style import SERIES, STATUS, band_colors, avatar, chip, gap_pill, match_pill, rgba

DOT = {"met": "#10b981", "partial": "#f59e0b", "missing": "#f43f5e"}
SEVERITY = {"red": "rose", "yellow": "lemon", "grey": "grey", "green": "mint"}  # career note -> pastel
FONT = "Plus Jakarta Sans, sans-serif"
GRADE_BAND = {"A": 4, "A-": 4, "B+": 3, "B": 3, "C": 2, "D": 0}
# Ranking rows are one CSS grid so every row lines up with the header. Narrow containers drop the Summary column, then
# Experience and Gap columns; the container query follows the table's width, not the window's.
ROW_CSS = """<style>
.cvr-wrap{container-type:inline-size}
.cvr{display:grid;grid-template-columns:2.2rem minmax(10rem,1.6fr) 6.2rem 5.6rem 3.4rem 9.6rem 10.6rem minmax(9rem,2fr);gap:0 0.75rem;align-items:center;padding:0.55rem 0.9rem}
@container (max-width:63rem){.cvr{grid-template-columns:2.2rem minmax(10rem,1fr) 6.2rem 5.6rem 3.4rem 9.6rem 10.6rem}.cvr>:nth-child(8){display:none}}
@container (max-width:53rem){.cvr{grid-template-columns:2.2rem minmax(8rem,1fr) 6.2rem 5.6rem 3.4rem}.cvr>:nth-child(n+6){display:none}}
</style>"""


def bar_height(n, step=40, pad=80):
    """Pixel height for a horizontal bar chart with n rows (pass it to st.altair_chart too)."""
    return n * step + pad


def _plot(chart, P, height):
    return (chart.properties(height=height)
            .configure(background="rgba(0,0,0,0)", font=FONT)
            .configure_view(strokeWidth=0)
            .configure_axis(labelColor=P.muted, titleColor=P.muted, gridColor=P.grid, domainColor=P.grid, tickColor=P.grid,
                            labelFontSize=11, titleFontSize=11, titleFontWeight="normal")
            .configure_legend(labelColor=P.muted, titleColor=P.muted, orient="top", labelFontSize=11, symbolType="circle"))


def _short(text, n):
    text = str(text)
    return text if len(text) <= n else text[:n - 1].rstrip() + "…"


def _color(domain, colors):
    return alt.Scale(domain=list(domain), range=list(colors))


# ---------- Overview ----------

def experience_scatter(people, P, height=320):
    """Years of experience vs Requirement Match, coloured by band."""
    df = pd.DataFrame([{"Candidate": c["name"], "Years": c["years"], "Match": c["fit"], "Band": BAND_LABELS[band(c["fit"])],
                        "Grade": c["grade"], "Experience": c["experience"]} for c in people if c["years"] is not None])
    if df.empty:
        return None
    df["x"] = df["Years"] + df.groupby(["Years", "Match"]).cumcount() * 0.15  # exact duplicates sit side by side
    keep = set(df.index) if len(df) <= 12 else set(df.nlargest(5, "Match").index)
    hi = max(5, int(df["x"].max()) + 2)
    # Names go above, below or right of their dot, wherever they hit no other name or dot; else the tooltip names them.
    # ponytail: sizes in data units are tuned for the 320 px half-width card; other sizes may overlap a little.
    cw, r = hi * 0.014, hi * 0.016  # one character's width and a dot's radius, in years
    boxes = [(x0, y0, r, 4.6) for x0, y0 in zip(df["x"], df["Match"])]  # (centre x, centre y, half width, half height)
    df["label"], df["spot"] = "", ""
    for i in df.sort_values("Match", ascending=False).index:
        if i not in keep:
            continue
        name, x0, y0 = df.at[i, "Candidate"].split()[0], df.at[i, "x"], df.at[i, "Match"]
        half = len(name) * cw / 2
        for spot, cx, cy in (("above", x0, y0 + 8.5), ("below", x0, y0 - 10), ("right", x0 + r + 0.2 * cw + half, y0)):
            if all(abs(cx - bx) >= half + bw or abs(cy - by) >= 3.5 + bh for bx, by, bw, bh in boxes):
                boxes.append((cx, cy, half, 3.5))
                df.at[i, "label"], df.at[i, "spot"] = name, spot
                break
    present = [b for b in BAND_LABELS if b in set(df["Band"])]
    x = alt.X("x:Q", scale=alt.Scale(domain=[0, hi]), title="Years of experience")
    y = alt.Y("Match:Q", scale=alt.Scale(domain=[0, 100]), title="Requirement Match %", axis=alt.Axis(values=[0, 25, 50, 75, 100]))
    dots = alt.Chart(df).mark_circle(size=150, opacity=0.9, stroke=P.card, strokeWidth=1.5).encode(
        x=x, y=y, color=alt.Color("Band:N", scale=_color(present, [P.band_fg[BAND_LABELS.index(b)] for b in present]),
                                  legend=alt.Legend(title=None)),
        tooltip=["Candidate", alt.Tooltip("Grade:N"), alt.Tooltip("Match:Q", title="Match %"), "Experience"])
    marks = {"above": {"dy": -13}, "below": {"dy": 15}, "right": {"dx": 9, "align": "left"}}
    names = alt.layer(*(alt.Chart(df[df["spot"] == s]).mark_text(fontSize=11, color=P.muted, baseline="middle", **kw)
                        .encode(x=x, y=y, text="label:N") for s, kw in marks.items()))
    corners = alt.Chart(pd.DataFrame([{"x": hi, "Match": 97, "t": "experienced & strong ↗", "base": "top"},
                                      {"x": hi, "Match": 3, "t": "⚠ years without the fit ↘", "base": "bottom"}]))
    labels = [corners.transform_filter(alt.datum.base == b).mark_text(align="right", baseline=b, color=P.muted, fontSize=11, dx=-4)
              .encode(x=x, y=y, text="t:N") for b in ("top", "bottom")]  # same x and y encodings: layers must not rename the axes
    return _plot(dots + names + labels[0] + labels[1], P, height)


def standing_chart(c, pool, P, height=300):
    """This candidate against the pool: 12-skill profile (x) vs Requirement Match (y), split at the pool medians.
    Top right = meets the list with depth behind it; top left = meets the list on thinner evidence."""
    df = pd.DataFrame([{"Candidate": x["name"], "Profile": x["profile"], "Match": x["fit"], "Grade": x["grade"],
                        "me": x is c} for x in pool])
    mx, my = df["Profile"].median(), df["Match"].median()
    lo, hi = max(0, df["Profile"].min() - 6), min(100, df["Profile"].max() + 6)
    x = alt.X("Profile:Q", scale=alt.Scale(domain=[lo, hi], zero=False, nice=False), title="12-skill profile (out of 100)")
    y = alt.Y("Match:Q", scale=alt.Scale(domain=[-14, 114]), title="Requirement Match %", axis=alt.Axis(values=[0, 25, 50, 75, 100]))
    tip = ["Candidate", "Grade", alt.Tooltip("Match:Q", title="Match %"), alt.Tooltip("Profile:Q", title="Profile")]
    split = pd.DataFrame([{"Profile": mx}])
    rules = (alt.Chart(split).mark_rule(strokeDash=[4, 4], color=P.muted, opacity=0.6).encode(x=x)
             + alt.Chart(pd.DataFrame([{"Match": my}])).mark_rule(strokeDash=[4, 4], color=P.muted, opacity=0.6).encode(y=y))
    others = alt.Chart(df[~df["me"]]).mark_circle(size=80, color=P.muted, opacity=0.45).encode(x=x, y=y, tooltip=tip)
    me = df[df["me"]]
    dot = alt.Chart(me).mark_circle(size=280, color=P.primary, opacity=1, stroke=P.card, strokeWidth=2).encode(x=x, y=y, tooltip=tip)
    right = c["profile"] > (lo + hi) / 2  # name beside the dot, on the side with room; corner labels sit outside 0-100
    text = dict(align="right" if right else "left", dx=-13 if right else 13, fontWeight="bold", fontSize=12)
    halo = alt.Chart(me).mark_text(**text, color=P.card, stroke=P.card, strokeWidth=5, strokeJoin="round").encode(
        x=x, y=y, text=alt.Text("Candidate:N"))  # keeps the name readable over other dots and the median line
    name = halo + alt.Chart(me).mark_text(**text, color=P.primary).encode(x=x, y=y, text=alt.Text("Candidate:N"))
    corners = pd.DataFrame([{"Profile": hi, "Match": 114, "t": "strong on both", "a": "right", "b": "top"},
                            {"Profile": lo, "Match": 114, "t": "meets the list, thinner evidence", "a": "left", "b": "top"},
                            {"Profile": hi, "Match": -14, "t": "strong skills, off the list", "a": "right", "b": "bottom"},
                            {"Profile": lo, "Match": -14, "t": "behind on both", "a": "left", "b": "bottom"}])
    labels = [alt.Chart(corners[(corners["a"] == a) & (corners["b"] == b)]).mark_text(
        align=a, baseline=b, color=P.muted, fontSize=10.5, dx=4 if a == "left" else -4).encode(x=x, y=y, text="t:N")
        for a in ("left", "right") for b in ("top", "bottom")]
    chart = rules + others + dot + name
    for layer in labels:
        chart += layer
    return _plot(chart, P, height)


def gain_rows_html(rows, c, rank_now, P):
    """'What would move them up': per unmet must-have, a bar from today's Match to the Match if the line were shown,
    with the rank it would give. Nice-to-have rows (from insights.nice_if) show only the tie-break rank."""
    out = []
    for r in rows:
        req, now, then = r["req"], c["fit"], r["fit"]
        status = chip(req["counted"].capitalize(), getattr(P, STATUS[req["counted"]]), size="0.72rem")
        bar = (f'<div style="position:relative;height:8px;border-radius:999px;background:{P.grid};overflow:hidden">'
               f'<div style="position:absolute;left:0;top:0;bottom:0;width:{now}%;background:{band_colors(now, P)[1]};opacity:.55"></div>'
               f'<div style="position:absolute;left:{now}%;top:0;bottom:0;width:{then - now}%;background:{P.primary}"></div></div>')
        moved = f'#{rank_now} → <b>#{r["rank"]}</b>' if r["rank"] < rank_now else f'stays #{rank_now}'
        move = f'<b style="color:{P.primary}">+{r["gain"]} pts</b> → {then}% · {moved}' if req["must"] else f'tie-break · {moved}'
        if not req["must"]:
            bar = ""
        out.append(f'<div style="display:grid;grid-template-columns:minmax(0,1fr) 11rem;gap:0.25rem 1rem;align-items:center;'
                   f'padding:0.45rem 0;border-bottom:1px solid {P.grid}">'
                   f'<div style="min-width:0">{status}<span style="color:{P.ink};font-size:0.9rem">{html.escape(req["text"])}</span></div>'
                   f'<div style="font-size:0.85rem;color:{P.muted};text-align:right;white-space:nowrap">{move}</div>'
                   f'<div style="grid-column:1 / span 2">{bar}</div></div>')
    return "".join(out)


def _find(text, quote):
    """(start, end) spans of a quote in the CV text, ignoring case, punctuation and line breaks; "..." and ";"
    split a quote into pieces that are found one by one."""
    spans = []
    for piece in re.split(r"\.\.\.|…|;", quote or ""):
        ws = re.findall(r"\w+", piece)
        if ws and (m := re.search(r"\W+".join(map(re.escape, ws)), text, re.I)):
            spans.append((m.start(), m.end()))
    return spans


def evidence_html(c, P):
    """The CV text with every verified quote marked: met requirements green, partial yellow, skill evidence lavender.
    Hover a mark to see what it proves. Returns (html, number of marks)."""
    text, marks = c["text"], []
    for r in c["requirements"]:
        if r["quote"] and r["found"]:
            colors = P.mint if r["counted"] == "met" else P.lemon
            marks += [(a, b, colors, f"{'Must' if r['must'] else 'Nice'} ({r['counted']}): {r['text']}") for a, b in _find(text, r["quote"])]
    for d in DIMS:
        x = c["dimensions"][d]
        if x["quote"]:
            marks += [(a, b, P.lavender, f"Skill: {DIM_FULL[d]} {x['score']}/10") for a, b in _find(text, x["quote"])]
    kept = []  # requirement marks come first, so they win where marks overlap; the hover text lists both
    for a, b, colors, label in marks:
        hit = next((k for k in kept if a < k[1] and b > k[0]), None)
        if hit:
            hit[3].append(label)
        else:
            kept.append([a, b, colors, [label]])
    out, pos = [], 0
    for a, b, (bg, fg), labels in sorted(kept):
        out.append(html.escape(text[pos:a]))
        tip = html.escape(" · ".join(dict.fromkeys(labels)), quote=True)
        out.append(f'<mark title="{tip}" style="background:{bg};color:{fg};border-radius:4px;padding:0 2px">{html.escape(text[a:b])}</mark>')
        pos = b
    out.append(html.escape(text[pos:]))
    body = "".join(out)
    return (f'<div style="white-space:pre-wrap;font-size:0.84rem;line-height:1.6;color:{P.ink};max-height:460px;overflow:auto;'
            f'padding:0.25rem 0.5rem 0.25rem 0">{body}</div>'), len(kept)


def coverage_bars(rows, P):
    """Per requirement, how many candidates meet it, partly meet it or miss it (stacked, rarest first)."""
    if not rows:
        return None
    labels = {r["id"]: f"{'Must' if r['must'] else 'Nice'} {r['id'][1:]} · {_short(r['text'], 58)}" for r in rows}
    df = pd.DataFrame([{"Requirement": labels[r["id"]], "Full": r["text"], "Status": s.capitalize(), "Candidates": r[s],
                        "k": i} for r in rows for i, s in enumerate(("met", "partial", "missing"))])
    total = sum(rows[0][s] for s in ("met", "partial", "missing"))
    chart = alt.Chart(df).mark_bar(height=16, cornerRadius=3).encode(
        y=alt.Y("Requirement:N", sort=[labels[r["id"]] for r in rows], title=None, axis=alt.Axis(labelLimit=460, grid=False, labelOverlap=False)),
        x=alt.X("Candidates:Q", stack="zero", title=f"Candidates (of {total})", scale=alt.Scale(domain=[0, total]),
                axis=alt.Axis(tickMinStep=1)),
        color=alt.Color("Status:N", scale=_color(["Met", "Partial", "Missing"], DOT.values()), legend=alt.Legend(title=None)),
        order=alt.Order("k:Q"), tooltip=[alt.Tooltip("Full:N", title="Requirement"), "Status", "Candidates"])
    return _plot(chart, P, bar_height(len(rows)))


def grade_bars(grades, P, height=260):
    """How many candidates got each grade, coloured by the band of that grade."""
    df = pd.DataFrame([{"Grade": g, "Candidates": n, "fill": P.band_fg[GRADE_BAND[g]]} for g, n in grades])
    base = alt.Chart(df).encode(x=alt.X("Grade:N", sort=None, title=None, axis=alt.Axis(labelAngle=0, labelFontSize=13, grid=False)),
                                y=alt.Y("Candidates:Q", title=None, axis=alt.Axis(tickMinStep=1)))
    bars = base.mark_bar(cornerRadiusTopLeft=5, cornerRadiusTopRight=5, size=34).encode(
        color=alt.Color("fill:N", scale=None), tooltip=["Grade", "Candidates"])
    text = base.mark_text(dy=-8, color=P.muted, fontWeight="bold").encode(
        text=alt.condition(alt.datum.Candidates > 0, "Candidates:Q", alt.value("")))
    return _plot(bars + text, P, height)


def strength_chart(rows, P):
    """Pool median per skill (weakest first), coloured by band; the tooltip shows the share scoring 7 or more."""
    df = pd.DataFrame([{"Skill": DIM_FULL[r["dim"]], "Median": r["median"], "At 7+": f"{r['strong']:.0%}",
                        "label": f"{r['median']:g}  ·  {r['strong']:.0%} at 7+",
                        "fill": P.band_fg[band(r["median"], 10)]} for r in rows])
    y = alt.Y("Skill:N", sort=list(df["Skill"]), title=None, axis=alt.Axis(labelLimit=200, grid=False))
    x = alt.X("Median:Q", scale=alt.Scale(domain=[0, 10.8]), title="Median score (out of 10)", axis=alt.Axis(values=[0, 2, 4, 6, 8, 10]))
    bars = alt.Chart(df).mark_bar(height=14, cornerRadius=4).encode(
        y=y, x=x, color=alt.Color("fill:N", scale=None), tooltip=["Skill", "Median", alt.Tooltip("At 7+:N", title="Candidates at 7+")])
    text = alt.Chart(df).mark_text(align="left", dx=6, color=P.muted).encode(y=y, x=x, text="label:N")
    return _plot(bars + text, P, bar_height(len(df)))


def skill_chart(rows, P):
    """Most common verified technologies in the pool; the colour says whether the job text asks for them."""
    if not rows:
        return None
    df = pd.DataFrame([{"Skill": r["skill"], "Candidates": r["candidates"], "Job": "Asked for" if r["asked"] else "Not asked for"}
                       for r in rows])
    y = alt.Y("Skill:N", sort=list(df["Skill"]), title=None, axis=alt.Axis(labelLimit=200, grid=False))
    bars = alt.Chart(df).mark_bar(height=14, cornerRadius=4).encode(
        y=y, x=alt.X("Candidates:Q", axis=alt.Axis(tickMinStep=1), title="Candidates"),
        color=alt.Color("Job:N", scale=_color(["Asked for", "Not asked for"], [P.primary, rgba(P.muted, 0.45)]),
                        legend=alt.Legend(title=None)),
        tooltip=["Skill", "Candidates", alt.Tooltip("Job:N", title="In the job text")])
    text = alt.Chart(df).mark_text(align="left", dx=6, color=P.muted).encode(y=y, x="Candidates:Q", text="Candidates:Q")
    return _plot(bars + text, P, bar_height(len(df), 26))


# ---------- Candidate ----------

def radar(series, P, average=None, height=440):
    """12-skill radar. series = [(name, {dim: score}, color)]; average = {dim: score},
    drawn as a dotted grey 'Pool median' polygon."""
    names = [DIM_FULL[d].replace(" ", "<br>", 1) for d in DIMS]  # two-line labels keep the plot large
    theta = names + names[:1]
    loop = lambda s: [s.get(d, 0) for d in DIMS] + [s.get(DIMS[0], 0)]  # noqa: E731
    fig = go.Figure()
    for name, scores, color in series:
        fig.add_trace(go.Scatterpolar(r=loop(scores), theta=theta, name=name, mode="lines+markers",
                                      line=dict(color=color, width=2), marker=dict(size=5),
                                      fill="toself", fillcolor=rgba(color, 0.18),
                                      hovertemplate="%{theta}: %{r}<extra>" + html.escape(name) + "</extra>"))
    if average:
        fig.add_trace(go.Scatterpolar(r=loop(average), theta=theta, name="Pool median", mode="lines",
                                      line=dict(color=P.muted, dash="dot", width=2), hoverinfo="skip"))
    fig.update_layout(
        height=height, margin=dict(l=70, r=70, t=48, b=60), showlegend=True,
        legend=dict(orientation="h", yanchor="top", y=-0.12, x=0.5, xanchor="center"),
        polar=dict(bgcolor="rgba(0,0,0,0)",
                   radialaxis=dict(range=[0, 10], tickvals=[2, 4, 6, 8, 10], gridcolor=P.grid, linecolor=P.grid,
                                   tickfont=dict(size=9, color=P.muted)),
                   angularaxis=dict(gridcolor=P.grid, linecolor=P.grid, tickfont=dict(size=11, color=P.ink))),
        paper_bgcolor="rgba(0,0,0,0)", font=dict(family=FONT, color=P.ink))
    return fig


def career_html(spans, P):
    """Employment history on one time axis, the role written above each bar so it fits a half-width card;
    spans = insights.career_spans()[0]."""
    if not spans:
        return ""
    lo, hi = min(s["start"] for s in spans), max(s["end"] for s in spans) + 1
    pos = lambda m: (m - lo) / (hi - lo) * 100  # noqa: E731
    month = lambda m: f"{calendar.month_abbr[(m - 1) % 12 + 1]} {(m - 1) // 12}"  # noqa: E731
    kinds = {"full_time": ("Full-time", P.primary), "internship": ("Internship", "#f59e0b"),
             "contract": ("Contract", SERIES[1]), "owner": ("Own business", SERIES[2])}
    rows, seen = [], {}
    for s in sorted(spans, key=lambda s: -s["start"]):
        label, color = kinds.get(s["kind"], ("Other", P.muted))
        seen[label] = color
        n = s["end"] - s["start"] + 1
        dates = f"{month(s['start'])} – {'now' if s['current'] else month(s['end'])} · " + (f"{n // 12} yr {n % 12} mo" if n >= 12 else f"{n} mo")
        rows.append(
            f'<div style="padding:0.3rem 0" title="{html.escape(label)}">'
            f'<div style="display:flex;justify-content:space-between;gap:0.75rem;font-size:0.82rem;line-height:1.4">'
            f'<span style="min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:{P.ink}">{html.escape(s["role"])}'
            f'<span style="color:{P.muted}"> @ {html.escape(s["employer"])}</span></span>'
            f'<span style="flex:none;color:{P.muted}">{dates}</span></div>'
            f'<div style="position:relative;height:8px;margin-top:4px;border-radius:999px;background:{P.grid}">'
            f'<div style="position:absolute;top:0;bottom:0;left:{pos(s["start"]):.1f}%;width:{max(pos(s["end"] + 1) - pos(s["start"]), 1.5):.1f}%;'
            f'border-radius:999px;background:{color}"></div></div></div>')
    first, last = (lo - 1) // 12 + 1, (hi - 2) // 12  # whole years that start inside the axis
    step = max(1, -(-(last - first + 1) // 7))
    ticks = "".join(f'<span style="position:absolute;left:{pos(y * 12 + 1):.1f}%;transform:translateX(-50%)">{y}</span>'
                    for y in range(first, last + 1, step) if 4 < pos(y * 12 + 1) < 96)
    legend = "".join(f'<span style="margin-right:0.8rem"><span style="display:inline-block;width:8px;height:8px;border-radius:999px;'
                     f'background:{color};margin-right:5px"></span>{label}</span>' for label, color in seen.items())
    legend = legend if set(seen) != {"Other"} else ""  # no role type known: the career notes say so
    return (f'<div style="font-size:0.75rem;color:{P.muted};margin-bottom:0.2rem">{legend}</div>{"".join(rows)}'
            f'<div style="position:relative;height:1.1rem;font-size:0.72rem;color:{P.muted};margin-top:0.2rem">{ticks}</div>')


def badge_rows_html(rows, P, width="5.5rem"):
    """A chip in a fixed column with a title and notes beside it: requirement verdicts, the 12 skills.
    rows = [(chip html, title html, [(note html, colour or None)])]; the caller escapes the text."""
    return "".join(
        f'<div style="display:grid;grid-template-columns:{width} minmax(0,1fr);gap:0.6rem;padding:0.55rem 0;'
        f'border-top:{f"1px solid {P.grid}" if i else "0"}"><div>{badge}</div><div style="min-width:0">'
        f'<div style="font-size:0.92rem;line-height:1.45;color:{P.ink}">{title}</div>'
        + "".join(f'<div style="font-size:0.8rem;line-height:1.45;margin-top:3px;color:{color or P.muted}">{note}</div>'
                  for note, color in notes)
        + "</div></div>" for i, (badge, title, notes) in enumerate(rows))


# ---------- Compare ----------

def delta_bars(a, b, P):
    """Head-to-head: per skill how far A (left) or B (right) is ahead."""
    ca, cb = SERIES[0], SERIES[1]
    rows = []
    for d in DIMS:
        sa, sb = a["dimensions"][d]["score"], b["dimensions"][d]["score"]
        delta = sa - sb
        bar = lambda on, color: (f'<div style="height:10px;border-radius:999px;width:{min(abs(delta) / 10, 1) * 100:.0f}%;'  # noqa: E731
                                 f'background:{color}"></div>' if on else "")
        rows.append(
            f'<div style="display:grid;grid-template-columns:minmax(110px,22%) 1fr 48px 1fr;align-items:center;gap:8px;'
            f'font-size:0.82rem;padding:3px 0" title="{html.escape(a["name"])} {sa:g} · {html.escape(b["name"])} {sb:g}">'
            f'<span style="color:{P.muted};overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{DIM_FULL[d]}</span>'
            f'<div style="display:flex;justify-content:flex-end">{bar(delta > 0, ca)}</div>'
            f'<span style="text-align:center;font-weight:600;font-variant-numeric:tabular-nums;'
            f'color:{P.ink if delta else P.muted}">{delta:+g}</span>'
            f'<div style="display:flex">{bar(delta < 0, cb)}</div></div>')
    head = (f'<div style="display:flex;justify-content:space-between;gap:12px;font-size:0.82rem;font-weight:600;margin-bottom:6px">'
            f'<span style="color:{ca}">{html.escape(a["name"])}</span><span style="color:{cb};text-align:right">{html.escape(b["name"])}</span></div>')
    return f'<div>{head}{"".join(rows)}</div>'


TABLE = "border-collapse:separate;border-spacing:3px;width:100%;font-size:0.86rem"


def _th(text, P, align="center", color=None):
    line = f"border-bottom:3px solid {color};" if color else ""
    return (f'<th style="text-align:{align};padding:6px 8px;font-weight:600;color:{P.ink};{line}">{html.escape(text)}</th>')


def _cell(text, colors, tip="", ring=None, bold=True):
    bg, fg = colors
    ring = f"box-shadow:inset 0 0 0 2px {ring};" if ring else ""
    return (f'<td title="{html.escape(tip, quote=True)}" style="text-align:center;padding:6px;border-radius:8px;'
            f'font-weight:{600 if bold else 500};background:{bg};color:{fg};{ring}">{html.escape(text)}</td>')


def score_matrix(cands, P):
    """Score matrix: the 12 skills, band-coloured cells, the best per row ringed."""
    head = _th("Skill", P, "left") + "".join(_th(c["name"], P, color=SERIES[i % len(SERIES)]) for i, c in enumerate(cands))
    body = []
    for d in DIMS:
        vals = [c["dimensions"][d]["score"] for c in cands]
        cells = []
        for c, v in zip(cands, vals):
            x = c["dimensions"][d]
            tip = x["evidence"] + (f" — “{x['quote']}”" if x["quote"] else " (quote not verified)")
            cells.append(_cell(f"{v:g}", band_colors(v, P, 10), tip, P.primary if len(set(vals)) > 1 and v == max(vals) else None))
        body.append(f'<tr><td style="padding:6px 8px;color:{P.ink}">{DIM_FULL[d]}</td>{"".join(cells)}</tr>')
    profile = "".join(_cell(f"{c['profile']:g}", band_colors(c["profile"], P)) for c in cands)
    body.append(f'<tr><td style="padding:6px 8px;font-weight:700;color:{P.ink}">Profile (average × 10)</td>{profile}</tr>')
    return f'<table style="{TABLE}"><thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table>'


def coverage_matrix(cands, P):
    """Requirement coverage: ✓ met, ? partial, ✗ missing; the quote is the tooltip."""
    head = _th("Requirement", P, "left") + "".join(_th(c["name"], P, color=SERIES[i % len(SERIES)]) for i, c in enumerate(cands))
    mark = {"met": "✓", "partial": "?", "missing": "✗"}
    body = []
    for i, req in enumerate(cands[0]["requirements"]):
        cells = []
        for c in cands:
            r = c["requirements"][i]
            tip = f"{r['counted']}" + (f" — “{r['quote']}”" if r["quote"] else "") + (f" · {r['reason']}" if r["reason"] else "")
            if r["verdict"] == "met" and r["counted"] == "partial":
                tip += " (quote not found in the CV, counted as partial)"
            cells.append(_cell(mark[r["counted"]], getattr(P, STATUS[r["counted"]]), tip))
        tag = chip("Must" if req["must"] else "Nice", P.lavender if req["must"] else P.grey, size="0.7rem")
        body.append(f'<tr><td style="padding:6px 8px;color:{P.ink}">{tag}{html.escape(req["text"])}</td>{"".join(cells)}</tr>')
    return f'<table style="{TABLE}"><thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table>'


# ---------- Candidate banner and ranking rows ----------

def banner_html(c, P):
    """Requirement Match banner: big grade + %, band-coloured wash, the facts beside it."""
    if not c.get("ok"):
        return (f'<div style="padding:1rem 1.5rem;border-radius:1rem;background:{P.card};box-shadow:{P.shadow};color:{P.muted}">'
                f'Not scored: {html.escape(str(c.get("error") or "no result"))}</div>')
    bg, fg = band_colors(c["fit"], P)
    facts = [f"{c['must_met']} of {c['must_total']} must-haves met", c["experience"]]
    if c["nice_total"]:
        facts.insert(1, f"{c['nice_met']} of {c['nice_total']} nice-to-haves")
    facts = "".join(f'<span style="white-space:nowrap">{html.escape(f)}</span>' for f in facts)
    return (f'<div style="display:flex;flex-wrap:wrap;align-items:center;gap:0.5rem 2rem;padding:1rem 1.5rem;border-radius:1rem;'
            f'background:linear-gradient(90deg,{bg},{P.card} 70%);box-shadow:{P.shadow}">'
            f'<div><div style="font-size:0.78rem;font-weight:500;color:{P.muted}">Requirement Match</div>'
            f'<div style="display:flex;align-items:baseline;gap:0.5rem;color:{fg};line-height:1.1;margin-top:2px">'
            f'<span style="font-size:2.1rem;font-weight:700">{html.escape(c["grade"])}</span>'
            f'<span style="font-size:1.2rem;font-weight:600">{c["fit"]}%</span></div></div>'
            f'<div style="display:flex;flex-wrap:wrap;gap:0.25rem 1.4rem;color:{P.muted};font-size:0.92rem">{facts}</div></div>')


def ranking_header_html(P):
    cells = ["#", "Candidate", "Match", "Must-haves", "Nice", "Experience", "Gap", "Summary"]
    return (ROW_CSS + f'<div class="cvr-wrap"><div class="cvr" style="padding-top:0;padding-bottom:0;font-size:0.72rem;font-weight:600;'
            f'letter-spacing:0.04em;text-transform:uppercase;color:{P.muted}">' + "".join(f"<span>{t}</span>" for t in cells) + "</div></div>")


def ranking_row_html(c, rank, P):
    """One ranking row on the same fixed columns as the header (pipeline/row/*)."""
    share = 100 * c["must_met"] / c["must_total"] if c["must_total"] else 0
    bar = band_colors(share, P)[1]
    nice = f"{c['nice_met']}/{c['nice_total']}" if c["nice_total"] else "—"
    cell = "min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap"
    summary = c["scoring"]["fit_summary"]
    check = chip(f"⚑ {c['to_check']}", P.peach, tip=f"{c['to_check']} line(s) the model called missing name a technology "
                 "the CV lists: check them") if c.get("to_check") else ""
    return (
        f'<div class="cvr-wrap"><div class="cvr" style="font-size:0.84rem">'
        f'<span style="font-weight:700;color:{P.muted}">#{rank}</span>'
        f'<div style="display:flex;align-items:center;gap:0.6rem;min-width:0">{avatar(c["name"], P, 30)}'
        f'<div style="min-width:0;line-height:1.25"><div style="{cell};font-weight:600;color:{P.ink}" title="{html.escape(c["name"])}">{html.escape(c["name"])}</div>'
        f'<div style="{cell};font-size:0.72rem;color:{P.muted}" title="{html.escape(c["file"])}">{html.escape(c["file"])}</div></div></div>'
        f'<div>{match_pill(c, P)}</div>'
        f'<div title="{c["must_met"]} of {c["must_total"]} must-haves met"><div style="font-weight:600;font-variant-numeric:tabular-nums;line-height:1.2">'
        f'{c["must_met"]}/{c["must_total"]}</div><div style="height:3px;border-radius:999px;background:{P.grid};margin-top:3px;overflow:hidden">'
        f'<div style="height:100%;width:{share:.0f}%;border-radius:999px;background:{bar}"></div></div></div>'
        f'<span style="font-variant-numeric:tabular-nums" title="{c["nice_met"]} of {c["nice_total"]} nice-to-haves met">'
        f'{nice}</span>'
        f'<span style="{cell};color:{P.muted}">{html.escape(c["experience"])}</span>'
        f'<div style="white-space:nowrap">{gap_pill(c, P)}{check}</div>'
        f'<span style="{cell};color:{P.muted}" title="{html.escape(summary)}">{html.escape(summary)}</span></div></div>')


if __name__ == "__main__":
    import json
    from datetime import date

    import insights as ins
    import scoring as sc
    from style import DARK, LIGHT

    def fake(i, name, verdicts, techs):
        reqs = [{"id": f"R{k}", "must": True, "text": f"Must line {k}", "verdict": v, "quote": "q" if v != "missing" else "",
                 "reason": "why", "found": v != "missing"} for k, v in enumerate(verdicts, 1)]
        reqs.append({"id": "P1", "must": False, "text": "Nice line", "verdict": "met", "quote": "n", "reason": "", "found": True})
        for r in reqs:
            r["counted"] = r["verdict"]
        dims = {d: {"score": (i * 3 + k) % 10, "evidence": f"ev {d}", "weakness": "", "quote": "qq" if k % 2 else "", "grounded": bool(k % 2)}
                for k, d in enumerate(DIMS)}
        facts = {"extracted_data": {"candidate_name": name, "years_of_experience": 2 + i * 3, "key_technologies": techs,
                                    "employment_history": [{"employer": "Acme", "role": "Engineer (Full time)", "start": "2019-01",
                                                            "end": None, "is_current": True, "source_quote": "x"}]},
                 "red_flags": {"gaps": [], "inconsistencies": [], "missing_info": []},
                 "contextual_summary": {"strengths": [], "weaknesses": [], "unique_selling_points": [], "career_narrative": ""}}
        r = {"file": f"{name}.txt", "text": "cv", "scoring": {"fit_summary": "Strong <b>backend</b> profile.", "requirements": reqs, "dimensions": dims},
             "facts": facts, "error": None}
        return {**r, **sc.derive(r)}

    pool = sc.rank([fake(0, "Ana A", ["met", "met", "missing"], ["React", "Go"]), fake(1, "Bo B", ["met", "partial", "missing"], ["React"]),
                    fake(2, "Cy C", ["met", "met", "met"], ["Go", "SQL"]), fake(3, "Dee D", ["missing", "missing", "met"], [])])
    reqs = [{"id": r["id"], "must": r["must"], "text": r["text"]} for r in pool[0]["requirements"]]
    for P in (LIGHT, DARK):
        for chart in (experience_scatter(pool, P), coverage_bars(ins.coverage(pool, reqs), P), grade_bars(ins.grades(pool), P),
                      strength_chart(ins.strength_profile(pool), P), skill_chart(ins.skill_landscape(pool, "We need React"), P)):
            assert chart is not None and json.dumps(chart.to_dict())
        series = [(c["name"], {d: c["dimensions"][d]["score"] for d in DIMS}, SERIES[i]) for i, c in enumerate(pool[:2])]
        assert radar(series, P, average={d: 5 for d in DIMS}).to_json()
        assert "Ana A" in delta_bars(pool[0], pool[1], P) and "✓" in coverage_matrix(pool, P) and "Profile" in score_matrix(pool, P)
        assert "Requirement Match" in banner_html(pool[0], P) and "&lt;b&gt;" in ranking_row_html(pool[0], 1, P)
        assert ranking_header_html(P).count("<span>") == 8 and "Not scored" in banner_html({"ok": False, "error": "x"}, P)
        assert json.dumps(standing_chart(pool[1], pool, P).to_dict())
        rows, _ = ins.what_if(pool[1], pool)
        assert "+" in gain_rows_html(rows, pool[1], ins.rank_of(pool[1], pool), P)
    c = {**pool[0], "text": "Built REST APIs in Go\nat Acme, 2019 - now. <script>",
         "requirements": [{**pool[0]["requirements"][0], "quote": "built rest apis; Acme", "found": True, "counted": "met"}],
         "dimensions": {d: {**pool[0]["dimensions"][d], "quote": "REST APIs in Go" if d == DIMS[0] else ""} for d in DIMS}}
    page, n = evidence_html(c, LIGHT)
    assert n == 2 and page.count("<mark") == 2 and "&lt;script&gt;" in page  # the skill quote overlaps the requirement mark
    assert "Must (met): Must line 1 · Skill: Technical Skills" in page
    assert experience_scatter([{**pool[0], "years": None}], LIGHT) is None and bar_height(10) == 480
    spans = ins.career_spans([{"role": "Engineer (Full time)", "employer": "A&B", "start": "2019-03", "end": None, "is_current": True},
                              {"role": "Intern", "employer": "C", "start": "2018-06", "end": "2018-08"}], date(2026, 10, 1))[0]
    page = career_html(spans, LIGHT)
    assert page.index("@ A&amp;B") < page.index("@ C")  # newest first, text escaped
    assert "Mar 2019 – now · 7 yr 8 mo" in page
    assert "Jun 2018 – Aug 2018 · 3 mo" in page and ">2019<" in page and career_html([], LIGHT) == ""
    rows = badge_rows_html([("B", "T1", [("n", None)]), ("B", "T2", [])], LIGHT)
    assert rows.count("grid-template-columns") == 2 and rows.count("border-top:0") == 1
    print("self-check OK")
