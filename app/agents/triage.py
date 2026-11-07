"""④ 分派 agent：決定現在要問農民哪些題目、照什麼順序。

協助者角色已取消，所有事情都由農民自己在手機上確認（docs/farmer-ux-agents.md）。
題目順序（全部是固定範本，不由 LLM 產生）：
  q1 → 每筆土地的核對題 C-land-{pid} → 每筆所有權的核對題 C-owner-{oid} → q2 → q3
  → 法律題（legal.plan，含追問）→ 實施期間 period
q1 答「不是」時，後面的題目都不問。
本 agent 不能確認任何欄位；核對題的答案由農民本人透過 actions.answer 套用。
"""
from __future__ import annotations

from .. import actions
from ..models import (ANSWER_LABEL, CHECK_LAND_SAY, CHECK_LAND_TEXT, CHECK_OPTIONS, CHECK_OWNER_SAY,
                      CHECK_OWNER_TEXT, PERIOD_SAY, PERIOD_TEXT, PERIOD_YEARS, QUESTION_UI, QUESTIONS, UNREADABLE,
                      Case, period_label, roc_year)
from . import legal

ACTOR = "agent:triage"
CHECK_LAND = "C-land-"
CHECK_OWNER = "C-owner-"
PERIOD = "period"


def after_extraction(case: Case, flags: list[str]) -> None:
    """擷取完成後只寫一筆紀錄；要問農民的核對題由 questions() 依資料推出，不另建任務。"""
    actions.log(case, ACTOR, "分派", f"{len(case.claims)} 個謄本欄位交給農民對照謄本確認"
                + (f"（核對 agent 提醒 {len(flags)} 項）" if flags else ""))


def check_target(question_id: str) -> str | None:
    """核對題對應的土地 pid 或所有權 oid；不是核對題回傳 None。"""
    for prefix in (CHECK_LAND, CHECK_OWNER):
        if question_id.startswith(prefix):
            return question_id[len(prefix):]
    return None


def parcel_no(case: Case, pid: str) -> int:
    """第幾筆地（1 起算，依擷取順序）。"""
    return next((n for n, p in enumerate(case.parcels, 1) if p.pid == pid), 0)


def _shown(case: Case, claim_id: str) -> str:
    c = next((c for c in case.claims if c.id == claim_id), None)
    return c.value if c and c.value else UNREADABLE


def _q(qid: str, text: str, say: str, kind: str, options, why: str = "", legal_q: bool = False,
       card: dict | None = None) -> dict:
    return {"id": qid, "text": text, "say": say, "kind": kind,
            "options": [{"value": v, "label": label} for v, label in options],
            "why": why, "legal": legal_q, "card": card}


def _basic(qid: str) -> dict:
    ui = QUESTION_UI[qid]
    return _q(qid, QUESTIONS[qid][0], ui["say"], ui["kind"], [(v, ANSWER_LABEL[v]) for v in ui["options"]])


def _check_questions(case: Case) -> list[dict]:
    out = []
    for p in case.parcels:
        area = _shown(case, f"{p.pid}-area_m2")
        out.append(_q(f"{CHECK_LAND}{p.pid}", CHECK_LAND_TEXT.format(n=parcel_no(case, p.pid)), CHECK_LAND_SAY,
                      "same", CHECK_OPTIONS, card={
                          "rows": [{"label": "坐落", "value": _shown(case, f"{p.pid}-location")},
                                   {"label": "地號", "value": _shown(case, f"{p.pid}-lot_no")},
                                   {"label": "面積", "value": area if area == UNREADABLE else f"{area} 平方公尺"}],
                          "photo_page": p.source.page}))
    for o in case.ownerships:  # 只放姓名、遮蔽後的證號、持分；不放地址
        out.append(_q(f"{CHECK_OWNER}{o.oid}", CHECK_OWNER_TEXT.format(n=parcel_no(case, o.pid)), CHECK_OWNER_SAY,
                      "same", CHECK_OPTIONS, card={
                          "rows": [{"label": "地主", "value": _shown(case, f"{o.oid}-owner")},
                                   {"label": "身分證", "value": _shown(case, f"{o.oid}-id_no")},
                                   {"label": "持分", "value": _shown(case, f"{o.oid}-share")}],
                          "photo_page": o.source.page}))
    return out


def _period_question() -> dict:
    start = roc_year()
    return _q(PERIOD, PERIOD_TEXT, PERIOD_SAY, "years",
              [(y, period_label(y, start)) for y in PERIOD_YEARS] + [("unsure", ANSWER_LABEL["unsure"])])


def questions(case: Case) -> list[dict]:
    """現在要問農民的全部題目（依序）。每題：{id, text, say, kind, options, why, legal, card}。"""
    out = [_basic("q1")]
    a1 = case.answers.get("q1")
    if a1 and a1.value == "no":
        return out
    out += _check_questions(case)
    out += [_basic("q2"), _basic("q3")]
    out += [_q(x.question.id, x.question.text, x.question.say, x.question.kind, x.question.options,
               why=x.question.why, legal_q=True) for x in legal.plan(case)]
    out.append(_period_question())
    return out


def unanswered(case: Case) -> list[dict]:
    return [q for q in questions(case) if q["id"] not in case.answers]
