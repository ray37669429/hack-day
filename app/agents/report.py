"""⑥ 報告 agent：把分析結果整理成給農民看的「土地分析報告」（Word），並提供畫面摘要。

內容全部來自案例資料與固定範本，不由 LLM 產生：
一、土地清單（面積換算、核對狀態） 二、地主與持分 三、你的回答
四、法律注意事項（分數、理由、參考；提醒不是法律意見） 五、還要處理的事 六、同意書狀態。

和同意書放在同一個資料夾；文件 agent 每次會清空資料夾，所以本 agent 要排在它之後執行。
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

from .. import actions, store
from ..models import Case, ClaimStatus
from . import legal, triage

ACTOR = "agent:report"
FILE = "土地分析報告.docx"
FONT = "標楷體"

DISCLAIMER = ("本報告由系統依固定規則整理，只供參考，不是法律意見。"
              "法條參考都待法律專業確認；有疑問請問地政事務所或農會。")
AREA_RULE = "面積換算：本筆面積＝平方公尺 ÷ 10000；權利面積＝本筆面積 × 持分；都取小數 4 位、四捨五入。"
ADVICE = "建議：請問地政事務所或農會。"


def _status(claims) -> str:
    if any(not c.ai_value for c in claims):
        return "有字看不清"
    if any(c.status == ClaimStatus.rejected for c in claims):
        return "跟謄本不一樣"
    if all(c.status == ClaimStatus.confirmed for c in claims):
        return "已核對"
    return "還沒核對"


def analyze(case: Case) -> dict:
    """報告的全部內容（純資料）。"""
    val = {c.id: c.value for c in case.claims}
    lands, owners = [], []
    for n, p in enumerate(case.parcels, 1):
        mine = [c for c in case.claims if c.target == p.pid]
        lands.append({"n": n, "location": val.get(f"{p.pid}-location") or "（看不清）",
                      "lot_no": val.get(f"{p.pid}-lot_no") or "（看不清）",
                      "area_m2": val.get(f"{p.pid}-area_m2") or "（看不清）",
                      "area_ha": actions.area_ha(case, p.pid) or "待確認", "status": _status(mine)})
        for o in (o for o in case.ownerships if o.pid == p.pid):
            oc = [c for c in case.claims if c.target == o.oid]
            owners.append({"n": n, "owner": val.get(f"{o.oid}-owner") or "（看不清）",
                           "id_no": val.get(f"{o.oid}-id_no") or "（看不清）",
                           "share": val.get(f"{o.oid}-share") or "（看不清）",
                           "right_ha": actions.right_area_ha(case, o.oid) or "待確認", "status": _status(oc)})
    answers = [{"q": q["text"], "a": actions.answer_label(case, q["id"], case.answers[q["id"]].value)}
               for q in triage.questions(case) if q["id"] in case.answers]
    sel = legal.selection(case)
    issues = []
    for i in legal.issues(case):
        qid = i.question.id if i.question else None
        a = case.answers.get(qid) if qid else None
        issues.append({"title": i.title, "score": i.score, "why": i.score_reason, "reference": i.reference,
                       "asked": sel[i.id]["reason"], "answer": i.question.label(a.value) if a else ""})
    missing = actions.missing(case)
    total = sum((Decimal(x["area_ha"]) for x in lands if x["area_ha"] != "待確認"), Decimal("0"))
    return {"lands": lands, "owners": owners, "answers": answers, "issues": issues,
            "todo": actions.todo(case), "draft": bool(missing), "missing_count": len(missing),
            "total_ha": f"{total:.4f}" if lands and all(x["area_ha"] != "待確認" for x in lands) else "",
            "at": datetime.now().strftime("%Y-%m-%d %H:%M")}


def summary(case: Case) -> dict | None:
    """農民完成畫面的摘要。還沒產生報告時回傳 None。"""
    if not (store.case_dir(case.id) / "documents" / FILE).exists():
        return None
    r = analyze(case)
    return {"name": FILE, "lands": len(r["lands"]), "total_ha": r["total_ha"],
            "checked": sum(1 for x in r["lands"] if x["status"] == "已核對"),
            "issues": [i["title"].split("：")[0] for i in r["issues"]],
            "todo": len(r["todo"]), "draft": r["draft"]}


# ───── Word

def _font(run, size=12, bold=False, color=None):
    run.font.name = FONT
    run._element.rPr.rFonts.set(qn("w:eastAsia"), FONT)
    run.font.size = Pt(size)
    run.bold = bold
    if color:
        run.font.color.rgb = RGBColor.from_string(color)


def _p(doc, text, size=12, bold=False, color=None, after=4):
    para = doc.add_paragraph()
    _font(para.add_run(text), size, bold, color)
    para.paragraph_format.space_after = Pt(after)
    return para


def _table(doc, head, rows):
    t = doc.add_table(rows=1, cols=len(head))
    t.style = "Table Grid"
    for cell, h in zip(t.rows[0].cells, head):
        cell.text = ""
        _font(cell.paragraphs[0].add_run(h), 11, True)
    for r in rows:
        cells = t.add_row().cells
        for cell, v in zip(cells, r):
            cell.text = ""
            _font(cell.paragraphs[0].add_run(str(v)), 11)
    doc.add_paragraph()


def build(case: Case, r: dict) -> Document:
    doc = Document()
    sec = doc.sections[0]
    sec.orientation = WD_ORIENT.PORTRAIT
    sec.left_margin = sec.right_margin = Cm(2)
    _p(doc, "土地分析報告" + ("（草稿）" if r["draft"] else ""), 20, True, after=2)
    _p(doc, f"產生時間：{r['at']}　　案例：{case.id}", 10, color="5C4A36", after=10)

    _p(doc, "一、土地清單", 14, True)
    _table(doc, ["#", "坐落", "地號", "面積（平方公尺）", "本筆面積（公頃）", "核對"],
           [[x["n"], x["location"], x["lot_no"], x["area_m2"], x["area_ha"], x["status"]] for x in r["lands"]])
    if r["total_ha"]:
        _p(doc, f"合計本筆面積：{r['total_ha']} 公頃", 11)
    _p(doc, AREA_RULE, 10, color="5C4A36", after=10)

    _p(doc, "二、地主與持分", 14, True)
    _table(doc, ["#", "地主", "身分證", "持分", "權利面積（公頃）", "核對"],
           [[x["n"], x["owner"], x["id_no"], x["share"], x["right_ha"], x["status"]] for x in r["owners"]])

    _p(doc, "三、你的回答", 14, True)
    _table(doc, ["題目", "回答"], [[x["q"], x["a"] or "—"] for x in r["answers"]] or [["（還沒回答）", ""]])

    _p(doc, "四、法律注意事項（提醒，不是法律意見）", 14, True)
    if r["issues"]:
        for n, i in enumerate(r["issues"], 1):
            _p(doc, f"{n}. {i['title']}", 12, True, after=1)
            _p(doc, f"可能性分數：{i['score']}（{i['why']}）", 11, after=1)
            _p(doc, f"{i['asked']}" + (f"；你的回答：{i['answer']}" if i["answer"] else ""), 11, after=1)
            _p(doc, f"參考：{i['reference']}", 10, color="5C4A36", after=1)
            _p(doc, ADVICE, 11, after=8)
    else:
        _p(doc, "依目前資料，沒有發現需要特別留意的情況。", 11, after=8)

    _p(doc, "五、還要處理的事", 14, True)
    for t in r["todo"] or ["沒有，都處理好了。"]:
        _p(doc, f"・{t}", 12, after=2)

    _p(doc, "六、同意書狀態", 14, True)
    _p(doc, (f"草稿：還有 {r['missing_count']} 件事沒處理好，處理完才是正式版。" if r["draft"]
             else "正式版：資料都核對過了，可以印出來簽名蓋章。"), 12, after=12)

    _p(doc, DISCLAIMER, 10, color="854F0B")
    return doc


def run(case: Case) -> str:
    """產生報告檔，回傳檔名。"""
    out = store.case_dir(case.id) / "documents"
    out.mkdir(exist_ok=True)
    r = analyze(case)
    build(case, r).save(out / FILE)
    actions.log(case, ACTOR, "產生分析報告", f"{len(r['lands'])} 筆地、{len(r['issues'])} 項法律注意事項、"
                                             f"{'草稿' if r['draft'] else '正式'}")
    return FILE
