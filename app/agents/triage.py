"""④ 分派 agent：決定每個待確認項目由誰處理。

規則（docs/farmer-ux-agents.md）：本人最清楚的 3 題給農民；謄本欄位、差異、看不清給協助者；
農民答「不是」「我不確定」「別人在種」時，加任務給協助者；
法律注意事項的題目（L-...）農民答「不知道／沒有」或「我不確定」時，也加任務給協助者。
"""
from __future__ import annotations

from .. import actions
from . import legal
from ..models import Case

ACTOR = "agent:triage"


def after_extraction(case: Case, flags: list[str]) -> None:
    actions.add_task(case, ACTOR, f"核對 {len(case.claims)} 個謄本欄位，並填公頃面積、實施期間"
                                  + (f"（核對 agent 提醒 {len(flags)} 項）" if flags else ""))


def after_answer(case: Case, question: str, value: str) -> None:
    if question in legal.QUESTIONS:
        q = legal.QUESTIONS[question]
        if value in q.flag:  # 會產生風險的答案（例如租約題答「有」）才加任務
            issue = legal.issue_for_question(case, question)
            actions.add_task(case, ACTOR, f"農民對「{q.text}」回答「{q.label(value)}」，請聯絡確認"
                                          + (f"（法律注意事項：{issue.title}）" if issue else ""))
        return
    if value == "unsure":
        actions.add_task(case, ACTOR, f"農民對第 {question[1]} 題不確定，請聯絡確認")
    elif question == "q1" and value == "no":
        actions.add_task(case, ACTOR, "農民說這幾筆不是他的地，請確認謄本是否拿錯")
    elif question == "q2" and value == "other":
        actions.add_task(case, ACTOR, "農民說由別人耕作，請填耕作人姓名及 ID")
