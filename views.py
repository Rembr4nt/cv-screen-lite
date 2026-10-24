"""The campaign, candidate and compare pages.

app.py builds the st.Page objects from these functions and sets views.PAGES before the navigation runs.
Everything the model or a CV wrote goes through style.esc (markdown) or html.escape (HTML).
"""
import html
import statistics
import textwrap
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import streamlit as st

import charts
import insights as ins
import scoring as sc
import style
import workspace
from charts import SERIES, SEVERITY
from style import STATUS, chip, esc

PAGES = {}  # filled by app.py: campaigns, chat, new, campaign, candidate, compare
PAGE_SIZE = 25
ROW_COLUMNS = [16, 1.7]  # ranking row: html | Details link (the header uses the same split so the columns line up)
HIDE_BAR = {"displayModeBar": False}


# ---------- small shared pieces ----------

def link(page, label, icon=None, **params):
    st.page_link(PAGES[page], label=label, icon=icon, query_params=params or None)


@contextmanager
def card(key, title=None, sub=None):
    with st.container(border=True, key=f"card_{key}"):
        if title:
            st.html(f'<div style="font-size:1.05rem;font-weight:700;letter-spacing:-0.01em">{html.escape(title)}</div>')
        if sub:
            st.caption(sub)
        yield


def row(key, spec=2):
    """Columns whose cards all stretch to the tallest one (style.apply_css), so a short card leaves no hole."""
    return st.container(key=f"pair_{key}").columns(spec, gap="small")


def pair(key, *draws):
    for col, draw in zip(row(key, len(draws)), draws):
        with col:
            draw()


def texts(value):
    """A model field that should be a list of strings, whatever it came back as."""
    return [str(x) for x in (value if isinstance(value, list) else [value] if value else [])]


def chips(items, colors, **kw):
    return "".join(chip(i, colors, **kw) for i in items)


def show(markup):
    """st.html refuses an empty string."""
    if markup:
        st.html(markup)


def facts_html(rows, P):
    """Label / value rows; an empty value shows a dash."""
    return "".join(
        f'<div style="display:flex;gap:0.6rem;padding:0.4rem 0.65rem;margin-bottom:5px;border-radius:0.6rem;background:{P.soft};'
        f'font-size:0.82rem"><span style="width:6.2rem;flex:none;color:{P.muted}">{html.escape(k)}</span>'
        f'<span style="min-width:0;overflow-wrap:anywhere;color:{P.ink}">{html.escape(str(v)) if v else "—"}</span></div>'
        for k, v in rows)


def label_html(text, P):
    """A small uppercase section label inside a card."""
    return (f'<div style="font-size:0.75rem;font-weight:700;letter-spacing:0.05em;text-transform:uppercase;color:{P.muted};'
            f'margin-bottom:0.3rem">{html.escape(text)}</div>')


def bullets_html(items, P, empty="None found."):
    if not items:
        return f'<div style="font-size:0.9rem;color:{P.muted}">{empty}</div>'
    return (f'<ul style="margin:0;padding-left:1.1rem;font-size:0.9rem;line-height:1.5;color:{P.ink}">'
            + "".join(f'<li style="margin-bottom:0.2rem">{i}</li>' for i in items) + "</ul>")


def heading(text, sub=None):
    st.markdown(f"## {esc(text)}")
    if sub:
        st.caption(sub)


def current_campaign():
    """(id, campaign) from ?c=, or a message and stop."""
    cid = st.query_params.get("c") or ""
    if not cid or cid != Path(cid).name or not (workspace.ROOT / cid / "campaign.json").exists():
        st.warning("This campaign was not found.")
        link("campaigns", "Back to Campaigns", ":material/arrow_back:")
        st.stop()
    return cid, workspace.load(cid)


def start_button(cid, camp, status, key):
    """Resume the CVs still waiting, or retry the failed ones; hidden while nothing is pending or a run is going."""
    n = len(workspace.pending(cid))
    if not n or status["running"]:
        return
    label = f"Retry {n} failed" if n == status["failed"] else f"Resume {n} remaining"
    if st.button(label, key=key, type="primary", icon=":material/refresh:"):
        workspace.start(cid, st.session_state.get("model") or camp["model"])
        st.rerun()


