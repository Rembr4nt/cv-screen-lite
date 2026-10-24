"""Formulas shared by scoring and the pages: Requirement Match and grades, colour bands, career notes and
pool insights. No Streamlit here.
Run `python insights.py` for the self-check.
"""
import math
import re
import statistics
from collections import Counter
from datetime import date

DIMS = [  # canonical order
    "technical_skills", "experience_relevance", "education_qualification", "project_complexity",
    "communication_skills", "leadership_experience", "industry_alignment", "continuous_learning",
    "achievement_impact", "career_progression", "tool_proficiency", "problem_solving",
]
DIM_FULL = {
    "technical_skills": "Technical Skills", "experience_relevance": "Experience Relevance",
    "education_qualification": "Education", "project_complexity": "Project Complexity",
    "communication_skills": "Communication", "leadership_experience": "Leadership",
    "industry_alignment": "Industry Alignment", "continuous_learning": "Continuous Learning",
    "achievement_impact": "Achievement Impact", "career_progression": "Career Progression",
    "tool_proficiency": "Tool Proficiency", "problem_solving": "Problem Solving",
}
CREDIT = {"met": 1.0, "partial": 0.5, "missing": 0.0}
GRADES = ((90, "A"), (80, "A-"), (70, "B+"), (60, "B"), (45, "C"))
GRADE_ORDER = ["A", "A-", "B+", "B", "C", "D"]
BAND_LABELS = ["Weak", "Low", "Mid", "Good", "Strong"]


def band(value, top=100):
    """0-4 colour band: thresholds at 30 / 50 / 65 / 80 % of the maximum."""
    pct = max(0, min(100, value / top * 100)) if top else 0
    return sum(pct >= t for t in (30, 50, 65, 80))


def fit_score(rows):
    """Requirement Match % over the Required rows: met 1, partial 0.5, missing 0; half-up rounding."""
    if not rows:
        return None
    return int(100 * sum(CREDIT[r["counted"]] for r in rows) / len(rows) + 0.5)


def fit_grade(score):
    if score is None:
        return None
    return next((g for floor, g in GRADES if score >= floor), "D")


def words(text):
    return " ".join(re.findall(r"\w+", str(text).lower()))


def mentions(term, text_words):
    """Whole-word match of a term inside already-normalised text."""
    t = words(term)
    return bool(t) and f" {t} " in f" {text_words} "


# ---------- career ----------

def _role_kind(role, employer=""):
    """'org' (a student or volunteer organisation) is told by the employer too: "Head of AI" at a company is a job."""
    r, both = role.lower(), f"{role} {employer}".lower()
    for kind, pat, text in (
        ("full_time", r"\bfull[\s-]?time\b", r), ("internship", r"\bintern(ship)?\b|\bmagang\b", r),
        ("contract", r"\bcontract\b", r),
        ("research", r"\b(research|practicum|lab|teaching)\s+assistant\b|\bpeer tutor\b|\bmentor\b|\bassistant\b", r),
        ("owner", r"\b(owner|founder|freelance|self[\s-]?employed)\b", r),
        ("org", r"\b(chair|treasurer|secretar)|\b(himpunan|bem|student|mahasiswa|committee|association|panitia|volunteer"
                r"|organizing|club|ukm|society|fundrais)", both),
        ("project", r"\bproject\b", r),
    ):
        if re.search(pat, text):
            return kind
    return "unknown"


def _start_month(s):
    if not isinstance(s, str):
        return None
    if m := re.fullmatch(r"(\d{4})-(\d{2})", s.strip()):
        return int(m[1]) * 12 + int(m[2])
    if m := re.fullmatch(r"(\d{4})", s.strip()):
        return int(m[1]) * 12 + 1
    return None


def _end_month(s):
    if isinstance(s, str) and re.fullmatch(r"\d{4}", s.strip()):
        return int(s) * 12 + 12
    return _start_month(s)


def _is_current(e):
    end = e.get("end")
    return bool(e.get("is_current")) or end in (None, "") or (
        isinstance(end, str) and re.fullmatch(
            r"present|current|now|today|ongoing|to[\s-]?date|sekarang|hingga sekarang|-|–|—", end.strip(), re.I))


