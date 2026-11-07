"""把農民頁會唸的全部固定句子收進 web/audio/prompts.json，再用 tools/gen_tts.py 產生音檔。

後端的句子（題目、法律題、服務台答案）直接從程式讀，不手抄；前端的句子列在 FRONT。
已經有的句子保留原本的 id 與台語（nan）欄位；新的句子台語留空，等母語者校對後再補。

用法：
    python tools/collect_prompts.py            # 更新 prompts.json，印出新增幾句
    python tools/collect_prompts.py --check    # 只檢查有沒有漏（測試用），有漏就回傳 1
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
PROMPTS = ROOT / "web" / "audio" / "prompts.json"

# 讀回答案時的選項文字（web/farmer.html：你講，○○，對嗎？）；期間只唸年數
READBACK_LABELS = ["是", "不是", "我不確定", "我自己", "別人", "承租", "託耕", "輪耕", "分耕",
                   "一樣", "不一樣", "知道", "不知道", "有", "沒有", "聯絡得到", "聯絡不到", "1 年", "3 年", "5 年"]


def front() -> list[tuple[str, str]]:
    """web/farmer.html 會唸的固定句子（要和 SAY、DESK_HELLO 等完全一樣）。"""
    out = [
        ("retry", "我沒聽清楚，請再講一次。"),
        ("use_buttons", "我沒聽清楚，請按下面的按鈕。"),
        ("again", "好，請再回答一次。"),
        ("received", "收到了。接下來不用做事，好了會請你回答幾個問題。"),
        ("done_ok", "謝謝你，回答完了。同意書做好了，請按下載。"),
        ("done_draft", "謝謝你，回答完了。同意書是草稿，還有幾件事要處理。"),
        ("desk_hello", "有什麼不懂的，都可以問我。按綠色的按鈕，用講的問。"),
        ("desk_again", "請說你的問題。"),
        ("desk_not_heard", "我沒聽清楚，可以再說一次，或按下面的問題。"),
        ("desk_offline", "現在沒辦法回答，請等一下再問一次。"),
        ("photo_open", "照片打不開，請再拍一次。"),
        ("photo_dark", "照片有點暗，請到亮一點的地方再拍一次。"),
        ("photo_blur", "照片有點糊，請拿穩手機，再拍一次。"),
        ("retake", "要重拍哪一張？請按下面的按鈕。"),
    ]
    for n in (1, 2, 3):
        out.append((f"intro{n}", f"你好，我們要幫你準備土地使用同意書。要拍土地謄本 {n} 張，核對謄本上的資料，"
                                 f"回答幾個問題，再選要簽幾年，大約 10 分鐘。"))
        out.append((f"shoot{n}", f"請拍第 {n} 張土地謄本。"))
    for n in (2, 3):
        out.append((f"photo_next{n}", f"很好。請拍第 {n} 張。"))
    for i, label in enumerate(READBACK_LABELS):
        out.append((f"rb_{i:02d}", f"你講，{label}，對嗎？"))
    return out


def back() -> list[tuple[str, str]]:
    """後端產生、前端照唸的句子：題目、法律題、服務台。"""
    from app import models
    from app.agents import faq, legal

    out = [(q, ui["say"]) for q, ui in models.QUESTION_UI.items()]
    out += [("check_land", models.CHECK_LAND_SAY), ("check_owner", models.CHECK_OWNER_SAY),
            ("period", models.PERIOD_SAY)]
    out += [(q.id.lower().replace("-", "_"), q.say) for q in legal.QUESTIONS.values()]
    out += [(f"faq_{i:02d}", t) for i, t in enumerate(faq.spoken())]
    return out


def wanted() -> list[tuple[str, str]]:
    seen, out = set(), []
    for pid, text in front() + back():
        if text not in seen:
            seen.add(text)
            out.append((pid, text))
    return out


def main(argv: list[str]) -> int:
    data = json.loads(PROMPTS.read_text(encoding="utf-8"))
    items = data["items"]
    have = {p["zh"] for p in items}
    ids = {p["id"] for p in items}
    new = [(pid, t) for pid, t in wanted() if t not in have]
    if "--check" in argv:
        for pid, t in new:
            print("缺：", pid, t)
        return 1 if new else 0
    for pid, t in new:
        base, n = pid, 2
        while pid in ids:
            pid, n = f"{base}_{n}", n + 1
        ids.add(pid)
        items.append({"id": pid, "zh": t, "nan": ""})
    PROMPTS.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"新增 {len(new)} 句，共 {len(items)} 句")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
