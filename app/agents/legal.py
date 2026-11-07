"""法律注意事項：用固定規則從案例資料找出「需要留意」的情況，打分後只問農民最可能的幾題。

立場（docs/legal-questions.md）：這是提醒，不是法律判斷。
- 規則只偵測情況，產生「給協助者的待辦」與「給農民的固定範本問題」，系統不下任何法律結論。
- 法條參考一律以「（待法律專業確認）」結尾。
- 給農民的文字用農民的說法、固定範本，不由 LLM 產生；不出現其他所有權人的姓名、證號、地址。

選題（plan）：
1. 每條規則依案例資料算分數（0–100，可能性 × 影響），附上算分理由。
2. 只問分數最高的前 LEGAL_MAX_FARMER_QUESTIONS 題（預設 2）；已回答的題目一定保留，畫面不會跳動。
3. 依答案補全細節：每題最多 1 個追問，只在答案顯示風險時出現。
4. 法律題總數（含追問）最多 LEGAL_MAX_TOTAL 題（預設 3）。
5. 沒被選中的注意事項照樣給協助者處理，只是不問農民；協助者畫面會寫出為什麼問、為什麼沒問。

issues(case) 是純函式：每次都從目前的案例資料重新推出來，只有農民的回答與協助者的處理紀錄
（case.answers、case.legal_notes）會被儲存。要加新規則，寫一個 rule 函式並加進 RULES。
之後若改用 LLM 排序，也只能調整分數、從固定題庫挑題，不能產生題目文字。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Callable

from ..models import ClaimField, ClaimStatus, Case

PENDING_LAW = "（待法律專業確認）"


@dataclass(frozen=True)
class LegalQuestion:
    """問農民的題目（固定範本）。options：(value, label)。flag：會產生協助者任務的答案。"""
    id: str
    kind: str
    text: str
    say: str
    why: str
    options: tuple[tuple[str, str], ...]
    flag: frozenset[str] = frozenset({"no", "unsure"})

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
    score: int = 0
    score_reason: str = ""
    question: LegalQuestion | None = None
    followups: dict[str, LegalQuestion] = field(default_factory=dict, compare=False)  # 答案 value → 追問


@dataclass(frozen=True)
class Asked:
    """選題結果：要問農民的一題。"""
    question: LegalQuestion
    issue: LegalIssue
    followup: bool = False


# ───── 題庫（全部固定；要不要問由規則與分數決定）

_YNU = (("yes", "是"), ("no", "不是"), ("unsure", "我不確定"))

QUESTIONS: dict[str, LegalQuestion] = {q.id: q for q in (
    LegalQuestion(
        id="L-coowner", kind="yesno",
        text="這筆地還有其他地主，他們知道你要簽同意書嗎？",
        say="這筆地，還有其他地主。他們知道你要簽同意書嗎？",
        why="因為這筆地有好幾個地主",
        options=(("yes", "知道"), ("no", "不知道"), ("unsure", "我不確定")),
    ),
    LegalQuestion(
        id="L-coowner-reach", kind="yesno",
        text="其他地主，你聯絡得到嗎？",
        say="其他地主，你聯絡得到嗎？請說，聯絡得到，或是，聯絡不到。",
        why="因為你說其他地主還不知道",
        options=(("yes", "聯絡得到"), ("no", "聯絡不到"), ("unsure", "我不確定")),
    ),
    LegalQuestion(
        id="L-lease", kind="have",
        text="你跟種田的人，有沒有簽租約？",
        say="你跟種田的人，有沒有簽租約？請說，有，或是，沒有。",
        why="因為你說是別人在種",
        options=(("yes", "有"), ("no", "沒有"), ("unsure", "我不確定")),
        flag=frozenset({"yes", "unsure"}),
    ),
    LegalQuestion(
        id="L-lease-375", kind="yesno",
        text="這份租約，是三七五租約嗎？",
        say="這份租約，是三七五租約嗎？請說，是，或是，不是。",
        why="因為你說有簽租約",
        options=_YNU,
        flag=frozenset({"yes", "unsure"}),
    ),
)}


def _lot(case: Case, pid: str) -> str:
    return next((c.value for c in case.claims if c.id == f"{pid}-lot_no"), "")


def _unclear(c) -> bool:
    return c.status != ClaimStatus.confirmed and (not c.ai_value or any("看不清" in f for f in c.flags))


# ───── 規則：每個函式回傳 0 或 1 個 LegalIssue（含分數）

def rule_coowner(case: Case) -> LegalIssue | None:
    """同一筆土地有 2 筆以上所有權登記 → 共有。地主越多、持分看不清，分數越高。"""
    counts: dict[str, int] = {}
    for o in case.ownerships:
        counts[o.pid] = counts.get(o.pid, 0) + 1
    shared = [pid for pid, n in counts.items() if n >= 2]
    if not shared:
        return None
    most = max(counts[pid] for pid in shared)
    score = min(80, 55 + 10 * (most - 2))
    why = [f"同一筆地最多 {most} 位地主（{score}）"]
    if any(c.field == ClaimField.share and _unclear(c) and c.target.split("-")[0] in shared for c in case.claims):
        score += 10
        why.append("持分看不清（+10）")
    parts = [f"{pid}（地號 {_lot(case, pid) or '待確認'}，{counts[pid]} 筆所有權登記）" for pid in shared]
    return LegalIssue(
        id="coowner",
        title="共有土地：需確認其他共有人是否同意或一起簽署",
        detail="共有土地：" + "、".join(parts) + "。請確認其他共有人是否同意，或是否需要一起簽同意書。",
        reference="民法第 818、820 條；土地法第 34 條之 1" + PENDING_LAW,
        score=score, score_reason="；".join(why),
        question=QUESTIONS["L-coowner"],
        followups={"no": QUESTIONS["L-coowner-reach"]},
    )


_LEASE_SCORE = {"承租": (90, "第 3 題答承租，很可能有租約"),
                "unsure": (75, "第 3 題不確定耕作方式"),
                "託耕": (65, "第 3 題答託耕"), "輪耕": (65, "第 3 題答輪耕"), "分耕": (65, "第 3 題答分耕")}


def rule_lease(case: Case) -> LegalIssue | None:
    """農民說是別人在種 → 可能有耕地租約。第 3 題答承租時分數最高。"""
    a = case.answers.get("q2")
    if not a or a.value != "other":
        return None
    q3 = case.answers.get("q3")
    score, why = _LEASE_SCORE.get(q3.value, (70, "")) if q3 else (75, "第 3 題還沒回答")
    how = f"；第 3 題回答「{q3.value}」" if q3 and q3.value != "unsure" else ""
    return LegalIssue(
        id="lease",
        title="有他人耕作：需確認是否有耕地租約（例如三七五租約），會影響由誰簽",
        detail=f"農民第 2 題回答由別人耕作{how}。請確認有沒有耕地租約，以及同意書應由誰簽署。",
        reference="耕地三七五減租條例" + PENDING_LAW,
        score=score, score_reason="第 2 題答別人在種" + (f"；{why}" if why else "") + f"（{score}）",
        question=QUESTIONS["L-lease"],
        followups={"yes": QUESTIONS["L-lease-375"]},
    )


def rule_unclear_share(case: Case) -> LegalIssue | None:
    """權利範圍看不清（AI 讀不到或被標看不清），且協助者還沒對照原件確認。只給協助者。"""
    bad = [c for c in case.claims if c.field == ClaimField.share and _unclear(c)]
    if not bad:
        return None
    return LegalIssue(
        id="unclear-share",
        title="權利範圍看不清：無法判斷簽署人的權利是否完整",
        detail="看不清的權利範圍：" + "、".join(c.id for c in bad)
               + "。請對照原件或重新申請謄本後填入；確認欄位後此項會自動消失。",
        reference="民法第 817、819 條（應有部分）" + PENDING_LAW,
        score=50, score_reason=f"{len(bad)} 個權利範圍看不清（50）",
    )


RULES: list[Callable[[Case], LegalIssue | None]] = [rule_coowner, rule_lease, rule_unclear_share]


def issues(case: Case) -> list[LegalIssue]:
    """目前有效的法律注意事項，依分數由高到低（同分照 RULES 順序）。"""
    found = [i for i in (rule(case) for rule in RULES) if i is not None]
    return sorted(found, key=lambda i: -i.score)


# ───── 選題

def _num(name: str, default: int) -> int:
    try:
        return max(0, int(os.getenv(name, default)))
    except ValueError:
        return default


def limits() -> tuple[int, int]:
    """（最多問幾個注意事項, 法律題總數上限含追問）"""
    return _num("LEGAL_MAX_FARMER_QUESTIONS", 2), _num("LEGAL_MAX_TOTAL", 3)


def _ranked(case: Case) -> list[LegalIssue]:
    """可以問農民的注意事項：已回答的排前面（畫面不跳動），其次分數高的。"""
    askable = [i for i in issues(case) if i.question]
    return sorted(askable, key=lambda i: (i.question.id not in case.answers, -i.score))


def plan(case: Case) -> list[Asked]:
    """現在要問農民的法律題（依序，含追問）。"""
    max_issues, max_total = limits()
    out: list[Asked] = []
    for issue in _ranked(case)[:max_issues]:
        out.append(Asked(issue.question, issue))
        a = case.answers.get(issue.question.id)
        fu = issue.followups.get(a.value) if a else None
        if fu:
            out.append(Asked(fu, issue, followup=True))
    kept: list[Asked] = []
    for x in out:  # 總數上限；已回答的一定保留
        if len(kept) < max_total or x.question.id in case.answers:
            kept.append(x)
    return kept


def active_questions(case: Case) -> list[LegalQuestion]:
    return [x.question for x in plan(case)]


def issue_for_question(case: Case, question_id: str) -> LegalIssue | None:
    for i in issues(case):
        if (i.question and i.question.id == question_id) or any(q.id == question_id for q in i.followups.values()):
            return i
    return None


def selection(case: Case) -> dict[str, dict]:
    """給協助者看的選題紀錄：每個注意事項有沒有問農民、為什麼。"""
    max_issues, _ = limits()
    asked = plan(case)
    asked_ids = {x.issue.id for x in asked if not x.followup}
    rank = {i.id: n for n, i in enumerate(_ranked(case), 1)}
    out = {}
    for i in issues(case):
        if not i.question:
            reason = "只給協助者：這類事項不適合問農民"
        elif i.id in asked_ids:
            reason = f"已問農民：分數 {i.score}，排第 {rank[i.id]}"
        else:
            reason = f"沒有問農民：分數 {i.score}，排第 {rank[i.id]}，每案最多問 {max_issues} 項"
        fu = next((x.question for x in asked if x.followup and x.issue.id == i.id), None)
        out[i.id] = {"asked": i.id in asked_ids, "reason": reason, "followup": fu}
    return out
