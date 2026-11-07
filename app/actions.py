"""動作層：唯一能修改案例資料的地方。

每個動作都檢查「誰在做」，並寫一筆操作紀錄。agent 不能確認任何欄位。
actor 格式：farmer、helper、system、agent:extract、agent:check、agent:triage、agent:document
"""
from __future__ import annotations

from . import store
from .models import (ANSWER_LABEL, PENDING, QUESTIONS, Case, Channel, ClaimField, ClaimStatus, Event, Extraction,
                     FarmerAnswer, FieldClaim, LegalNote, Manual, Ownership, Parcel, Photo, Source, Stage, Task)


class ActionError(Exception):
    """動作不被允許或資料不正確。訊息會直接顯示給使用者。"""


def _require(actor: str, *allowed: str) -> None:
    if actor not in allowed:
        raise ActionError(f"「{actor}」不能做這個動作（只允許：{'、'.join(allowed)}）")


def _log(case: Case, actor: str, action: str, detail: str = "") -> None:
    case.events.append(Event(actor=actor, action=action, detail=detail))


def _claim(case: Case, claim_id: str) -> FieldClaim:
    for c in case.claims:
        if c.id == claim_id:
            return c
    raise ActionError(f"找不到欄位 {claim_id}")


# ───── 案例與照片

def create_case(actor: str, sample_id: str | None = None, pages_expected: int = 2) -> Case:
    _require(actor, "helper", "system")
    case_id, token = store.new_ids()
    case = Case(id=case_id, farmer_token=token, sample_id=sample_id, pages_expected=pages_expected)
    _log(case, actor, "建立案例", f"假謄本 {sample_id}" if sample_id else "")
    store.save(case)
    return case


def record_photo(case: Case, actor: str, page: int, file: str, ok: bool, reason: str,
                 brightness: float, sharpness: float) -> Photo:
    _require(actor, "farmer", "helper")
    if case.stage != Stage.collecting:
        raise ActionError("這個案例已經不在收照片的階段")
    if not 1 <= page <= case.pages_expected:
        raise ActionError(f"頁數要在 1 到 {case.pages_expected} 之間")
    photo = Photo(page=page, file=file, ok=ok, reason=reason, brightness=brightness, sharpness=sharpness)
    case.photos.append(photo)
    _log(case, actor, "上傳照片", f"第 {page} 頁：{'通過' if ok else '退回，' + reason}（亮度 {brightness:.0f}、清晰度 {sharpness:.0f}）")
    return photo


def pages_ok(case: Case) -> bool:
    good = {p.page for p in case.photos if p.ok}
    return all(n in good for n in range(1, case.pages_expected + 1))


def set_stage(case: Case, actor: str, stage: Stage, detail: str = "") -> None:
    _require(actor, "system", "agent:extract", "agent:check", "agent:triage", "agent:document")
    case.stage = stage
    _log(case, actor, "改變階段", f"{stage.value} {detail}".strip())


# ───── agent 專用