def _label(m):
    return f"{(m - 1) // 12}-{(m - 1) % 12 + 1:02d}"


def career_spans(history, today=None):
    """Employment rows with month indexes (organisation roles left out)."""
    today = today or date.today()
    now = today.year * 12 + today.month
    spans, incomplete, has_full_time = [], False, False
    for e in history or []:
        kind = _role_kind(e.get("role") or "", e.get("employer") or "")
        has_full_time |= kind == "full_time"
        if kind == "org":
            continue
        start = _start_month(e.get("start"))
        current = _is_current(e)
        end = now if current else _end_month(e.get("end"))
        if start is None or end is None or end < start:
            incomplete = True
            continue
        spans.append({"start": start, "end": end, "current": current, "kind": kind,
                      "role": e.get("role") or "", "employer": e.get("employer") or ""})
    return spans, incomplete, has_full_time, now


def career_years(history, fallback=None, today=None):
    """Years actually worked: overlapping roles count once. Falls back to the model's figure when the
    history has dates we cannot read."""
    spans, incomplete, _, _ = career_spans(history, today)
    if spans and not incomplete:
        months = set()
        for s in spans:
            months.update(range(s["start"], s["end"] + 1))
        return round(len(months) / 12, 1)
    try:
        return float(fallback) if fallback not in (None, "") else None
    except (TypeError, ValueError):
        return None


def level(years):
    if years is None:
        return None
    return "Entry" if years < 1 else "Junior" if years < 3 else "Mid" if years < 6 else "Senior"


def experience_text(years):
    if years is None:
        return "Not stated"
    n = round(years)
    return f"{level(years)} · " + ("under 1 yr" if years < 1 else f"about {n} yr{'s' if n != 1 else ''}")


def career_notes(history, today=None):
    """[(severity, text)], severity red / yellow / grey / green, worst first."""
    if not history:
        return []
    spans, incomplete, has_full_time, now = career_spans(history, today)
    notes = []
    months = lambda s: s["end"] - s["start"] + 1  # noqa: E731  inclusive: Jul -> Aug = 2
    if spans and not incomplete:
        ordered = sorted(spans, key=lambda s: (s["start"], s["end"]))
        cover, has_gap = ordered[0]["end"], False
        for s in ordered[1:]:
            if s["start"] <= cover:
                cover = max(cover, s["end"])
                continue
            empty = s["start"] - cover - 1
            if empty >= 2:
                has_gap = True
                notes.append(("red", f"{empty}-month gap ({_label(cover)} → {_label(s['start'])})"))
            cover = s["end"]
        if len(spans) >= 2 and not has_gap:
            notes.append(("green", "Continuous employment — no gaps ≥2mo"))
        for s in ordered:
            if (m := months(s)) <= 3:
                notes.append(("yellow", f"{s['role']} @ {s['employer']} — {m} month{'' if m == 1 else 's'} only"))
        longest = max((s for s in spans if months(s) >= 24), key=months, default=None)
        if longest:
            m = months(longest)
            notes.append(("green", f"{m // 12} yr {m % 12} mo at {longest['employer']}"))
        latest = max(spans, key=lambda s: s["start"])
        if latest["kind"] in ("internship", "contract"):
            notes.append(("grey", "Most recent role is " + ("an internship" if latest["kind"] == "internship" else "a contract")))
    current = [e for e in history if _role_kind(e.get("role") or "", e.get("employer") or "") != "org" and _is_current(e)]
    if not current:
        last = max((s["end"] for s in spans), default=None)
        notes.append(("red", "No current role" + (f" (last ended {_label(last)})" if last else "")))
    else:
        top = max(current, key=lambda e: _start_month(e.get("start")) or -1)
        start = _start_month(top.get("start"))
        notes.append(("green", f"Currently at {top.get('employer', '')}" + (f" (since {_label(start)})" if start else "")))
    if not has_full_time and spans:
        notes.append(("grey", "No role labelled full-time"))
    order = {"red": 0, "yellow": 1, "grey": 2, "green": 3}
    return sorted(notes, key=lambda n: order[n[0]])


