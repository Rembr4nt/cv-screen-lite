"""CV Screen Lite: navigation, sidebar and the campaigns, new-campaign and chat pages.
The campaign, candidate and compare pages are in views.py. Run: streamlit run app.py"""
import hashlib
import html
import math
import re
import statistics
from datetime import datetime
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")  # before workspace reads CVSCREEN_WORKSPACE and CV_WORKERS

import scoring  # noqa: E402
import style  # noqa: E402
import views  # noqa: E402
import workspace  # noqa: E402
from style import band_colors, chip, esc, match_pill  # noqa: E402

CARD_H = 330  # every campaign card has this height, so a row of cards lines up
# Measured 2026-10-23, both calls for one CV: gpt-oss:120b-cloud ~16 s one CV at a time; claude-haiku-5-5 ~40 s, 4 at a time.
SECONDS_PER_CV = {"ollama": 16, "claude": 40}
UPLOADS = ["zip", "pdf", "docx", "txt"]
FORM = ("new_title", "new_resp", "new_req", "new_nice", "chat_cid", "chat_scope", "chat_who")  # kept across pages


@st.cache_data(ttl=60, show_spinner=False)
def models():
    return scoring.available_models()


def tag(cid):
    """A short stable id for widget keys (a campaign id has spaces and dots)."""
    return hashlib.md5(cid.encode()).hexdigest()[:8]


