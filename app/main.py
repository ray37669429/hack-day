"""FastAPI 入口。啟動：uvicorn app.main:app --reload --port 8001

API 說明見 docs/backend-design.md 第 5 節。協助者角色已取消：農民用專屬連結自己確認全部內容。
/api/cases 只給本機管理與測試用（建立案例、看完整資料），對外開放前必須加登入或拿掉。
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import load_env

load_env()

from . import actions, pipeline, store  # noqa: E402
from .agents import document, faq, intake, legal, report, triage  # noqa: E402
from .models import Case, Channel, Photo, Stage  # noqa: E402

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
        raise HTTPException(404, "這個連結不能用")


def _act(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except actions.ActionError as e:
        raise HTTPException(400, str(e))


def _doc_path(case: Case, name: str) -> Path:
    """本案的同意書檔案；名稱必須在 case.documents 裡，且不能跳出資料夾。"""
    if name not in case.documents or Path(name).name != name:
        raise HTTPException(404, "找不到這份文件")
    doc_dir = (store.case_dir(case.id) / "documents").resolve()
    path = (doc_dir / name).resolve()
    if path.parent != doc_dir or not path.is_file():
        raise HTTPException(404, "找不到這份文件")
    return path


def legal_view(case: Case) -> list[dict]:
    """法律注意事項（依分數高到低），附選題理由與備註。農民回答了就算處理過。"""
    out = []
    sel = legal.selection(case)
    for i in legal.issues(case):
        qid = i.question.id if i.question else None
        a = case.answers.get(qid) if qid else None
        s = sel[i.id]
        fu = s["followup"]
        fa = case.answers.get(fu.id) if fu else None
        out.append({"id": i.id, "title": i.title, "detail": i.detail, "reference": i.reference,
                    "score": i.score, "score_reason": i.score_reason,
                    "asked": s["asked"], "selection": s["reason"],
                    "question_id": qid, "answer_label": i.question.label(a.value) if a else None,
                    "followup": {"question_id": fu.id, "text": fu.text,
                                 "answer_label": fu.label(fa.value) if fa else None} if fu else None,
                    "handled": not s["asked"] or a is not None})
    return out


def admin_view(case: Case) -> dict:
    """本機管理與除錯用：整個案例 + 不能出正式版的原因 + 法律注意事項 + 農民待辦。"""
    return {**case.model_dump(mode="json"), "missing": actions.missing(case), "legal": legal_view(case),
            "todo": actions.todo(case)}


# ───── 農民端資料（照片是農民自己拍的：可顯示姓名、遮蔽後的證號、持分；不放地址）

def farmer_questions(case: Case) -> list[dict]:
    return triage.questions(case)


def farmer_answers(case: Case) -> dict[str, str]:
    current = {q["id"] for q in farmer_questions(case)}  # 追問被取消後，舊答案不再顯示
    return {q: actions.answer_label(case, q, a.value) for q, a in case.answers.items() if q in current}


def farmer_documents(case: Case) -> list[dict]:
    return [{"name": n, "url": f"/api/f/{case.farmer_token}/documents/{quote(n)}", "draft": "草稿" in n}
            for n in case.documents]


def farmer_report(case: Case) -> dict | None:
    """土地分析報告的摘要與下載網址；還沒產生時是 None。"""
    s = report.summary(case)
    return {**s, "url": f"/api/f/{case.farmer_token}/report"} if s else None


def latest_photos(case: Case) -> dict[int, Photo]:
    """每一頁最後一張合格的照片。"""
    latest: dict[int, Photo] = {}
    for p in case.photos:
        if p.ok and not p.retired:
            latest[p.page] = p
    return latest


# ───── 本機管理（建立案例、除錯）

class NewCase(BaseModel):
    sample_id: str | None = None
    pages_expected: int = 2


@app.post("/api/cases")
def create_case(body: NewCase):
    if body.sample_id and body.sample_id not in {"C01", "C02", "C03"}:
        raise HTTPException(400, "假謄本只有 C01、C02、C03")
    case = _act(actions.create_case, "system", body.sample_id, body.pages_expected)
    return {"id": case.id, "farmer_token": case.farmer_token, "farmer_url": f"/api/f/{case.farmer_token}"}


@app.get("/api/cases/{case_id}")
def get_case(case_id: str):
    return admin_view(_case(case_id))


@app.get("/api/cases/{case_id}/documents/{name}")
def get_document(case_id: str, name: str):
    case = _case(case_id)
    return FileResponse(_doc_path(case, name), filename=name)


# ───── 農民（用專屬連結）

@app.get("/api/f/{token}")
def farmer_view(token: str):
    case = _farmer(token)
    lands = []
    if case.stage in (Stage.reviewing, Stage.documented):
        val = {c.id: c.value for c in case.claims}
        for p in case.parcels:
            lands.append({"pid": p.pid, "location": val.get(f"{p.pid}-location", ""),
                          "lot_no": val.get(f"{p.pid}-lot_no", ""), "area_raw": val.get(f"{p.pid}-area_m2", ""),
                          "area_unit": "平方公尺", "page": p.source.page})
    latest = latest_photos(case)
    return {
        "stage": case.stage.value,
        "pages_expected": case.pages_expected,
        "pages_done": sorted(latest),
        "lands": lands,
        "photos": [{"page": n, "url": f"/api/f/{token}/photos/{n}"} for n in sorted(latest)],
        "questions": farmer_questions(case),
        "answers": farmer_answers(case),
        "documents": farmer_documents(case),
        "todo": actions.todo(case),
        "retake": actions.retake_pages(case),
        "report": farmer_report(case),
    }


@app.get("/api/f/{token}/photos/{page}")
def farmer_photo(token: str, page: int):
    case = _farmer(token)
    photo = latest_photos(case).get(page)
    if photo is None or Path(photo.file).name != photo.file:
        raise HTTPException(404, "找不到這一頁的照片")
    photo_dir = (store.case_dir(case.id) / "photos").resolve()
    path = (photo_dir / photo.file).resolve()
    if path.parent != photo_dir or not path.is_file():
        raise HTTPException(404, "找不到這一頁的照片")
    return FileResponse(path)


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
    if "打不開" in reason and b == 0 and s == 0:
        checks = []
    else:
        checks = [{"id": "bright", "ok": b >= intake.MIN_BRIGHTNESS, "text": "夠亮" if b >= intake.MIN_BRIGHTNESS else "有點暗"},
                  {"id": "sharp", "ok": s >= intake.MIN_SHARPNESS, "text": "清楚" if s >= intake.MIN_SHARPNESS else "有點糊"}]
    return {"ok": ok, "reason": reason, "brightness": round(b), "sharpness": round(s), "all_pages_done": complete,
            "checks": checks}


class Answer(BaseModel):
    question: str
    value: str
    channel: Channel = Channel.button
    transcript: str = ""


@app.post("/api/f/{token}/answers")
def post_answer(token: str, body: Answer):
    case = _farmer(token)
    _act(actions.answer, case, "farmer", body.question, body.value, body.channel, body.transcript)
    # 題目都答完就自動產生同意書；之後改答案也重新產生，避免留下過期的檔案
    if case.claims and (not triage.unanswered(case) or case.documents):
        document.run(case)
        report.run(case)  # 文件 agent 會清空資料夾，報告排在後面
        if case.stage == Stage.reviewing:
            actions.set_stage(case, "agent:document", Stage.documented)
    store.save(case)
    return {"ok": True, "answers": farmer_answers(case), "questions": farmer_questions(case),
            "documents": farmer_documents(case), "todo": actions.todo(case), "report": farmer_report(case)}


@app.get("/api/f/{token}/documents/{name}")
def farmer_document(token: str, name: str):
    case = _farmer(token)
    return FileResponse(_doc_path(case, name), filename=name)


@app.get("/api/f/{token}/report")
def farmer_report_file(token: str):
    case = _farmer(token)
    path = store.case_dir(case.id) / "documents" / report.FILE
    if not path.is_file():
        raise HTTPException(404, "報告還沒做好")
    return FileResponse(path, filename=report.FILE)


class Retake(BaseModel):
    page: int


@app.post("/api/f/{token}/retake")
def retake(token: str, body: Retake):
    """回到拍照：重拍某一頁。清掉擷取結果、核對答案和舊的同意書與報告，拍好後自動重新讀謄本。"""
    case = _farmer(token)
    _act(actions.retake, case, "farmer", body.page)
    for old in (store.case_dir(case.id) / "documents").glob("*.docx"):
        old.unlink()
    store.save(case)
    return farmer_view(token)


class Ask(BaseModel):
    text: str = ""
    channel: Channel = Channel.button


@app.post("/api/f/{token}/ask")
def ask(token: str, body: Ask):
    """服務台：阿伯從固定答案庫回答（app/agents/faq.py）。不保存錄音，只記問題文字與挑中的答案。"""
    case = _farmer(token)
    text = body.text.strip()[:200]
    nxt = triage.unanswered(case) if case.stage in (Stage.reviewing, Stage.documented) else []
    r = faq.reply(case, text, nxt[0]["text"] if nxt else None)
    actions.log(case, "agent:faq", "回答農民的問題", f"{'語音' if body.channel == Channel.voice else '按鈕'}：「{text[:60]}」→ {r['id']}")
    store.save(case)
    return r


# ───── 靜態檔：前端與假謄本（data/output 不對外）

app.mount("/web", StaticFiles(directory=ROOT / "web", html=True), name="web")
app.mount("/data/samples", StaticFiles(directory=ROOT / "data" / "samples"), name="samples")


@app.get("/")
def index():
    return RedirectResponse("/web/prototype.html")