# ---------- pool insights (Overview tab); `people` = screened candidates, best first ----------

def kpis(people):
    fits = [c["fit"] for c in people]
    every = sum(c["gaps"] == 0 for c in people)
    return {"avg": round(statistics.mean(fits)) if fits else None, "top": people[0] if people else None,
            "every": every, "every_pct": every / len(people) if people else 0}


def trust(people):
    """How much of the model's evidence held up: share of met/partial verdicts whose quote is in the CV,
    and how many 'met' were cut to partial because the quote was not found."""
    claimed = [r for c in people for r in c["requirements"] if r["verdict"] in ("met", "partial")]
    found = sum(r["found"] for r in claimed)
    cut = sum(r["verdict"] == "met" and r["counted"] == "partial" for c in people for r in c["requirements"])
    check = sum(c["to_check"] for c in people)
    return {"claimed": len(claimed), "found": found, "cut": cut, "check": check,
            "check_people": sum(bool(c["to_check"]) for c in people)}


def coverage(people, requirements):
    """Per requirement: how many candidates meet it, partly meet it, miss it. Rarest 'met' first."""
    rows = []
    for i, req in enumerate(requirements):
        counts = Counter(c["requirements"][i]["counted"] for c in people)
        rows.append({**req, "met": counts["met"], "partial": counts["partial"], "missing": counts["missing"]})
    return sorted(rows, key=lambda r: (r["met"], -r["missing"]))


def near_misses(people, max_gap=2):
    """The candidates closest to meeting every must-have: those missing the fewest must-have lines (at most
    max_gap; None for any number), with the lines they miss. A partial counts as not met, as in the
    'Gap · N must-haves' chip."""
    gaps = [c["gaps"] for c in people if c["gaps"] and (max_gap is None or c["gaps"] <= max_gap)]
    if not gaps:
        return None, []
    near = [(c, [r for r in c["requirements"] if r["must"] and r["counted"] != "met"]) for c in people if c["gaps"] == min(gaps)]
    return min(gaps), sorted(near, key=lambda x: -x[0]["fit"])


def bottleneck(people, requirements):
    """The must-have that most often stands between the closest candidates and a full match, and the
    must-haves nobody meets."""
    _, near = near_misses(people)
    blocked = Counter(r["id"] for _, unmet in near for r in unmet)
    by_id = {r["id"]: r for r in coverage(people, requirements)}
    top = None
    if blocked:
        rid, n = blocked.most_common(1)[0]
        top = {**by_id[rid], "blocked": n, "of": len(near)}
    nobody = [r for r in by_id.values() if r["must"] and r["met"] == 0]
    return top, nobody


def _nearest_rank(values, pct):
    v = sorted(values)
    return v[max(0, math.ceil(pct * len(v)) - 1)]


def hidden_gems(people, top=5):
    """'Don't lose these': a strong 12-skill profile (top quarter of the pool; median when fewer than
    4) but a below-median Requirement Match, backed by at least 8 verified skill quotes."""
    if len(people) < 2:
        return []
    profiles = [c["profile"] for c in people]
    floor = statistics.median(profiles) if len(people) < 4 else _nearest_rank(profiles, 0.75)
    mid_fit = statistics.median(c["fit"] for c in people)
    gems = [c for c in people if c["profile"] >= floor and c["fit"] < mid_fit
            and sum(d["grounded"] for d in c["dimensions"].values()) >= 8]
    return sorted(gems, key=lambda c: -(c["profile"] - c["fit"]))[:top]


def strength_profile(people):
    """Per skill: median score across the pool and share of candidates at 7 or above, weakest first."""
    rows = []
    for d in DIMS:
        vals = [c["dimensions"][d]["score"] for c in people]
        rows.append({"dim": d, "median": statistics.median(vals), "strong": sum(v >= 7 for v in vals) / len(vals)})
    return sorted(rows, key=lambda r: (r["median"], r["strong"]))


