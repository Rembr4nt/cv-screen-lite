"""Campaign folders on disk and the background screening job. No Streamlit here.

workspace/<YYYY-MM-DD HH.MM.SS> <title>/campaign.json     the job: title, responsibilities, required, nice, model
                                       cvs/<original files>
                                       results/<file>.json   one per CV, saved the moment it is screened
Screening runs in a thread, so leaving the page does not stop it; an interrupted run resumes from the
CVs that have no finished result. Run `python workspace.py` for the self-check (no network).
"""
import json
import os
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import scoring as sc

ROOT = Path(os.getenv("CVSCREEN_WORKSPACE") or Path(__file__).parent / "workspace")
# Claude runs CVs in parallel. Ollama cloud answers one call at a time per account (measured 2026-10-23: 4 calls took
# 29 s with 1, 2 or 4 workers), so parallel calls there only delay every result; one worker shows results sooner.
WORKERS = int(os.getenv("CV_WORKERS", "4"))
JOBS = {}  # campaign id -> {"total", "done", "running", "thread"}; lost on restart, which shows as "Resume"


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1))
    os.replace(tmp, path)  # atomic: a reader never sees half a file


def create(title, responsibilities, required, nice, model, cvs):
    now = datetime.now()
    cid = f"{now:%Y-%m-%d %H.%M.%S} {sc.clean(title)[:60]}"
    _write(ROOT / cid / "campaign.json", {"id": cid, "title": title.strip(), "created": now.isoformat(timespec="seconds"),
                                          "model": model, "responsibilities": responsibilities,
                                          "required": required, "nice": nice})
    add_cvs(cid, cvs)
    return cid


def add_cvs(cid, cvs):
    """Save uploaded CVs (from scoring.read_uploads). A name already in the campaign gets ' (2)'."""
    folder = ROOT / cid / "cvs"
    folder.mkdir(parents=True, exist_ok=True)
    added = []
    for cv in cvs:
        p, name, n = Path(cv["file"]), cv["file"], 2
        while (folder / name).exists():
            name, n = f"{p.stem} ({n}){p.suffix}", n + 1
        (folder / name).write_bytes(cv["data"])
        added.append(name)
    return added


def campaigns():
    """Every campaign, newest first."""
    return [json.loads(p.read_text()) for p in sorted(ROOT.glob("*/campaign.json"), reverse=True)]


def load(cid):
    return json.loads((ROOT / cid / "campaign.json").read_text())


def cv_files(cid):
    folder = ROOT / cid / "cvs"
    return sorted(p.name for p in folder.iterdir() if p.is_file()) if folder.exists() else []


def results(cid):
    found = (json.loads(p.read_text()) for p in (ROOT / cid / "results").glob("*.json"))
    return {r["file"]: r for r in found}


def people(cid):
    """Every screened or failed CV with its derived numbers, best Requirement Match first."""
    return sc.rank([{**r, **sc.derive(r)} for r in results(cid).values()])


def pending(cid):
    """CVs with no finished result (never screened, failed, or cut off by a restart)."""
    done = {f for f, r in results(cid).items() if not r.get("error")}
    return [f for f in cv_files(cid) if f not in done]


def status(cid):
    res = results(cid)
    job = JOBS.get(cid) or {}
    return {"total": len(cv_files(cid)), "screened": sum(not r.get("error") for r in res.values()),
            "failed": sum(bool(r.get("error")) for r in res.values()), "running": bool(job.get("running")),
            "job_done": job.get("done", 0), "job_total": job.get("total", 0)}


def delete(cid):
    shutil.rmtree(ROOT / cid)


def start(cid, model, screen=sc.screen_cv):
    """Screen every pending CV in a background thread. Does nothing while a run for this campaign is going."""
    if (JOBS.get(cid) or {}).get("running"):
        return
    todo = pending(cid)
    if not todo:
        return
    job = JOBS[cid] = {"total": len(todo), "done": 0, "running": True}
    job["thread"] = threading.Thread(target=_run, args=(cid, todo, model, job, screen), daemon=True)
    job["thread"].start()


def _run(cid, todo, model, job, screen):
    try:
        campaign, old = load(cid), results(cid)

        def one(file):
            prev = old.get(file) or {}
            text = prev.get("text") or sc.file_text(file, (ROOT / cid / "cvs" / file).read_bytes()).strip()
            if not text:
                return {"file": file, "text": "", "model": model, "error": "no text found in this file"}
            return screen(file, text, campaign, model, prev)

        with ThreadPoolExecutor(WORKERS if model.startswith("claude-") else 1) as pool:
            futures = {pool.submit(one, f): f for f in todo}
            for fut in as_completed(futures):
                try:
                    r = fut.result()
                except Exception as e:  # a crash on one CV is saved as a failure, never lost
                    r = {"file": futures[fut], "text": "", "model": model, "error": f"{type(e).__name__}: {e}"}
                _write(ROOT / cid / "results" / f"{r['file']}.json", r)
                job["done"] += 1
    finally:
        job["running"] = False


if __name__ == "__main__":
    import tempfile

    ROOT = Path(tempfile.mkdtemp())
    calls = []

    def fake(file, text, campaign, model, prev):
        calls.append(file)
        if file.startswith("bad"):
            return {"file": file, "text": text, "model": model, "error": "scoring: broken reply", "scoring": None, "facts": None}
        return {"file": file, "text": text, "model": model, "error": None, "scoring": None, "facts": None}

    cvs = [{"file": n, "data": f"CV of {n}".encode()} for n in ("a.txt", "b.txt", "bad.txt")]
    cid = create("Data / Analyst", ["Report"], ["SQL"], [], "m", cvs)
    assert "/" not in cid and load(cid)["required"] == ["SQL"]
    assert add_cvs(cid, [{"file": "a.txt", "data": b"again"}]) == ["a (2).txt"]
    start(cid, "m", fake)
    JOBS[cid]["thread"].join()
    st = status(cid)
    assert st == {"total": 4, "screened": 3, "failed": 1, "running": False, "job_done": 4, "job_total": 4}, st
    assert pending(cid) == ["bad.txt"] and sorted(results(cid)) == ["a (2).txt", "a.txt", "b.txt", "bad.txt"]
    calls.clear()
    start(cid, "m", fake)  # resume / retry: only the failed CV runs again
    JOBS[cid]["thread"].join()
    assert calls == ["bad.txt"]
    assert [c["id"] for c in campaigns()] == [cid]
    delete(cid)
    assert campaigns() == []
    print("self-check OK")
