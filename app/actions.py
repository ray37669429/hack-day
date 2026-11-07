"""動作層：唯一能修改案例資料的地方。

每個動作都檢查「誰在做」，並寫一筆操作紀錄。agent 不能確認任何欄位：
只有農民本人回答核對題（「一樣」／「不一樣」）時，才會確認或退回欄位。
協助者角色已取消。actor 格式：farmer、system、agent:extract、agent:check、agent:triage、agent:document
"""
from __future__ import annotations

from . import store
from .models import (ANSWER_LABEL, PENDING, PERIOD_YEARS, QUESTIONS, Case, Channel, ClaimField, ClaimStatus, Event,
                     Extraction, FarmerAnswer, FieldClaim, Ownership, Parcel, Photo, Source, Stage, Task, period_text,
                     roc_year)


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
    _require(actor, "system")
    case_id, token = store.new_ids()
    case = Case(id=case_id, farmer_token=token, sample_id=sample_id, pages_expected=pages_expected)
    _log(case, actor, "建立案例", f"假謄本 {sample_id}" if sample_id else "")
    store.save(case)
    return case


def record_photo(case: Case, actor: str, page: int, file: str, ok: bool, reason: str,
                 brightness: float, sharpness: float) -> Photo:
    _require(actor, "farmer")
    if case.stage != Stage.collecting:
        raise ActionError("這個案例已經不在收照片的階段")
    if not 1 <= page <= case.pages_expected:
        raise ActionError(f"頁數要在 1 到 {case.pages_expected} 之間")
    photo = Photo(page=page, file=file, ok=ok, reason=reason, brightness=brightness, sharpness=sharpness)
    case.photos.append(photo)
    _log(case, actor, "上傳照片", f"第 {page} 頁：{'通過' if ok else '退回，' + reason}（亮度 {brightness:.0f}、清晰度 {sharpness:.0f}）")
    return photo


def pages_ok(case: Case) -> bool:
    good = {p.page for p in case.photos if p.ok and not p.retired}
    return all(n in good for n in range(1, case.pages_expected + 1))


def retake(case: Case, actor: str, page: int) -> None:
    """農民要重拍某一頁：舊照片標成不再使用，清掉擷取結果與核對答案，回到收照片階段。
    新照片收齊後，原本的流程（pipeline.after_photos）會自動重新擷取。其他題目的答案保留。"""
    _require(actor, "farmer")
    if case.stage == Stage.extracting:
        raise ActionError("正在讀謄本，請等一下再重拍")
    if not 1 <= page <= case.pages_expected:
        raise ActionError(f"頁數要在 1 到 {case.pages_expected} 之間")
    for p in case.photos:
        if p.page == page and p.ok:
            p.retired = True
    dropped = [q for q in case.answers if q.startswith("C-")]
    for q in dropped:
        del case.answers[q]
    case.parcels, case.ownerships, case.claims, case.documents = [], [], [], []
    case.stage = Stage.collecting
    _log(case, actor, "重拍", f"第 {page} 頁；清掉擷取結果與 {len(dropped)} 個核對答案")


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
    """系統待辦（目前只用在自動處理失敗）。"""
    _require(actor, "system")
    t = Task(id=len(case.tasks) + 1, to=actor, text=text)
    case.tasks.append(t)
    _log(case, actor, "新增任務", text)
    return t


def log(case: Case, actor: str, action: str, detail: str = "") -> None:
    """只寫操作紀錄、不改資料（例如分派 agent 記錄它做了什麼）。"""
    _require(actor, "system", "agent:extract", "agent:check", "agent:triage", "agent:document",
             "agent:report", "agent:faq")
    _log(case, actor, action, detail)


def record_documents(case: Case, actor: str, files: list[str], draft: bool) -> None:
    _require(actor, "agent:document")
    case.documents = files
    _log(case, actor, "產生同意書", f"{len(files)} 份，{'草稿' if draft else '正式版'}")


# ───── 農民

def _planned(case: Case) -> dict[str, dict]:
    from .agents import triage  # 延遲匯入，避免循環
    return {q["id"]: q for q in triage.questions(case)}