def lines(text):
    """One item per line, without the bullet or number in front."""
    return [t for line in text.splitlines() if (t := re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", line).strip())]


def kv(rows):
    return "".join(f'<div style="display:flex;justify-content:space-between;align-items:center;gap:12px;min-height:28px;'
                   f'font-size:0.9rem"><span style="color:{P.muted}">{k}</span><span style="text-align:right;min-width:0">'
                   f'{v}</span></div>' for k, v in rows)


def read(files, key):
    """Read the uploaded files once per upload (zips and PDFs are slow to open)."""
    ids = [f.file_id for f in files]
    if st.session_state.get(f"{key}_ids") != ids:
        with st.spinner("Reading CVs..."):
            st.session_state[f"{key}_read"] = scoring.read_uploads([(f.name, f.getvalue()) for f in files])
        st.session_state[f"{key}_ids"] = ids
    return st.session_state[f"{key}_read"]


def read_summary(cvs, skipped):
    st.html(chip(f"{len(cvs)} CV{'s' if len(cvs) != 1 else ''} ready", P.mint if cvs else P.grey, bold=True))
    if skipped:
        st.warning("**Skipped**\n\n" + "\n".join(f"- {esc(name)}: {reason}" for name, reason in skipped), icon=":material/block:")


# ---------- campaigns ----------

def card_body(c, live=False):
    """The numbers on a campaign card; while it screens this runs as a fragment that refreshes every 2 s."""
    cid = c["id"]
    s = workspace.status(cid)
    if live and not s["running"]:
        st.rerun(scope="app")  # the run just ended: redraw the whole page
    ok = [p for p in workspace.people(cid) if p["ok"]]
    created = datetime.fromisoformat(c["created"])
    meta = chip(f"Created {created.day} {created:%b}", P.grey) + chip(c["model"], P.sky)
    failed = f' <span style="color:{P.rose[1]}">· {s["failed"]} failed</span>' if s["failed"] else ""
    top = ok[0] if ok else None
    avg = round(statistics.mean(p["fit"] for p in ok)) if ok else None
    name = (f'<span style="display:inline-block;max-width:8.5rem;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;'
            f'vertical-align:bottom">{html.escape(top["name"])}</span> {match_pill(top, P)}') if top else "-"
    st.html(f'<div style="line-height:1.4">{meta}</div>' + kv([
        ("Candidates", f'<b>{s["screened"]}</b> of {s["total"]} CVs{failed}'),
        ("Top match", name),
        ("Average match", chip(f"{avg}%", band_colors(avg, P), bold=True) if ok else "-")]))
    if s["running"]:
        st.progress(s["job_done"] / s["job_total"] if s["job_total"] else 0, text=f"AI screening... {s['job_done']}/{s['job_total']}")
    elif not s["total"]:
        st.html(chip("No CVs yet", P.grey))
    elif s["failed"]:
        st.html(chip("Some CVs failed · open to retry", P.rose))
    elif s["screened"] < s["total"]:
        st.html(chip(f"{s['total'] - s['screened']} waiting · open to resume", P.lemon))
    else:
        st.html(chip("Screening complete", P.mint))


live_body = st.fragment(run_every="2s")(card_body)


@st.dialog("Add CVs")
def add_dialog(c):
    cid, k = c["id"], tag(c["id"])
    st.caption(f"To {esc(c['title'])}")
    if workspace.status(cid)["running"]:
        st.info("Screening is still running. Add more CVs when it finishes.")
        return
    files = st.file_uploader("CVs", type=UPLOADS, accept_multiple_files=True, key=f"up_{k}", label_visibility="collapsed")
    if not files:
        return
    cvs, skipped = read(files, f"add_{k}")
    read_summary(cvs, skipped)
    model = c["model"] if c["model"] in models() else st.session_state.get("model")  # one campaign, one model
    st.caption(f"Screened with {model}" if model else "No model available.")
    if st.button("Add CVs & screen", type="primary", disabled=not (cvs and model), width="stretch"):
        workspace.add_cvs(cid, cvs)
        workspace.start(cid, model)
        st.rerun()


def campaign_card(c, running):
    cid, k = c["id"], tag(c["id"])
    with st.container(border=True, key=f"card_c_{k}", height=CARD_H, vertical_alignment="distribute", gap="xsmall"):
        link, menu = st.columns([7, 1], vertical_alignment="top")
        link.page_link(PAGES["campaign"], label=esc(c["title"]), icon=":material/folder_open:", query_params={"c": cid}, width="stretch")
        with menu.popover(":material/more_horiz:", type="tertiary"):
            sure = st.checkbox("Delete this campaign and all its results", key=f"ok_{k}", disabled=running)
            if running:
                st.caption("Screening is running. You can delete it when it finishes.")
            if st.button("Delete", key=f"del_{k}", icon=":material/delete:", type="primary", disabled=not sure or running):
                workspace.delete(cid)
                st.toast(f"Deleted {esc(c['title'])}")
                st.rerun()
        (live_body if running else card_body)(c, running)
        open_, add = st.columns(2)
        if open_.button("Open", key=f"open_{k}", width="stretch"):
            st.switch_page(PAGES["campaign"], query_params={"c": cid, "tab": "ranking"})
        if add.button("Add CVs", key=f"add_{k}", icon=":material/upload_file:", width="stretch"):
            add_dialog(c)


def new_tile(empty):
    with st.container(border=True, key="card_c_new", height=CARD_H, vertical_alignment="center", horizontal_alignment="center"):
        st.html(
            f'<div style="text-align:center"><span style="display:inline-flex;align-items:center;justify-content:center;'
            f'width:64px;height:64px;border-radius:999px;background:{style.rgba(P.primary, 0.15)};color:{P.primary}">'
            + style.svg_icon(["M12 5v14M5 12h14"], P.primary, 30, 2.4) + '</span>'
            '<div style="font-size:1.25rem;font-weight:700;margin-top:14px">Create New Campaign</div>'
            f'<div style="color:{P.muted};font-size:0.9rem">{"No campaigns yet. Start your first one." if empty else "Start a new recruitment campaign"}</div></div>')
        if st.button("New campaign", key="start_btn", type="primary", icon=":material/add:"):
            st.switch_page(PAGES["new"])


def campaigns_page():
    head, search = st.columns([3, 1], vertical_alignment="bottom")
    head.title("Campaigns")
    head.caption("Every hiring campaign. Open one to see its candidates.")
    q = search.text_input("Search", placeholder="Search campaigns...", icon=":material/search:", key="camp_q", label_visibility="collapsed")
    camps = workspace.campaigns()
    shown = [c for c in camps if q.strip().lower() in c["title"].lower()]
    running = {c["id"]: workspace.status(c["id"])["running"] for c in shown}
    shown.sort(key=lambda c: not running[c["id"]])  # screening ones first
    items = [None] + shown
    for i in range(0, len(items), 3):
        for col, c in zip(st.columns(3), items[i:i + 3]):
            with col:
                if c:
                    campaign_card(c, running[c["id"]])
                else:
                    new_tile(not camps)
    if camps and not shown:
        st.caption(f"No campaign matches {esc(q.strip())}.")


# ---------- new campaign ----------

def new_page():
    st.session_state["_on_new"] = True
    st.page_link(PAGES["campaigns"], label="Campaigns", icon=":material/arrow_back:")
    st.title("New campaign")
    st.caption("Describe the job, add the CVs, and the AI screens each CV against it.")
    model = st.session_state.get("model")
    left, right = st.columns([3, 2], gap="large")

    with left, st.container(border=True, key="card_setup"):
        st.markdown("#### 1 · Campaign setup")
        st.caption("One item per line. A leading dash or number is fine.")
        title = st.text_input("Position :red[*]", placeholder="e.g. Full Stack Developer", key="new_title")
        resp = lines(st.text_area("Job Responsibility :red[*]", height=120, key="new_resp",
                                  placeholder="- Design and build ...\n- Collaborate with ...\n- ..."))
        req = lines(st.text_area("Required (Must Have) :red[*]", height=120, key="new_req",
                                 placeholder="- Minimum 3 years ...\n- ...\n- ..."))
        st.caption("Lines the CV must show. Each one counts equally in Requirement Match.")
        nice = lines(st.text_area("Nice to Have", height=120, key="new_nice",
                                  placeholder="- Excellent in ...\n- ...\n- ..."))
        st.caption("Shown separately and used to break ties.")

    with right, st.container(border=True, key="card_files"):
        st.markdown("#### 2 · Upload CVs")
        st.caption("PDF, DOCX or TXT files, or a .zip of them.")
        files = st.file_uploader("CVs", type=UPLOADS, accept_multiple_files=True, key="up_new", label_visibility="collapsed")
        if files:
            cvs, skipped = read(files, "new")
        else:
            if st.session_state.get("new_seen") and not RETURNING:  # emptied by the user, not by leaving the page
                for k in ("new_read", "new_ids"):
                    st.session_state.pop(k, None)
            cvs, skipped = st.session_state.get("new_read", ([], []))
            if cvs:
                st.caption("Kept from your last visit. Upload files again to replace them.")
        st.session_state["new_seen"] = [f.file_id for f in files]
        read_summary(cvs, skipped)

    with right, st.container(border=True, key="card_review"):
        st.markdown("#### 3 · Review & launch")

        def count(items):
            return chip(len(items), P.mint if items else P.grey, bold=True)

        claude = bool(model and model.startswith("claude-"))
        per, at_once = (SECONDS_PER_CV["claude"], workspace.WORKERS) if claude else (SECONDS_PER_CV["ollama"], 1)
        mins = max(1, round(math.ceil(len(cvs) / at_once) * per / 60))
        st.html(kv([("Responsibilities", count(resp)), ("Required", count(req)), ("Nice to have", count(nice)),
                    ("CVs", count(cvs)), ("Model", html.escape(model or "none")),
                    ("Estimated time", f"about {mins} min" if cvs else "-")]))
        st.caption(f"A rough estimate: about {per} s per CV, {at_once} CV{'s' if at_once > 1 else ''} at a time.")
        if model and model.startswith("claude-"):
            st.caption(":orange[Claude is a paid model.]")
        missing = [what for what, have in (("a position", title.strip()), ("a responsibility", resp), ("a required line", req),
                                           ("a CV", cvs), ("a model", model)) if not have]
        if st.button("Create campaign & start screening", type="primary", width="stretch", disabled=bool(missing)):
            cid = workspace.create(title.strip(), resp, req, nice, model, cvs)
            workspace.start(cid, model)
            for k in [k for k in st.session_state if k.startswith("new_")]:
                del st.session_state[k]  # the next new campaign starts blank
            st.switch_page(PAGES["campaign"], query_params={"c": cid, "tab": "ranking"})
        if missing:
            st.caption("Still needed: " + ", ".join(missing))


# ---------- chat ----------

ALL_STARTERS = ["Who is the strongest candidate, and why?", "Who meets every must-have?",
                "Compare the top three candidates.", "Which candidates have red flags I should check?"]
ONE_STARTERS = ["Summarize this candidate in three lines.", "Which must-haves are not met?",
                "What should I ask in the interview?", "Are there red flags in this CV?"]


def chat_page():
    st.title("Chat")
    st.caption("Ask about the candidates of one campaign. Answers come only from the job, the screening results and the CVs.")
    camps = workspace.campaigns()
    if not camps:
        st.info("No campaigns yet. Create one and screen some CVs first.")
        return
    by = {c["id"]: c for c in camps}
    qc = st.query_params.get("c")
    if qc in by and st.session_state.get("_chat_qc") != qc:  # arrived from a campaign page: start on that campaign
        st.session_state["chat_cid"] = st.session_state["_chat_qc"] = qc
    if st.session_state.get("chat_cid") not in by:
        st.session_state.pop("chat_cid", None)
    st.session_state.setdefault("chat_scope", "All candidates")

    pick_campaign, pick_scope, pick_who, clear = st.columns([3, 3, 3, 1], vertical_alignment="bottom")
    cid = pick_campaign.selectbox("Campaign", list(by), format_func=lambda i: by[i]["title"], key="chat_cid")
    people = workspace.people(cid)
    ok = [p for p in people if p["ok"]]
    if not ok:
        st.info("Nothing is screened in this campaign yet. Open it to see the progress.")
        return
    one = pick_scope.pills("Ask about", ["All candidates", "One candidate"], key="chat_scope", required=True) == "One candidate"
    names = {p["file"]: p["name"] for p in ok}
    if st.session_state.get("chat_who") not in names:
        st.session_state.pop("chat_who", None)
    who = pick_who.selectbox("Candidate", list(names), format_func=names.get, key="chat_who") if one else None
    hist = st.session_state.setdefault("chat_hist", {}).setdefault((cid, who or ""), [])
    clear.button("Clear", icon=":material/delete_sweep:", disabled=not hist, on_click=hist.clear, help="Clear this chat")

    model = st.session_state.get("model")
    if not model:
        st.warning("Pick a model in the sidebar to chat.")
    prompt = st.chat_input("Ask a question...", disabled=not model) or st.session_state.pop("_ask", None)
    with st.container(border=True, key="card_chat", height=480):
        if not hist and not prompt:
            st.markdown(f"##### Ask about {esc(names[who] if who else by[cid]['title'])}")
            st.caption(f"Answering from {'the CV and results of this candidate' if who else f'all {len(ok)} screened candidates'}.")
            cols = st.columns(2)
            for i, q in enumerate(ONE_STARTERS if who else ALL_STARTERS):
                cols[i % 2].button(q, key=f"ask_{i}", on_click=st.session_state.update, kwargs={"_ask": q}, width="stretch", disabled=not model)
        for m in hist:
            with st.chat_message(m["role"]):
                st.markdown(m["content"])
        if prompt and model:
            hist.append({"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.markdown(prompt)
            with st.chat_message("assistant"):
                try:
                    reply = st.write_stream(scoring.ask_stream(model, scoring.chat_system(by[cid], people, focus=who), list(hist)))
                    if not reply.strip():
                        raise ValueError("the model returned an empty reply")
                    hist.append({"role": "assistant", "content": reply})
                except scoring.LLM_ERRORS as e:
                    hist.pop()  # keep the turns alternating
                    st.error(f"No answer: {scoring.why(e)}")


# ---------- app ----------

TROPHY = ["M6 9H4.5a2.5 2.5 0 0 1 0-5H6", "M18 9h1.5a2.5 2.5 0 0 0 0-5H18", "M4 22h16",
          "M10 14.66V17c0 .55-.47.98-.97 1.21C7.85 18.75 7 20.24 7 22", "M14 14.66V17c0 .55.47.98.97 1.21C16.15 18.75 17 20.24 17 22",
          "M18 2H6v7a6 6 0 0 0 12 0V2Z"]  # the lucide "trophy" icon

st.set_page_config(page_title="CV Screen", page_icon=":material/workspace_premium:", layout="wide")
P = style.palette()
style.apply_css(P)
style.watch_theme(P)
st.html(f"""<style>
[class*="st-key-card_c_"] [data-testid="stPageLink-NavLink"] {{ padding:0; align-items:flex-start; }}
[class*="st-key-card_c_"] [data-testid="stPageLink-NavLink"] p {{ font-weight:700; font-size:1.05rem; line-height:1.3; min-height:2.6em;
    display:-webkit-box; -webkit-box-orient:vertical; -webkit-line-clamp:2; overflow:hidden; white-space:normal; }}
.st-key-card_c_new {{ border:2px dashed {style.rgba(P.muted, 0.45)}; box-shadow:none; background:{P.soft}; }}
.st-key-camp_q [data-baseweb="input"], .st-key-camp_q [data-baseweb="base-input"] {{ border-radius:999px; }}
</style>""")

PAGES = {
    "campaigns": st.Page(campaigns_page, title="Campaigns", icon=":material/folder_open:", url_path="campaigns", default=True),
    "chat": st.Page(chat_page, title="Chat", icon=":material/forum:", url_path="chat"),
    "new": st.Page(new_page, title="New campaign", icon=":material/add_circle:", url_path="new", visibility="hidden"),
    "campaign": st.Page(views.campaign_page, title="Campaign", url_path="campaign", visibility="hidden"),
    "candidate": st.Page(views.candidate_page, title="Candidate", url_path="candidate", visibility="hidden"),
    "compare": st.Page(views.compare_page, title="Compare", url_path="compare", visibility="hidden"),
}
views.PAGES = PAGES
nav = st.navigation(list(PAGES.values()), position="top")

# Streamlit drops the state of widgets a page did not draw: copy it so typed text survives a visit to another page.
for k in FORM:
    if k in st.session_state:
        st.session_state[k] = st.session_state[k]
RETURNING = not st.session_state.pop("_on_new", False)  # True on the first run of the new-campaign page after another page

with st.sidebar:
    st.html(
        '<div style="display:flex;align-items:center;gap:10px;padding:4px 2px 10px">'
        f'<span style="display:inline-flex;align-items:center;justify-content:center;width:34px;height:34px;border-radius:12px;'
        f'background:{P.lavender[0]}">' + style.svg_icon(TROPHY, P.lavender[1], 17) + '</span>'
        '<span style="line-height:1.2"><span style="display:block;font-weight:700;letter-spacing:-0.01em">CV Screen</span>'
        f'<span style="display:block;font-size:0.72rem;color:{P.muted}">AI Recruiter</span></span></div>')
    options = models()
    st.selectbox("Model", options, key="model", disabled=not options,
                 help="Ollama cloud models are free. claude-haiku-5-5 needs ANTHROPIC_API_KEY and is paid.")
    if not options:
        st.warning("No model found. Start Ollama (ollama serve) or set ANTHROPIC_API_KEY in .env.")

nav.run()
