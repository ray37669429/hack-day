"""法律注意事項：用固定規則從案例資料找出「需要留意」的情況。

立場（docs/legal-questions.md）：這是提醒，不是法律判斷。
- 規則只偵測情況，產生「給協助者的待辦」與「給農民的固定範本問題」，系統不下任何法律結論。
- 法條參考一律以「（待法律專業確認）」結尾。
- 給農民的文字用農民的說法、固定範本，不由 LLM 產生；不出現其他所有權人的姓名、證號、地址。

issues(case) 是純函式：每次都從目前的案例資料重新推出來，只有農民的回答與協助者的處理紀錄
（case.answers、case.legal_notes）會被儲存。要加新規則，寫一個 rule 函式並加進 RULES。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from ..models import ClaimField, ClaimStatus, Case

PENDING_LAW = "（待法律專業確認）"


@dataclass(frozen=True)
class LegalQuestion:
    """問農民的題目（固定範本）。options：(value, label)。"""
    id: str
    kind: str
    text: str
    say: str
    why: str
    options: tuple[tuple[str, str], ...]

    def values(self) -> set[str]:
        return {v for v, _ in self.options}

    def label(self, value: str) -> str:
        return dict(self.options).get(value, value)


@dataclass(frozen=True)
class LegalIssue:
    """給協助者看的注意事項。question 為 None 表示只給協助者處理。"""
    id: str
    title: str
    detail: str
    reference: str
    question: LegalQuestion | None = field(default=None)


# ───── 給農民的題目（全部固定，依 id 查得到；有沒有要問由規則決定）

QUESTIONS: dict[str, LegalQuestion] = {q.id: q for q in (
    LegalQuestion(
        id="L-coowner", kind="yesno",
        text="這筆地還有其他地主，他們知道你要簽同意書嗎？",
        say="這筆地，還有其他地主。他們知道你要簽同意書嗎？",
        why="因為這筆地有好幾個地主",
        options=(("yes", "知道"), ("no", "不知道"), ("unsure", "我不確定")),
    ),
    LegalQuestion(
        id="L-lease", kind="have",
        text="你跟種田的人，有沒有簽租約？",
        say="你跟種田的人，有沒有簽租約？請說，有，或是，沒有。",
        why="因為你說是別人在種",
        options=(("yes", "有"), ("no", "沒有"), ("unsure", "我不確定")),
    ),
)}


def _lot(case: Case, pid: str) -> str:
    return next((c.value for c in case.claims if c.id == f"{pid}-lot_no"), "")


# ───── 規則：每個函式回傳 0 或 1 個 LegalIssue

def rule_coowner(case: Case) -> LegalIssue | None:
    """同一筆土地有 2 筆以上所有權登記 → 共有。"""
    counts: dict[str, int] = {}
    for o in case.ownerships:
        counts[o.pid] = counts.get(o.pid, 0) + 1
    shared = [pid for pid, n in counts.items() if n >= 2]
    if not shared:
        return None
    parts = [f"{pid}（地號 {_lot(case, pid) or '待確認'}，{counts[pid]} 筆所有權登記）" for pid in shared]
    return LegalIssue(
        id="coowner",
        title="共有土地：需確認其他共有人是否同意或一起簽署",
        detail="共有土地：" + "、".join(parts) + "。請確認其他共有人是否同意，或是否需要一起簽同意書。",
        reference="民法第 818、820 條；土地法第 34 條之 1" + PENDING_LAW,
        question=QUESTIONS["L-coowner"],
    )


def rule_lease(case: Case) -> LegalIssue | None:
    """農民說是別人在種 → 可能有耕地租約。"""
    a = case.answers.get("q2")
    if not a or a.value != "other":
        return None
    q3 = case.answers.get("q3")
    how = f"；第 3 題回答「{q3.value}」" if q3 and q3.value != "unsure" else ""
    return LegalIssue(
        id="lease",
        title="有他人耕作：需確認是否有耕地租約（例如三七五租約），會影響由誰簽",
        detail=f"農民第 2 題回答由別人耕作{how}。請確認有沒有耕地租約，以及同意書應由誰簽署。",
        reference="耕地三七五減租條例" + PENDING_LAW,
        question=QUESTIONS["L-lease"],
    )


def rule_unclear_share(case: Case) -> LegalIssue | None:
    """權利範圍看不清（AI 讀不到或被標看不清），且協助者還沒對照原件確認。"""
    bad = [c for c in case.claims
           if c.field == ClaimField.share and c.status != ClaimStatus.confirmed
           and (not c.ai_value or any("看不清" in f for f in c.flags))]
    if not bad:
        return None
    return LegalIssue(
        id="unclear-share",
        title="權利範圍看不清：無法判斷簽署人的權利是否完整",
        detail="看不清的權利範圍：" + "、".join(c.id for c in bad)
               + "。請對照原件或重新申請謄本後填入；確認欄位後此項會自動消失。",
        reference="民法第 817、819 條（應有部分）" + PENDING_LAW,
    )


RULES: list[Callable[[Case], LegalIssue | None]] = [rule_coowner, rule_lease, rule_unclear_share]


def issues(case: Case) -> list[LegalIssue]:
    """目前有效的法律注意事項（依 RULES 順序）。"""
    return [i for i in (rule(case) for rule in RULES) if i is not None]


def active_questions(case: Case) -> list[LegalQuestion]:
    return [i.question for i in issues(case) if i.question is not None]


def issue_for_question(case: Case, question_id: str) -> LegalIssue | None:
    return next((i for i in issues(case) if i.question and i.question.id == question_id), None)