def answer(case: Case, actor: str, question: str, value: str, channel: Channel, transcript: str = "") -> FarmerAnswer:
    """農民回答目前要問的題目（q1–q3、核對題、法律題、實施期間）。核對題的答案會套用到欄位。"""
    from .agents import triage
    _require(actor, "farmer")
    q = _planned(case).get(question)
    if q is None:
        raise ActionError(f"沒有這一題：{question}")
    labels = {o["value"]: o["label"] for o in q["options"]}
    if value not in labels:
        raise ActionError(f"第 {question} 題不能回答「{value}」")
    if channel == Channel.voice and not transcript.strip():
        raise ActionError("語音回答要附上辨識到的原文")
    a = FarmerAnswer(question=question, value=value, channel=channel, transcript=transcript.strip())
    case.answers[question] = a
    _log(case, actor, "回答問題",
         f"{question}={labels[value]}（{'語音：' + a.transcript if channel == Channel.voice else '按鈕'}）")
    target = triage.check_target(question)
    if target is not None:
        _apply_check(case, actor, target, value)
    return a


def _apply_check(case: Case, actor: str, target: str, value: str) -> None:
    """核對題：一樣 → 確認（看不清的欄位不能確認，維持待確認）；不一樣 → 退回；我不確定 → 回到待確認。"""
    for c in [c for c in case.claims if c.target == target]:
        if value == "yes" and c.ai_value:
            confirm_claim(case, actor, c.id)
        elif value == "no":
            reject_claim(case, actor, c.id)
        else:
            reset_claim(case, actor, c.id)


def answer_label(case: Case, question: str, value: str) -> str:
    """回答的顯示文字（用該題選項的文字）。"""
    q = _planned(case).get(question)
    if q:
        return next((o["label"] for o in q["options"] if o["value"] == value), value)
    return ANSWER_LABEL.get(value, value)


def confirm_claim(case: Case, actor: str, claim_id: str) -> FieldClaim:
    """只有農民本人能確認（對照謄本說「一樣」）。agent 與 system 一律拒絕。值一律是 AI 讀到的原值。"""
    _require(actor, "farmer")
    c = _claim(case, claim_id)
    if not c.ai_value:
        raise ActionError(f"{claim_id} 看不清，不能確認；請重拍這一頁")
    c.value, c.status, c.confirmed_by = c.ai_value, ClaimStatus.confirmed, actor
    _log(case, actor, "確認欄位", claim_id)
    return c


def reject_claim(case: Case, actor: str, claim_id: str) -> FieldClaim:
    """農民說跟謄本「不一樣」。"""
    _require(actor, "farmer")
    c = _claim(case, claim_id)
    c.status, c.confirmed_by = ClaimStatus.rejected, None
    _log(case, actor, "退回欄位", claim_id)
    return c


def reset_claim(case: Case, actor: str, claim_id: str) -> FieldClaim:
    """回到待確認（農民改答「我不確定」，或看不清的欄位）。"""
    _require(actor, "farmer")
    c = _claim(case, claim_id)
    if c.status != ClaimStatus.pending:
        c.status, c.confirmed_by = ClaimStatus.pending, None
        _log(case, actor, "欄位改回待確認", claim_id)
    return c


# ───── 查詢（不改資料）

def confirmed(case: Case, claim_id: str) -> str | None:
    for c in case.claims:
        if c.id == claim_id:
            return c.value if c.status == ClaimStatus.confirmed else None
    return None


def area_ha(case: Case, pid: str) -> str | None:
    """本筆面積（公頃）：只用已確認的面積計算；不能算回傳 None。"""
    from .agents import area
    m2 = confirmed(case, f"{pid}-area_m2")
    return area.to_ha(m2) if m2 else None


def right_area_ha(case: Case, oid: str) -> str | None:
    """權利面積（公頃）= 已確認的本筆面積（四捨五入後）× 已確認的持分；不能算回傳 None。"""
    from .agents import area
    o = next((o for o in case.ownerships if o.oid == oid), None)
    ha = area_ha(case, o.pid) if o else None
    share = confirmed(case, f"{oid}-share")
    frac = area.parse_share(share) if share else None
    return area.right_ha(ha, frac) if ha and frac is not None else None


def period(case: Case) -> str | None:
    """實施期間：農民選的年數，從回答那年（民國）1 月 1 日起算。沒選或不確定回傳 None。"""
    a = case.answers.get("period")
    if not a or a.value not in PERIOD_YEARS:
        return None
    return period_text(a.value, roc_year(a.at))