def skill_landscape(people, job_text, top=15):
    """Most common verified technologies in the pool, and whether the job text asks for them."""
    seen, label = Counter(), {}
    for c in people:
        mine = {}  # one count per candidate even if the CV lists "React" and "react"
        for t in c["facts"]["extracted_data"].get("key_technologies") or []:
            if words(t):
                mine.setdefault(words(t), str(t).strip())
        for key, t in mine.items():
            seen[key] += 1
            label.setdefault(key, Counter())[t] += 1
    job = words(job_text)
    return [{"skill": label[k].most_common(1)[0][0], "candidates": n, "asked": mentions(k, job)}
            for k, n in seen.most_common(top)]


def rank_of(c, pool, fit=None, nice=None):
    """1-based rank of c in the pool if its Match were `fit` and its nice-to-haves met `nice` (scoring.rank order)."""
    key = lambda x, f, n: (-f, -n, -x["profile"], x["name"])  # noqa: E731
    mine = key(c, c["fit"] if fit is None else fit, c["nice_met"] if nice is None else nice)
    return 1 + sum(key(x, x["fit"], x["nice_met"]) < mine for x in pool if x is not c)


def what_if(c, pool):
    """For each must-have the candidate does not fully meet: their Match and rank if they could show it.
    Sorted by the biggest jump; also the rank with every must-have met."""
    must = [r for r in c["requirements"] if r["must"]]
    rows = []
    for r in must:
        if r["counted"] == "met":
            continue
        fit = fit_score([{**x, "counted": "met"} if x is r else x for x in must])
        rows.append({"req": r, "fit": fit, "gain": fit - c["fit"], "rank": rank_of(c, pool, fit)})
    return sorted(rows, key=lambda x: (-x["gain"], x["rank"])), (rank_of(c, pool, 100) if rows else None)


def nice_if(c, pool):
    """Once every must-have is met, only nice-to-haves break ties: per unmet one, the rank if the candidate showed it."""
    return [{"req": r, "fit": c["fit"], "gain": 0, "rank": rank_of(c, pool, nice=c["nice_met"] + 1)}
            for r in c["requirements"] if not r["must"] and r["counted"] != "met"]


def standing(c, pool):
    """Rank of c by Match, by the 12-skill profile and by years of experience."""
    by = lambda f: 1 + sum(f(x) > f(c) for x in pool if x is not c)  # noqa: E731
    return {"match": rank_of(c, pool), "profile": by(lambda x: x["profile"]), "years": by(lambda x: x["years"] or 0)}


def grades(people):
    counts = Counter(c["grade"] for c in people)
    return [(g, counts[g]) for g in GRADE_ORDER]


def levels(people):
    counts = Counter(level(c["years"]) or "Unknown" for c in people)
    return [(k, counts[k]) for k in ("Entry", "Junior", "Mid", "Senior", "Unknown") if counts[k]]


def flags_to_check(people):
    """Red flags and career warnings, only for the people you would likely talk to first."""
    out = []
    for c in people[:max(5, math.ceil(len(people) / 4))]:
        rf = c["facts"]["red_flags"]
        items = [f for k in ("gaps", "inconsistencies", "missing_info") for f in rf.get(k) or []]
        items += [t for sev, t in career_notes(c["facts"]["extracted_data"].get("employment_history")) if sev in ("red", "yellow")]
        if items:
            out.append((c, items))
    return out


