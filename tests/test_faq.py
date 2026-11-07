"""服務台 agent：只從固定答案庫挑答案；法律問題不判斷；找不到就老實說。"""
from __future__ import annotations

from app.agents import faq
from app.models import Case, Stage


def case(stage=Stage.collecting, **kw):
    return Case(id="K1", farmer_token="t", stage=stage, **kw)


def test_match_common_questions():
    assert faq.match("這是要做什麼？").id == "what"
    assert faq.match("我的資料安全嗎").id == "privacy"
    assert faq.match("還要多久").id == "how_long"
    assert faq.match("怎麼拍比較清楚，照片太暗").id == "photo_tips"
    assert faq.match("我按錯了怎麼辦").id == "mistake"
    assert faq.match("草稿是什麼意思").id == "draft"


def test_legal_questions_are_never_judged():
    for q in ("這樣簽會不會有問題", "三七五租約怎麼辦", "共有的地可以簽嗎", "我要不要簽"):
        r = faq.reply(case(Stage.reviewing), q, "這幾筆是你的地嗎？")
        assert r["id"] == "legal", q
        assert "不能幫你判斷" in r["answer"]


def test_unknown_and_empty():
    r = faq.reply(case(), "今天天氣很好")
    assert r["id"] == "fallback" and r["answer"] == faq.FALLBACK
    assert faq.reply(case(), "  ")["id"] == "not_heard"


def test_next_step_depends_on_state():
    assert "第 1 張" in faq.reply(case(Stage.collecting), "現在要做什麼")["answer"]
    assert "讀你的謄本" in faq.reply(case(Stage.extracting), "下一步呢")["answer"]
    r = faq.reply(case(Stage.reviewing), "接下來要做什麼", "這些地是誰在種？")
    assert r["answer"] == "現在請你回答：這些地是誰在種？"
    assert "下載同意書" in faq.reply(case(Stage.documented), "然後呢", None)["answer"]


def test_answers_are_fixed_templates():
    # 每個答案都來自答案庫（或狀態範本），不是把問題原文接回去
    for q in ("這是要做什麼", "你是誰", "怎麼簽名"):
        r = faq.reply(case(Stage.reviewing), q, "x")
        assert r["answer"] in {f.answer for f in faq.FAQS}
        assert r["say"] == r["answer"] and q not in r["answer"]
    assert faq.reply(case(Stage.reviewing), "x", "q")["suggestions"] == faq.SUGGEST["answer"]
