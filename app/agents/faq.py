"""⑦ 服務台 agent：農民按「問問題」用講的發問，阿伯像服務台櫃員一樣回答。

規則（AGENTS.md）：
- 回答只從下面的固定答案庫挑，不讓 LLM 自由產生文字。「下一步」這類會看案例狀態，但也是固定範本。
- 法律、能不能簽這類問題一律不判斷，請他問地政事務所或農會。
- 找不到合適的答案就老實說不會，不硬答。
- 不保存錄音；只記錄問題文字與挑中的答案（操作紀錄）。

比對：關鍵詞命中越長、越多，分數越高。之後若改用 LLM 分類，也只能回傳下面的答案 id。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ..models import Case, Stage


@dataclass(frozen=True)
class Faq:
    id: str
    keys: tuple[str, ...]
    answer: str


# 順序有意義：同分時排前面的優先（例如法律問題要先於一般問題）
FAQS: tuple[Faq, ...] = (
    Faq("legal", ("法律", "違法", "犯法", "會不會有問題", "有沒有問題", "租約", "三七五", "共有", "繼承", "過戶",
                  "賣", "抵押", "貸款", "稅", "告", "糾紛", "可以簽嗎", "能不能簽", "要不要簽", "應該簽"),
        "這個牽涉到法律，我不能幫你判斷。請你問地政事務所或農會，比較準。"),
    Faq("next", ("下一步", "現在要做什麼", "要做什麼", "接下來", "怎麼做", "然後呢", "再來"),
        ""),  # 依狀態產生，見 _next()
    Faq("what", ("這是什麼", "這是要做什麼", "做什麼用", "幹嘛", "為什麼要做", "同意書是什麼", "什麼東西"),
        "我們在幫你準備土地使用同意書。你拍謄本、核對一下、回答幾個問題，最後印出來簽名就好。"),
    Faq("who", ("你是誰", "你好", "阿伯是誰", "你是什麼"),
        "我是阿伯，幫你做同意書的小幫手。有不懂的，都可以按「問問題」問我。"),
    Faq("why_photo", ("為什麼要拍", "拍謄本", "拍這個", "為什麼拍", "謄本是什麼"),
        "謄本上有你土地的資料。拍下來，系統會幫你把字抄到同意書上，你就不用自己寫。"),
    Faq("photo_tips", ("拍不好", "太暗", "模糊", "不清楚", "怎麼拍", "拍不起來", "重拍", "糊"),
        "到亮一點的地方，把謄本放平，四個角都拍進來，手拿穩再按拍照。"),
    Faq("privacy", ("安全", "外流", "個資", "給誰看", "會不會被", "詐騙", "被騙", "資料去哪"),
        "照片只用來讀謄本上的字、做你的同意書，不會拿去做別的事。這個系統也不會跟你要錢或密碼。"),
    Faq("how_long", ("多久", "幾分鐘", "要很久", "還要等", "什麼時候好", "怎麼這麼久"),
        "全部大約十分鐘。讀謄本的時候要等一下，手機放著就好。"),
    Faq("check", ("一樣是什麼", "怎麼核對", "核對", "對對看", "不一樣怎麼辦", "看不清"),
        "請拿出你的謄本對對看。卡片上的字跟謄本上一樣，就按一樣；不一樣就按不一樣。看不清楚也沒關係，按我不確定。"),
    Faq("unsure", ("不知道", "不確定", "不會答", "怎麼答", "答不出來", "不懂"),
        "不知道沒關係，按「我不確定」就好。同意書會先當草稿，之後再補。"),
    Faq("category", ("分耕", "託耕", "輪耕", "承租", "耕作方式", "哪一種"),
        "這四種是寫在同意書上的耕作方式。不確定是哪一種，就按「我不確定」，簽的時候再寫上去。"),
    Faq("period", ("幾年", "期間", "簽多久", "多少年"),
        "看你跟種田的人怎麼講好。可以選一年、三年或五年；還沒講好，就按「我不確定」。"),
    Faq("sign", ("簽名", "蓋章", "印章", "去哪裡簽", "怎麼簽", "印出來", "列印", "下載"),
        "同意書下載以後印出來。你和種田的人都要簽名蓋章，再寫上日期。種田的人名字和身分證號，簽的時候自己寫。"),
    Faq("draft", ("草稿", "正式", "還沒好"),
        "草稿的意思是還有地方沒確認好。照著「還要處理的事」做完，就會變成正式的。"),
    Faq("mistake", ("按錯", "選錯", "回去", "上一步", "改答案", "反悔"),
        "沒關係。按左上角的箭頭可以回上一步，重新選一次。"),
)

FALLBACK = "這個我還不會回答。你可以問農會，或請家人幫你看看。"
NOT_HEARD = "我沒聽清楚，可以再說一次，或按下面的按鈕問我。"

# 給不方便講話的人：直接點的常見問題（依階段）
SUGGEST = {
    "photo": ["這是要做什麼？", "怎麼拍比較清楚？", "我的資料安全嗎？"],
    "wait": ["還要多久？", "這是要做什麼？", "我的資料安全嗎？"],
    "answer": ["現在要做什麼？", "我不知道怎麼答", "按錯了怎麼辦？"],
    "done": ["怎麼簽名？", "什麼是草稿？", "這是要做什麼？"],
}


def _norm(text: str) -> str:
    return re.sub(r"[\s，。！？、,.!?「」]", "", str(text))


def match(text: str) -> Faq | None:
    """回傳分數最高的答案；完全沒命中回傳 None。"""
    t = _norm(text)
    if not t:
        return None
    best, best_score = None, 0
    for f in FAQS:
        score = sum(len(k) for k in f.keys if k in t)
        if score > best_score:
            best, best_score = f, score
    return best


def _phase(case: Case, next_question: str | None) -> str:
    if case.stage == Stage.collecting:
        return "photo"
    if case.stage in (Stage.extracting, Stage.needs_human):
        return "wait"
    return "answer" if next_question else "done"


def _next(case: Case, next_question: str | None) -> str:
    """「下一步」的固定範本，依案例狀態套入。"""
    if case.stage == Stage.collecting:
        done = {p.page for p in case.photos if p.ok}
        page = next((p for p in range(1, case.pages_expected + 1) if p not in done), case.pages_expected)
        return f"現在請你拍第 {page} 張土地謄本，一共 {case.pages_expected} 張。"
    if case.stage == Stage.extracting:
        return "現在在讀你的謄本，你不用做事，等一下就好。"
    if case.stage == Stage.needs_human:
        return "系統讀不了這份謄本。請重新拍一次，或找家人幫忙。"
    if next_question:
        return f"現在請你回答：{next_question}"
    return "都好了。請下載同意書，印出來簽名蓋章。"


def reply(case: Case, text: str, next_question: str | None = None) -> dict:
    """回答一個問題。next_question：農民現在該回答的題目文字（沒有就是 None）。"""
    f = match(text)
    if not _norm(text):
        fid, answer = "not_heard", NOT_HEARD
    elif f is None:
        fid, answer = "fallback", FALLBACK
    elif f.id == "next":
        fid, answer = "next", _next(case, next_question)
    else:
        fid, answer = f.id, f.answer
    return {"id": fid, "answer": answer, "say": answer, "suggestions": SUGGEST[_phase(case, next_question)]}