def missing(case: Case) -> list[str]:
    """還不能出正式版的原因。空清單 = 可以出正式版（⑤ 文件 agent 的送出條件；非空就是草稿）。"""
    from .agents import triage
    if not case.claims:
        return ["還沒有擷取結果"]
    out: list[str] = []
    for c in case.claims:
        if c.status == ClaimStatus.rejected:
            out.append(f"已退回：{c.id}")
        elif c.status != ClaimStatus.confirmed:
            out.append(f"未確認：{c.id}")
    a1 = case.answers.get("q1")
    if a1 is None:
        out.append(f"農民還沒回答：{QUESTIONS['q1'][0]}")
    elif a1.value != "yes":
        out.append(f"農民第 1 題回答「{ANSWER_LABEL[a1.value]}」")
    out += [f"農民還沒回答：{q['text']}" for q in triage.unanswered(case) if q["id"] != "q1"]
    if "period" in case.answers and period(case) is None:
        out.append("實施期間未決定")
    out += [f"無法計算：{p.pid} 本筆面積（公頃）" for p in case.parcels if area_ha(case, p.pid) is None]
    out += [f"無法計算：{o.oid} 權利面積（公頃）" for o in case.ownerships if right_area_ha(case, o.oid) is None]
    return out


# 給農民看的待辦（固定範本，用農民的說法；不放編號、不用術語）
TODO_NOT_MINE = "你說這不是你的地，請拍你自己的謄本"
TODO_Q1_UNSURE = "你還不確定這是不是你的地，請再看一次"
TODO_UNREADABLE = "第 {n} 筆地：有字看不清楚，請重拍第 {p} 張"
TODO_DIFFERENT = "第 {n} 筆地：資料跟謄本不一樣，請重拍第 {p} 張"
TODO_CHECK_UNSURE = "第 {n} 筆地：你還不確定資料對不對，請再看一次"
TODO_CANNOT_COMPUTE = "第 {n} 筆地：面積或持分看不懂，請重拍第 {p} 張"
TODO_PERIOD = "還沒決定要簽幾年"
TODO_UNANSWERED = "還有題目沒回答"


def retake_pages(case: Case) -> list[int]:
    """建議重拍的頁：有看不清、跟謄本不一樣、或面積持分算不出來的欄位所在的頁。"""
    pages = set()
    for c in case.claims:
        if not c.ai_value or c.status == ClaimStatus.rejected:
            pages.add(c.source.page)
    for p in case.parcels:
        mine = [c for c in case.claims if c.target == p.pid or c.target.startswith(p.pid + "-")]
        if all(c.status == ClaimStatus.confirmed for c in mine) and not (
                area_ha(case, p.pid) and all(right_area_ha(case, o.oid) for o in case.ownerships if o.pid == p.pid)):
            pages |= {c.source.page for c in mine if c.field in (ClaimField.area_m2, ClaimField.share)}
    return sorted(pages)


def todo(case: Case) -> list[str]:
    """農民還要做的事（固定範本）。空清單 = 農民這邊都做完了。"""
    from .agents import triage
    if not case.claims:
        return []
    a1 = case.answers.get("q1")
    if a1 and a1.value == "no":
        return [TODO_NOT_MINE]
    out: list[str] = []
    if a1 and a1.value == "unsure":
        out.append(TODO_Q1_UNSURE)
    owner_pid = {o.oid: o.pid for o in case.ownerships}
    for n, p in enumerate(case.parcels, 1):
        mine = [c for c in case.claims if c.target == p.pid or owner_pid.get(c.target) == p.pid]
        checks = [f"{triage.CHECK_LAND}{p.pid}"] + [f"{triage.CHECK_OWNER}{o.oid}" for o in case.ownerships
                                                     if o.pid == p.pid]
        for c in mine:
            if not c.ai_value:
                out.append(TODO_UNREADABLE.format(n=n, p=c.source.page))
        for c in mine:
            if c.status == ClaimStatus.rejected:
                out.append(TODO_DIFFERENT.format(n=n, p=c.source.page))
        if any(q in case.answers and case.answers[q].value == "unsure" for q in checks):
            out.append(TODO_CHECK_UNSURE.format(n=n))
        computable = area_ha(case, p.pid) and all(right_area_ha(case, o.oid)
                                                  for o in case.ownerships if o.pid == p.pid)
        if all(c.status == ClaimStatus.confirmed for c in mine) and not computable:
            pages = sorted({c.source.page for c in mine if c.field in (ClaimField.area_m2, ClaimField.share)})
            out.append(TODO_CANNOT_COMPUTE.format(n=n, p="、".join(map(str, pages)) or p.source.page))
    if "period" in case.answers and period(case) is None:
        out.append(TODO_PERIOD)
    if triage.unanswered(case):
        out.append(TODO_UNANSWERED)
    return list(dict.fromkeys(out))