def add_extraction(case: Case, actor: str, ex: Extraction) -> None:
    """擷取 agent 寫入結果：全部建立成「待確認」。"""
    _require(actor, "agent:extract")
    if case.claims:
        raise ActionError("這個案例已經擷取過")
    pend = {(p.parcel_id, p.field): p.note for p in ex.pending}

    def add(claim_id: str, target: str, field: ClaimField, raw: str, source: Source, note: str = "") -> None:
        raw = (raw or "").strip()
        if raw == PENDING:
            raw, note = "", note or "看不清"
        case.claims.append(FieldClaim(id=claim_id, target=target, field=field, ai_value=raw, value=raw,
                                      note=note, source=source))

    for p in ex.parcels:
        case.parcels.append(Parcel(pid=p.parcel_id, source=p.source))
        add(f"{p.parcel_id}-location", p.parcel_id, ClaimField.location,
            f"{p.county}{p.township}{p.section}{p.subsection}", p.source)
        add(f"{p.parcel_id}-lot_no", p.parcel_id, ClaimField.lot_no, p.lot_no, p.source)
        add(f"{p.parcel_id}-area_m2", p.parcel_id, ClaimField.area_m2, p.area_raw.replace(",", ""), p.source)
    counter: dict[str, int] = {}
    for o in ex.ownerships:
        counter[o.parcel_id] = counter.get(o.parcel_id, 0) + 1
        oid = f"{o.parcel_id}-O{counter[o.parcel_id]}"
        case.ownerships.append(Ownership(oid=oid, pid=o.parcel_id, source=o.source))
        add(f"{oid}-owner", oid, ClaimField.owner, o.owner, o.source)
        add(f"{oid}-id_no", oid, ClaimField.id_no, o.id_masked, o.source)
        add(f"{oid}-share", oid, ClaimField.share, o.share_raw, o.source, pend.get((o.parcel_id, "權利範圍"), ""))
    _log(case, actor, "擷取完成", f"{len(ex.parcels)} 筆土地、{len(ex.ownerships)} 筆所有權、{len(case.claims)} 個欄位，全部待確認")


def add_flag(case: Case, actor: str, claim_id: str, text: str) -> None:
    _require(actor, "agent:check")
    c = _claim(case, claim_id)
    if text not in c.flags:
        c.flags.append(text)
        _log(case, actor, "加註警示", f"{claim_id}：{text}")


def add_task(case: Case, actor: str, text: str) -> Task:
    _require(actor, "helper", "system", "agent:triage", "agent:check", "agent:document")
    t = Task(id=len(case.tasks) + 1, text=text)
    case.tasks.append(t)
    _log(case, actor, "新增任務", text)
    return t


# ───── 農民

def answer(case: Case, actor: str, question: str, value: str, channel: Channel, transcript: str = "") -> FarmerAnswer:
    """農民回答 q1–q3，或目前有效的法律注意事項題目（L-...）。"""
    from .agents import legal  # 延遲匯入，避免循環
    _require(actor, "farmer")
    if question in QUESTIONS:
        allowed, label = QUESTIONS[question][1], ANSWER_LABEL.get(value, value)
    elif question in {q.id for q in legal.active_questions(case)}:
        lq = legal.QUESTIONS[question]
        allowed, label = lq.values(), lq.label(value)
    else:
        raise ActionError(f"沒有這一題：{question}")
    if value not in allowed:
        raise ActionError(f"第 {question} 題不能回答「{value}」")
    if channel == Channel.voice and not transcript.strip():
        raise ActionError("語音回答要附上辨識到的原文")
    a = FarmerAnswer(question=question, value=value, channel=channel, transcript=transcript.strip())
    case.answers[question] = a
    _log(case, actor, "回答問題", f"{question}={label}（{'語音：' + a.transcript if channel == Channel.voice else '按鈕'}）")
    return a


def answer_label(question: str, value: str) -> str:
    """回答的顯示文字：法律題用該題選項文字，其他用 ANSWER_LABEL。"""
    from .agents import legal
    if question in legal.QUESTIONS:
        return legal.QUESTIONS[question].label(value)
    return ANSWER_LABEL.get(value, value)


# ───── 協助者

def confirm_claim(case: Case, actor: str, claim_id: str, value: str | None = None) -> FieldClaim:
    """只有人能確認。agent 呼叫一律拒絕。"""
    _require(actor, "helper")
    c = _claim(case, claim_id)
    new = (c.value if value is None else value).strip()
    if not new:
        raise ActionError(f"{claim_id} 沒有值，不能確認；看不清的欄位請先填入正確值")
    changed = new != c.ai_value
    c.value, c.status, c.confirmed_by = new, ClaimStatus.confirmed, actor
    _log(case, actor, "確認欄位", f"{claim_id}{'（已修正 AI 的值）' if changed else ''}")
    return c