@st.fragment(run_every="2s")
def progress(cid, seen):
    """Progress bar for a running screening; any change (a CV finished, the run ended) redraws the whole page."""
    s = workspace.status(cid)
    if s["running"] and s["job_done"] == seen:
        st.progress(s["job_done"] / max(s["job_total"], 1), text=f"Screening {s['job_done']} of {s['job_total']} CVs")
    else:
        st.rerun(scope="app")


# ---------- campaign page ----------

def campaign_page():
    P = style.palette()
    cid, camp = current_campaign()
    people = workspace.people(cid)
    ok = [c for c in people if c["ok"]]
    s = workspace.status(cid)

    link("campaigns", "Campaigns", ":material/arrow_back:")
    head, actions = st.columns([5, 3], vertical_alignment="bottom")
    with head:
        heading(camp["title"])
    with actions, st.container(horizontal=True, horizontal_alignment="right"):
        if st.button("Compare top 3", key="compare_top", icon=":material/compare_arrows:", disabled=len(ok) < 2):
            st.switch_page(PAGES["compare"], query_params={"c": cid, "cv": [c["file"] for c in ok[:3]]})
        start_button(cid, camp, s, "start_top")
    waiting = s["total"] - s["screened"] - s["failed"]
    st.caption(" · ".join([f"Created {datetime.fromisoformat(camp['created']):%d %b %Y, %H:%M}", esc(camp["model"]),
                           f"{s['total']} CVs", f"{s['screened']} screened"]
                          + ([f"{s['failed']} failed"] if s["failed"] else []) + ([f"{waiting} waiting"] if waiting else [])))
    if s["running"]:
        progress(cid, s["job_done"])

    want = st.query_params.get("tab", "overview")
    tab = st.segmented_control("View", ["Overview", "Ranking"], default=want.capitalize() if want in ("overview", "ranking") else "Overview",
                               required=True, label_visibility="collapsed")
    if tab.lower() != want:
        st.query_params["tab"] = tab.lower()
    if tab == "Ranking":
        ranking_tab(cid, camp, people, s, P)
    else:
        overview_tab(cid, camp, ok, P)