if __name__ == "__main__":
    assert band(29.9) == 0 and band(30) == 1 and band(65) == 3 and band(8, 10) == 4
    assert fit_grade(90) == "A" and fit_grade(89) == "A-" and fit_grade(45) == "C" and fit_grade(44) == "D"
    rows = [{"counted": "met"}, {"counted": "met"}, {"counted": "partial"}, {"counted": "missing"}]
    assert fit_score(rows) == 63  # 2.5 / 4 = 62.5 -> half-up 63
    assert fit_score([]) is None
    assert mentions("Node.js", words("Built APIs in node.js")) and not mentions("Java", words("JavaScript only"))
    assert _role_kind("Head of AI Innovation", "Visi Cerdas Global") == _role_kind("Staff Engineer", "Acme") == "unknown"
    assert _role_kind("Head of Media Division", "Himpunan Mahasiswa Informatika") == _role_kind("Treasurer") == "org"
    hist = [{"role": "Engineer (Full time)", "employer": "A", "start": "2020-01", "end": "2021-12"},
            {"role": "Freelance dev", "employer": "B", "start": "2021-07", "end": "2022-06"},
            {"role": "Intern", "employer": "C", "start": "2023-01", "end": "2023-02"}]
    assert career_years(hist, today=date(2026, 10, 1)) == 2.7  # 30 months 2020-01..2022-06 + 2 months
    assert career_years([{"role": "x", "start": "?", "end": "2020"}], fallback="4") == 4.0
    assert level(0.5) == "Entry" and level(2.9) == "Junior" and level(5) == "Mid" and level(9) == "Senior"
    assert experience_text(1.2) == "Junior · about 1 yr" and experience_text(None) == "Not stated"
    notes = dict((t, s) for s, t in career_notes(hist, date(2026, 10, 1)))
    assert notes["6-month gap (2022-06 → 2023-01)"] == "red" and "No current role (last ended 2023-02)" in notes

    def person(name, fit, profile, unmet=(), grounded=12):
        reqs = [{"id": f"R{i}", "must": True, "counted": "missing" if f"R{i}" in unmet else "met",
                 "verdict": "met", "found": True} for i in (1, 2, 3)]
        return {"name": name, "file": name, "fit": fit, "profile": profile, "gaps": len(unmet), "requirements": reqs,
                "dimensions": {d: {"score": profile / 10, "grounded": i < grounded} for i, d in enumerate(DIMS)}}
    pool = [person("a", 100, 70), person("b", 67, 60, ["R2"]), person("c", 67, 50, ["R2"]),
            person("d", 33, 80, ["R1", "R2"]), person("e", 33, 85, ["R1", "R3"], grounded=5)]
    reqs = [{"id": f"R{i}", "must": True, "text": f"req {i}"} for i in (1, 2, 3)]
    top, nobody = bottleneck(pool, reqs)
    assert top["id"] == "R2" and top["blocked"] == 2 and top["of"] == 2 and nobody == []
    gap, near = near_misses(pool)
    assert gap == 1 and [c["name"] for c, _ in near] == ["b", "c"] and near[0][1][0]["id"] == "R2"
    gap, near = near_misses([c for c in pool if c["gaps"] != 1])  # nobody 1 short -> the 2-short ones
    assert gap == 2 and [c["name"] for c, _ in near] == ["d", "e"]
    assert near_misses([pool[0]] + pool[3:], max_gap=1) == (None, []) and near_misses(pool[3:], None)[0] == 2
    assert [c["name"] for c in hidden_gems(pool)] == ["d"]  # e has too few verified quotes
    assert hidden_gems(pool[:3]) == []  # nobody below the median Match with a top profile
    assert coverage(pool, reqs)[0]["id"] == "R2"  # rarest first
    for c in pool:
        c["nice_met"] = 0
    rows, all_rank = what_if(pool[3], pool)  # d: R1 and R2 missing, Match 33
    assert [(x["req"]["id"], x["fit"], x["rank"]) for x in rows] == [("R1", 67, 2), ("R2", 67, 2)] and all_rank == 1
    assert what_if(pool[0], pool) == ([], None) and rank_of(pool[1], pool) == 2
    c = {**pool[2], "requirements": pool[2]["requirements"] + [{"id": "P1", "must": False, "counted": "missing"}]}
    assert rank_of(c, pool) == 3 and [x["rank"] for x in nice_if(c, pool)] == [2]  # a nice-to-have breaks the tie with b
    aged = [{**x, "years": y} for x, y in zip(pool, (1, 2, 3, 4, None))]
    assert standing(aged[3], aged) == {"match": 5, "profile": 2, "years": 1}  # e has the top profile; d the most years
    for c, techs in zip(pool, (["React", "react", "Go"], ["React"], [], [], [])):
        c["facts"] = {"extracted_data": {"key_technologies": techs}}
    land = skill_landscape(pool, "We need React developers")
    assert land[0] == {"skill": "React", "candidates": 2, "asked": True} and land[1]["asked"] is False
    print("self-check OK")