def reject_claim(case: Case, actor: str, claim_id: str, reason: str = "") -> FieldClaim:
    _require(actor, "helper")
    c = _claim(case, claim_id)
    c.status = ClaimStatus.rejected
    _log(case, actor, "退回欄位", f"{claim_id}：{reason}")
    add_task(case, "helper", f"請農民補拍：{claim_id}{'（' + reason + '）' if reason else ''}")
    return c


def set_manual(case: Case, actor: str, manual: Manual) -> None:
    _require(actor, "helper")
    pids = {p.pid for p in case.parcels}
    oids = {o.oid for o in case.ownerships}
    if set(manual.area_ha) - pids or set(manual.right_area_ha) - oids:
        raise ActionError("人工欄位對到不存在的土地或所有權")
    case.manual = manual
    _log(case, actor, "填寫人工欄位", "公頃面積、權利面積、實施期間、耕作人")


def resolve_legal(case: Case, actor: str, issue_id: str, note: str = "") -> LegalNote:
    """協助者標記某個法律注意事項已處理（記錄怎麼處理）。系統與 agent 不能代為處理。"""
    from .agents import legal
    _require(actor, "helper")
    issue = next((i for i in legal.issues(case) if i.id == issue_id), None)
    if issue is None:
        raise ActionError(f"目前沒有這個法律注意事項：{issue_id}")
    n = LegalNote(by=actor, note=note.strip())
    case.legal_notes[issue_id] = n
    _log(case, actor, "處理法律注意事項", f"{issue.title}{'：' + n.note if n.note else ''}")
    return n


def record_documents(case: Case, actor: str, files: list[str], draft: bool) -> None:
    _require(actor, "helper", "agent:document")
    case.documents = files
    _log(case, actor, "產生同意書", f"{len(files)} 份，{'草稿' if draft else '正式版'}")


# ───── 查詢（不改資料）

def confirmed(case: Case, claim_id: str) -> str | None:
    for c in case.claims:
        if c.id == claim_id:
            return c.value if c.status == ClaimStatus.confirmed else None
    return None


def missing(case: Case) -> list[str]:
    """還不能出正式版的原因。空清單 = 可以出正式版（⑤ 文件 agent 的送出條件）。"""
    out: list[str] = []
    if not case.claims:
        return ["還沒有擷取結果"]
    for c in case.claims:
        if c.status == ClaimStatus.rejected:
            out.append(f"已退回：{c.id}")
        elif c.status != ClaimStatus.confirmed:
            out.append(f"未確認：{c.id}")
    a = case.answers
    if "q1" not in a:
        out.append("農民還沒回答：這是你的地嗎")
    elif a["q1"].value != "yes":
        out.append(f"農民第 1 題回答「{ANSWER_LABEL[a['q1'].value]}」，需協助者處理")
    for q in ("q2", "q3"):
        if q not in a:
            out.append(f"農民還沒回答：{QUESTIONS[q][0]}")
        elif a[q].value == "unsure":
            out.append(f"農民對「{QUESTIONS[q][0]}」不確定")
    from .agents import legal
    for x in legal.plan(case):  # 只算被選中要問農民的題目（含追問）
        if x.question.id not in a:
            out.append(f"農民還沒回答：{x.question.text}")
    for issue in legal.issues(case):
        if issue.id not in case.legal_notes:
            out.append(f"法律注意事項未處理：{issue.title}")
    m = case.manual
    out += [f"未填：{p.pid} 本筆面積（公頃）" for p in case.parcels if not m.area_ha.get(p.pid)]
    out += [f"未填：{o.oid} 權利面積（公頃）" for o in case.ownerships if not m.right_area_ha.get(o.oid)]
    if not m.period:
        out.append("未填：實施期間")
    if not m.cultivator:
        out.append("未填：耕作人及 ID")
    return out