def ranking_tab(cid, camp, people, status, P):
    ok = [c for c in people if c["ok"]]
    failed = [c for c in people if not c["ok"]]
    st.caption("Match is the share of required lines a CV meets: met counts 1, partial ½, missing 0. A met whose quote is not in the CV "
               "counts as partial. Nice-to-haves only break ties. ⚑ N: lines the model called missing although the CV "
               "lists the technology; check them yourself.")
    if failed:
        lines = "\n".join(f"- **{esc(c['file'])}**: {esc(str(c.get('error'))[:300])}" for c in failed)
        st.warning(f"**{len(failed)} CV{'s' if len(failed) > 1 else ''} could not be screened**\n\n{lines}", icon=":material/error:")
        start_button(cid, camp, status, "start_failed")
    if not ok:
        st.info("Nothing is screened yet. Results appear here as each CV finishes.")
        return
    pages = -(-len(ok) // PAGE_SIZE)
    page = 1
    if pages > 1:
        page = st.segmented_control("Page", range(1, pages + 1), default=1, required=True, key=f"page_{cid}", label_visibility="collapsed",
                                    format_func=lambda p: f"{(p - 1) * PAGE_SIZE + 1}–{min(p * PAGE_SIZE, len(ok))}")
    start = (page - 1) * PAGE_SIZE
    st.columns(ROW_COLUMNS)[0].html(charts.ranking_header_html(P))
    with st.container(gap="xsmall"):
        for i, c in enumerate(ok[start:start + PAGE_SIZE], start):
            with st.container(key=f"row_{i}"):
                body, go = st.columns(ROW_COLUMNS, vertical_alignment="center")
                body.html(charts.ranking_row_html(c, i + 1, P))
                with go:
                    link("candidate", "Details", ":material/arrow_forward:", c=cid, cv=c["file"])


def overview_tab(cid, camp, ok, P):
    if not ok:
        st.info("Nothing is screened yet. The overview fills in as CVs finish.")
        return
    reqs = sc.requirement_list(camp)
    k, t = ins.kpis(ok), ins.trust(ok)
    s = workspace.status(cid)
    top = k["top"]

    done = f"{s['failed']} failed" if s["failed"] else "all done" if s["screened"] == s["total"] else None
    tiles = [("CVs screened", f"{s['screened']} of {s['total']}", done),
             ("Average Match", f"{k['avg']}%", None),
             ("Top Match", f"{top['grade']} · {top['fit']}%", top["name"]),
             ("Meet every must-have", str(k["every"]), f"{k['every_pct']:.0%} of screened")]
    for i, (col, (label, value, sub)) in enumerate(zip(row("kpi", 4), tiles)):
        with col, st.container(border=True, key=f"card_kpi{i}"):
            st.metric(label, value, sub, delta_color="off", delta_arrow="off")
    if t["claimed"]:
        cut = f"; {t['cut']} 'met' {'was' if t['cut'] == 1 else 'were'} cut to partial" if t["cut"] else ""
        check = (f" {t['check']} line{'s' if t['check'] > 1 else ''} the model called missing ({t['check_people']} candidate"
                 f"{'s' if t['check_people'] > 1 else ''}) name a technology the CV lists, so they count as partial: worth a look."
                 if t["check"] else "")
        st.caption(f"{t['found'] / t['claimed']:.0%} of claimed matches quote the CV verbatim{cut}.{check}")

    block, nobody = ins.bottleneck(ok, reqs)
    if block or nobody:
        lines = []
        if block:
            lines.append(f"**Bottleneck:** '{esc(block['text'])}' is missing for {block['blocked']} of the {block['of']} candidates "
                         f"closest to a full match; only {block['met']} of {len(ok)} meet it.")
        if nobody:
            lines.append("**Nobody meets:** " + "; ".join(esc(r["text"]) for r in nobody))
        st.warning("\n\n".join(lines), icon=":material/warning:")

    cov = ins.coverage(ok, reqs)
    with card("coverage", "Requirement coverage", "How many candidates meet each line, rarest first."):
        st.altair_chart(charts.coverage_bars(cov, P), height=charts.bar_height(len(cov)))

    left, right = row("near")
    gap, near = ins.near_misses(ok, None)
    must = lambda n: f"{n} must-have{'s' if n > 1 else ''}"  # noqa: E731
    note = ((f"Missing only {must(gap)}." if gap <= 2 else f"Nobody is within two must-haves; the closest still miss {gap}.")
            + " Red: missing, yellow: partial; hover a line for the evidence." if gap else "Everyone meets every must-have.")
    with left, card("near", "Closest to a full match", note):
        for c, unmet in near[:3]:
            link("candidate", f"{esc(c['name'])} · {c['grade']} {c['fit']}%", c=cid, cv=c["file"])
            st.html("".join(chip(r["text"], getattr(P, STATUS[r["counted"]]), size="0.75rem", tip=r["quote"] or r["reason"])
                            for r in unmet))
        if len(near) > 3:
            st.caption(f"and {len(near) - 3} more in the ranking")
    with right, card("gems", "Don't lose these", "A strong 12-skill profile but a below-median Match."):
        gems = ins.hidden_gems(ok)
        for c in gems:
            link("candidate", esc(c["name"]), c=cid, cv=c["file"])
            top3 = sorted(c["dimensions"].items(), key=lambda kv: -kv[1]["score"])[:3]
            st.html(chips([f"{ins.DIM_FULL[d]} {x['score']:g}" for d, x in top3], P.mint))
            missed = [r["text"] for r in c["requirements"] if r["must"] and r["counted"] != "met"]
            st.caption(f"Skill profile **{c['profile']:g}** vs Match **{c['fit']}%**"
                       + (f" · misses {esc('; '.join(textwrap.shorten(t, 48, placeholder='…') for t in missed[:2]))}" + (f" and {len(missed) - 2} more" if len(missed) > 2 else "") if missed else ""))
        if not gems:
            st.caption("No one stands out this way.")

    left, right = row("scatter")
    levels = " · ".join(f"{name} {n}" for name, n in ins.levels(ok))
    with left, card("scatter", "Experience vs Match", levels):
        chart = charts.experience_scatter(ok, P)
        if chart is None:
            st.caption("No years of experience found in the CVs.")
        else:
            st.altair_chart(chart, height=320)
    with right, card("grades", "Grade distribution", "Requirement Match grade per candidate."):
        st.altair_chart(charts.grade_bars(ins.grades(ok), P, 320), height=320)

    left, right = row("strength")
    with left, card("strength", "Pool strength profile", "Median score per skill, weakest first."):
        rows = ins.strength_profile(ok)
        st.altair_chart(charts.strength_chart(rows, P), height=charts.bar_height(len(rows)))
    with right, card("skills", "Skill landscape", "Most common verified technologies, and whether the job text asks for them."):
        land = ins.skill_landscape(ok, " ".join(camp["responsibilities"] + camp["required"] + camp["nice"]))
        chart = charts.skill_chart(land, P)
        if chart is None:
            st.caption("No technologies found in the CVs.")
        else:
            st.altair_chart(chart, height=charts.bar_height(len(land), 26))

    flags = ins.flags_to_check(ok)
    with card("flags", "Red flags to check", "Gaps, inconsistencies and short or missing roles, for the people you would likely talk to first."):
        if not flags:
            st.caption("Nothing to check.")
        else:
            with st.expander(f"{len(flags)} candidate{'s' if len(flags) != 1 else ''} with flags"):
                for c, items in flags:
                    link("candidate", esc(c["name"]), c=cid, cv=c["file"])
                    st.markdown("\n".join(f"- {esc(i)}" for i in items))


# ---------- candidate page ----------

def candidate_page():
    P = style.palette()
    cid, camp = current_campaign()
    people = workspace.people(cid)
    ok = [c for c in people if c["ok"]]
    c = next((x for x in people if x["file"] == st.query_params.get("cv")), None)
    if c is None:
        st.warning("This candidate was not found.")
        link("campaign", "Back to the ranking", ":material/arrow_back:", c=cid, tab="ranking")
        st.stop()
    if not c["ok"]:
        link("campaign", "Ranking", ":material/arrow_back:", c=cid, tab="ranking")
        heading(c["name"])
        st.error(f"This CV could not be screened: {esc(str(c.get('error')))}")
        start_button(cid, camp, workspace.status(cid), "start_one")
        st.stop()

    i = ok.index(c)
    back, who, nav = st.columns([1.3, 5, 3.8], vertical_alignment="center")
    with back:
        link("campaign", "Ranking", ":material/arrow_back:", c=cid, tab="ranking")
    who.html(f'<div style="display:flex;align-items:center;gap:0.7rem;flex-wrap:wrap">{style.avatar(c["name"], P, 42)}'
             f'<span style="font-size:1.5rem;font-weight:700;letter-spacing:-0.02em;color:{P.ink}">{html.escape(c["name"])}</span>'
             f'<span>{chip(f"#{i + 1} of {len(ok)}", P.grey)}{style.gap_pill(c, P)}'
             f'{chip(c["grade"], style.band_colors(c["fit"], P), bold=True)}</span></div>')
    with nav, st.container(horizontal=True, horizontal_alignment="right", vertical_alignment="center"):
        for j, label, icon in ((i - 1, "Previous", ":material/chevron_left:"), (i + 1, "Next", ":material/chevron_right:")):
            near = ok[j] if 0 <= j < len(ok) else c
            st.page_link(PAGES["candidate"], label=label, icon=icon, disabled=near is c, query_params={"c": cid, "cv": near["file"]})
        original = workspace.ROOT / cid / "cvs" / c["file"]
        if original.is_file():
            st.download_button("Original CV", original.read_bytes(), file_name=c["file"], on_click="ignore", icon=":material/download:")

    st.html(charts.banner_html(c, P))
    view = st.segmented_control("View", ["Details", "Compare"], default="Details", required=True, key="candidate_view",
                                label_visibility="collapsed")
    if view == "Compare":
        by_file = {x["file"]: x for x in ok if x is not c}
        nearby = (ok[i + 1:] + ok[:i][::-1])[:2]
        pick = st.multiselect("Compare with", list(by_file), default=[x["file"] for x in nearby], max_selections=3,
                              format_func=lambda f: by_file[f]["name"])
        if pick:
            compare_view(cid, [c] + [by_file[f] for f in pick], P)
        else:
            st.info("Pick at least one other candidate to compare with.")
        return

    pair("who", lambda: summary_card(c, P), lambda: standing_card(c, ok, P))
    pair("next", lambda: moves_card(c, ok, P), lambda: career_card(c, P))
    pair("fit", lambda: requirements_card(c, P), lambda: strengths_card(c, P))
    skills_card(c, ok, P)
    pair("cv", lambda: tech_card(c, P), lambda: evidence_card(c, P))


def moves_card(c, pool, P):
    rows, all_rank = ins.what_if(c, pool)
    if not rows:
        nice = ins.nice_if(c, pool)
        with card("moves", "What would move them up",
                  "Every must-have is met. Only nice-to-haves break ties now: worth asking about these."
                  if nice else "Every must-have and nice-to-have is met; nothing on the list holds them back."):
            if nice:
                show(charts.gain_rows_html(nice, c, ins.rank_of(c, pool), P))
            st.caption(f"Nice-to-haves met: {c['nice_met']} of {c['nice_total']}."
                       if c["nice_total"] else "This job has no nice-to-haves.")
        return
    with card("moves", "What would move them up",
              f"Ask about these first: Match and rank if the candidate can show the line. All {len(rows)}: 100%, #{all_rank}."):
        show(charts.gain_rows_html(rows[:6], c, ins.rank_of(c, pool), P))
        if len(rows) > 6:
            st.caption(f"and {len(rows) - 6} more")


def standing_card(c, pool, P):
    s, n = ins.standing(c, pool), len(pool)
    with card("standing", "Standing in this pool",
              f"#{s['match']} of {n} by Match · #{s['profile']} by 12-skill profile · #{s['years']} by years"):
        if n < 3:
            st.caption("Needs at least three screened candidates.")
            return
        st.altair_chart(charts.standing_chart(c, pool, P), height=300)
        high_fit = c["fit"] > statistics.median(x["fit"] for x in pool)
        high_profile = c["profile"] > statistics.median(x["profile"] for x in pool)
        st.caption({(True, True): "Above the pool median on both: the Match has depth behind it.",
                    (True, False): "Above the median on Match, not on the 12-skill profile: meets the list on thinner evidence.",
                    (False, True): "Above the median on the 12-skill profile, not on Match: good skills, partly off this job's list.",
                    (False, False): "Not above the pool median on either."}[(high_fit, high_profile)]
                   + " Dashed lines are the pool medians.")


def evidence_card(c, P):
    page, n = charts.evidence_html(c, P)
    with card("evidence", "The CV, with the evidence marked",
              f"{n} passage{'s' if n != 1 else ''} back the verdicts and scores above. Hover a mark to see what it proves."):
        show(chip("Met requirement", P.mint) + chip("Partial", P.lemon) + chip("Skill evidence", P.lavender))
        show(page)


def requirements_card(c, P):
    with card("requirements", "Requirement coverage", f"{c['must_met']} of {c['must_total']} must-haves met"
              + (f" · {c['nice_met']} of {c['nice_total']} nice-to-haves" if c["nice_total"] else "")):
        e, warn = html.escape, P.peach[1]
        for title, must in (("Must-haves", True), ("Nice to have", False)):
            items = []
            for r in (r for r in c["requirements"] if r["must"] == must):
                said = " · ".join([f"“{e(r['quote'])}”"] * bool(r["quote"]) + [e(r["reason"])] * bool(r["reason"]))
                notes = [(said, None)] * bool(said)
                if r["verdict"] in ("met", "partial") and not r["found"]:
                    notes.append(("Quote not found in the CV, counted as partial.", warn))
                if r.get("check"):
                    notes.append((f"The model said missing, but the CV lists {e(', '.join(r['check']))}, which this line names. "
                                  "A listed skill counts as partial; check this line yourself.", warn))
                items.append((chip(r["counted"].capitalize(), getattr(P, STATUS[r["counted"]]), bold=True), e(r["text"]), notes))
            if items:
                st.html(label_html(title, P) + charts.badge_rows_html(items, P))


def strengths_card(c, P):
    cs, rf, e = c["facts"]["contextual_summary"], c["facts"]["red_flags"], html.escape
    flags = [f"<b>{label}:</b> {e(f)}" for key, label in (("gaps", "Gap"), ("inconsistencies", "Inconsistency"),
                                                          ("missing_info", "Missing info")) for f in rf.get(key) or []]
    with card("strengths", "Strengths and weaknesses"):
        st.html(label_html("Strengths", P) + bullets_html([e(i) for i in cs["strengths"]], P))
        st.html(label_html("Weaknesses", P) + bullets_html([e(i) for i in cs["weaknesses"]], P))
        if cs["unique_selling_points"]:
            st.html(label_html("Unique selling points", P) + bullets_html([e(i) for i in cs["unique_selling_points"]], P))
        st.html(label_html("Red flags (each one quotes the CV)", P) + bullets_html(flags, P))
        if c["facts"].get("dropped_flags"):
            st.caption(f"{c['facts']['dropped_flags']} more flag(s) were dropped because their quotes are not in the CV.")


def skills_card(c, pool, P):
    mine = {d: c["dimensions"][d]["score"] for d in ins.DIMS}
    median = {d: statistics.median(x["dimensions"][d]["score"] for x in pool) for d in ins.DIMS}
    with card("skills", "12 skills", f"Profile {c['profile']:g} out of 100 (average score × 10). Dotted: median of all screened candidates."):
        chart, notes = st.columns([2, 3], gap="medium", vertical_alignment="center")
        chart.plotly_chart(charts.radar([(c["name"], mine, SERIES[0])], P, median, height=420), width="stretch", config=HIDE_BAR)
        e, items = html.escape, []
        for d in ins.DIMS:
            x = c["dimensions"][d]
            items.append((chip(f"{x['score']:g}", style.band_colors(x["score"], P, 10), bold=True),
                          f"<b>{ins.DIM_FULL[d]}</b> · {e(x['evidence'])}",
                          [(f"“{e(x['quote'])}”", None) if x["quote"] else ("Quote not verified", P.peach[1])]
                          + [(f'<span style="color:{P.rose[1]}">Weakness</span> {e(x["weakness"])}', None)] * bool(x["weakness"])))
        notes.html(f'<div style="max-height:420px;overflow-y:auto;padding-right:0.5rem">{charts.badge_rows_html(items, P, "2.4rem")}</div>')


def summary_card(c, P):
    ed, cs = c["facts"]["extracted_data"], c["facts"]["contextual_summary"]
    with card("summary", "Summary"):
        st.markdown(esc(c["scoring"]["fit_summary"]))
        if cs["career_narrative"]:
            st.caption(esc(cs["career_narrative"]))
        st.html(facts_html([("Education", ed.get("highest_education")), ("Experience", c["experience"]),
                            ("Languages", ", ".join(texts(ed.get("languages")))), ("Domains", ", ".join(texts(ed.get("industry_domains")))),
                            ("Certifications", ", ".join(texts(ed.get("certifications"))))], P))


def career_card(c, P):
    history = c["facts"]["extracted_data"].get("employment_history")
    spans = ins.career_spans(history)[0]
    with card("career", "Career"):
        if spans:
            st.html(charts.career_html(spans, P))
        else:
            st.caption("No dated employment found in the CV.")
        show("".join(chip(text, getattr(P, SEVERITY[sev])) for sev, text in ins.career_notes(history)))


def tech_card(c, P):
    ed = c["facts"]["extracted_data"]
    techs, unverified, projects = texts(ed.get("key_technologies")), texts(ed.get("key_technologies_unverified")), texts(ed.get("notable_projects"))
    with card("tech", "Technologies"):
        if not (techs or unverified):
            st.caption("No technologies listed.")
        show(chips(techs, P.sky) + "".join(chip(t, P.grey, outline=P.grid, tip="Not found in the CV text") for t in unverified))
        if unverified:
            st.caption("Grey: the model listed it, but the CV text never mentions it.")
        if projects:
            st.html(label_html("Notable projects", P) + bullets_html([html.escape(p) for p in projects], P))


# ---------- compare ----------

def compare_page():
    P = style.palette()
    cid, camp = current_campaign()
    ok = [c for c in workspace.people(cid) if c["ok"]]
    link("campaign", "Ranking", ":material/arrow_back:", c=cid, tab="ranking")
    heading("Compare candidates", camp["title"])
    if len(ok) < 2:
        st.info("At least two screened CVs are needed to compare.")
        return
    by_file = {c["file"]: c for c in ok}
    wanted = [f for f in st.query_params.get_all("cv") if f in by_file][:4]
    pick = st.multiselect("Candidates", list(by_file), default=wanted if len(wanted) >= 2 else [c["file"] for c in ok[:3]],
                          max_selections=4, format_func=lambda f: by_file[f]["name"])
    if len(pick) < 2:
        st.info("Pick two to four candidates.")
        return
    compare_view(cid, [c for c in ok if c["file"] in pick], P)


def weaknesses(c):
    """Verified inconsistencies first, then the skill weaknesses with the biggest shortfall (the worst one if none is big)."""
    ranked = sorted(((10 - d["score"], d["weakness"].strip()) for d in c["dimensions"].values() if d["weakness"].strip()), reverse=True)
    big = [w for gap, w in ranked if gap >= 4] or [w for _, w in ranked[:1]]
    return list(dict.fromkeys((c["facts"]["red_flags"].get("inconsistencies") or []) + big))[:3]


def compare_view(cid, cands, P):
    """Best fit, one card per candidate, radar, head-to-head, coverage and score matrices (2 to 4 candidates)."""
    pool = [c for c in workspace.people(cid) if c["ok"]]
    first, second = sc.rank(list(cands))[:2]
    gap = first["fit"] - second["fit"]
    a, b = esc(first["name"]), esc(second["name"])
    st.success(f"**{a}** leads with {first['grade']} · {first['fit']}%, {gap} point{'s' if gap != 1 else ''} over {b}." if gap
               else f"**{a}** and **{b}** are level at {first['fit']}%; the nice-to-haves and skill profile decide.",
               icon=":material/emoji_events:")

    techs = [{ins.words(t): t for t in c["facts"]["extracted_data"].get("key_technologies") or [] if ins.words(t)} for c in cands]
    for i, (col, c) in enumerate(zip(row("verdicts", len(cands)), cands)):
        color = SERIES[i % len(SERIES)]
        ed = c["facts"]["extracted_data"]
        strong = [d for d, x in sorted(c["dimensions"].items(), key=lambda kv: -kv[1]["score"]) if x["score"] >= 7][:3]
        only = [t for k, t in techs[i].items() if not any(k in other for j, other in enumerate(techs) if j != i)]
        weak = weaknesses(c)
        with col, st.container(border=True, key=f"card_verdict{i}"):
            st.html(f'<div style="height:4px;border-radius:4px;background:{color};margin-bottom:0.6rem"></div>'
                    f'<div style="font-weight:700;font-size:1.05rem;color:{P.ink};margin-bottom:0.3rem">{html.escape(c["name"])}</div>'
                    f'{style.match_pill(c, P)}{style.gap_pill(c, P)}')
            st.html(facts_html([("Must-haves", f"{c['must_met']} of {c['must_total']}"), ("Nice-to-haves", f"{c['nice_met']} of {c['nice_total']}"),
                                ("Experience", c["experience"]), ("Education", ed.get("highest_education"))], P))
            st.markdown("**Strengths**")
            st.html(chips([f"Strong {ins.DIM_FULL[d].lower()}" for d in strong], P.mint) if strong else f'<span style="color:{P.muted}">None stands out.</span>')
            st.markdown("**Weaknesses**")
            st.markdown("\n".join(f"- :red[{esc(w)}]" for w in weak) if weak else "None found.")
            if only:
                st.markdown("**Only this candidate lists**")
                st.html(chips(only[:10], (style.rgba(color, 0.14), color), outline=color))

    median = {d: statistics.median(x["dimensions"][d]["score"] for x in pool) for d in ins.DIMS}
    two = len(cands) == 2
    left, right = row("radar") if two else (st.container(), None)
    with left, card("radar", "Skills compared"):
        show = st.toggle("Pool median", value=True)
        series = [(c["name"], {d: c["dimensions"][d]["score"] for d in ins.DIMS}, SERIES[i % len(SERIES)]) for i, c in enumerate(cands)]
        st.plotly_chart(charts.radar(series, P, median if show else None), width="stretch", config=HIDE_BAR)
    if two:
        with right, card("delta", "Head-to-head", "How far each candidate is ahead, per skill (points out of 10)."):
            st.html(charts.delta_bars(cands[0], cands[1], P))
    with card("coverage_matrix", "Requirement coverage", "✓ met · ? partial · ✗ missing. Hover a cell for the quote."):
        st.html(charts.coverage_matrix(cands, P))
    with card("score_matrix", "Score matrix", "Out of 10; the best score in each row is ringed. Hover a cell for the evidence."):
        st.html(charts.score_matrix(cands, P))
