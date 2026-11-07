"""FastAPI 入口。啟動：uvicorn app.main:app --reload --port 8000

API 說明見 docs/backend-design.md 第 5 節。協助者端 MVP 只在本機使用，對外開放前必須加登入。
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import load_env

load_env()

from . import actions, pipeline, store  # noqa: E402
from .agents import document, intake, triage
from .models import ANSWER_LABEL, QUESTIONS, Case, Channel, Manual, Stage

ROOT = Path(__file__).resolve().parent.parent
app = FastAPI(title="農地同意書 MVP")
MAX_UPLOAD = 15 * 1024 * 1024


def _case(case_id: str) -> Case:
    try:
        return store.load(case_id)
    except (KeyError, ValueError):
        raise HTTPException(404, "找不到這個案例")


def _farmer(token: str) -> Case:
    try:
        return store.find_by_token(token)
    except KeyError:
        raise HTTPException(404, "連結無效，請向協助者索取新的連結")


def _act(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except actions.ActionError as e:
        raise HTTPException(400, str(e))


def helper_view(case: Case) -> dict:
    return {**case.model_dump(mode="json"), "missing": actions.missing(case)}


# ───── 協助者

class NewCase(BaseModel):
    sample_id: str | None = None
    pages_expected: int = 2


@app.post("/api/cases")
def create_case(body: NewCase):
    if body.sample_id and body.sample_id not in {"C01", "C02", "C03"}:
        raise HTTPException(400, "假謄本只有 C01、C02、C03")
    case = _act(actions.create_case, "helper", body.sample_id, body.pages_expected)
    return {"id": case.id, "farmer_token": case.farmer_token, "farmer_url": f"/api/f/{case.farmer_token}"}


@app.get("/api/cases/{case_id}")
def get_case(case_id: str):
    return helper_view(_case(case_id))


class Confirm(BaseModel):
    value: str | None = None


@app.post("/api/cases/{case_id}/claims/{claim_id}/confirm")
def confirm(case_id: str, claim_id: str, body: Confirm):
    case = _case(case_id)
    _act(actions.confirm_claim, case, "helper", claim_id, body.value)
    store.save(case)
    return helper_view(case)


class Reject(BaseModel):
    reason: str = ""


@app.post("/api/cases/{case_id}/claims/{claim_id}/reject")
def reject(case_id: str, claim_id: str, body: Reject):
    case = _case(case_id)
    _act(actions.reject_claim, case, "helper", claim_id, body.reason)
    store.save(case)
    return helper_view(case)


@app.put("/api/cases/{case_id}/manual")
def put_manual(case_id: str, body: Manual):
    case = _case(case_id)
    _act(actions.set_manual, case, "helper", body)
    store.save(case)
    return helper_view(case)


@app.post("/api/cases/{case_id}/documents")
def make_documents(case_id: str):
    case = _case(case_id)
    if not case.claims:
        raise HTTPException(400, "還沒有擷取結果，不能產生同意書")
    files = document.run(case)
    if case.stage == Stage.reviewing:
        actions.set_stage(case, "agent:document", Stage.documented)
    store.save(case)
    return {"files": files, "draft": bool(actions.missing(case)), "missing": actions.missing(case)}


@app.get("/api/cases/{case_id}/documents/{name}")
def get_document(case_id: str, name: str):
    case = _case(case_id)
    if name not in case.documents:
        raise HTTPException(404, "找不到這份文件")
    return FileResponse(store.case_dir(case.id) / "documents" / name, filename=name)


# ───── 農民（用專屬連結，不回傳身分證號與他人資料）

@app.get("/api/f/{token}")
def farmer_view(token: str):
    case = _farmer(token)
    lands = []
    for p in case.parcels:
        loc = next((c.value for c in case.claims if c.id == f"{p.pid}-location"), "")
        lot = next((c.value for c in case.claims if c.id == f"{p.pid}-lot_no"), "")
        lands.append({"pid": p.pid, "location": loc, "lot_no": lot})
    good = sorted({p.page for p in case.photos if p.ok})
    return {
        "stage": case.stage.value,
        "pages_expected": case.pages_expected,
        "pages_done": good,
        "lands": lands if case.stage in (Stage.reviewing, Stage.documented) else [],
        "questions": [{"id": q, "text": t, "options": sorted(v)} for q, (t, v) in QUESTIONS.items()],
        "answers": {q: ANSWER_LABEL[a.value] for q, a in case.answers.items()},
    }


@app.post("/api/f/{token}/photos")
async def upload_photo(token: str, bg: BackgroundTasks, page: int = Form(...), file: UploadFile = File(...)):
    case = _farmer(token)
    data = await file.read()
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "照片太大")
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".webp", ".heic"}:
        suffix = ".jpg"
    name = f"page{page}_{datetime.now():%H%M%S%f}{suffix}"
    photo_dir = store.case_dir(case.id) / "photos"
    photo_dir.mkdir(exist_ok=True)
    (photo_dir / name).write_bytes(data)
    ok, reason, b, s = intake.check(photo_dir / name)
    _act(actions.record_photo, case, "farmer", page, name, ok, reason, b, s)
    store.save(case)
    complete = actions.pages_ok(case)
    if complete:
        bg.add_task(pipeline.after_photos, case.id)
    return {"ok": ok, "reason": reason, "brightness": round(b), "sharpness": round(s), "all_pages_done": complete}


class Answer(BaseModel):
    question: str
    value: str
    channel: Channel = Channel.button
    transcript: str = ""


@app.post("/api/f/{token}/answers")
def post_answer(token: str, body: Answer):
    case = _farmer(token)
    _act(actions.answer, case, "farmer", body.question, body.value, body.channel, body.transcript)
    triage.after_answer(case, body.question, body.value)
    store.save(case)
    return {"ok": True, "answers": {q: ANSWER_LABEL[a.value] for q, a in case.answers.items()}}


# ───── 靜態檔：前端與假謄本（data/output 不對外）

app.mount("/web", StaticFiles(directory=ROOT / "web", html=True), name="web")
app.mount("/data/samples", StaticFiles(directory=ROOT / "data" / "samples"), name="samples")


@app.get("/")
def index():
    return RedirectResponse("/web/prototype.html")
