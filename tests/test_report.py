"""報告 agent 與服務台 API：答完題目會產生土地分析報告；發問只回固定答案並寫操作紀錄。"""
from __future__ import annotations

import os
from pathlib import Path

from docx import Document

from tests.test_flow import answer_all, client, ready_case  # noqa: F401（共用 fixture 與流程）


def report_text(cid):
    path = Path(os.environ["HACKDAY_DATA"]) / "cases" / cid / "documents" / "土地分析報告.docx"
    doc = Document(path)
    parts = [p.text for p in doc.paragraphs]
    for t in doc.tables:
        parts += [c.text for row in t.rows for c in row.cells]
    return "\n".join(parts)


def test_report_after_all_answered_c01(client):
    cid, token = ready_case(client, "C01")
    assert client.get(f"/api/f/{token}").json()["report"] is None
    r = answer_all(client, token)
    rep = r["report"]
    assert rep["url"] == f"/api/f/{token}/report" and rep["lands"] == 2 and rep["checked"] == 2
    assert not rep["draft"] and rep["todo"] == 0 and rep["total_ha"]
    got = client.get(rep["url"])
    assert got.status_code == 200 and got.content[:2] == b"PK"
    text = report_text(cid)
    assert "土地分析報告" in text and "（草稿）" not in text
    assert "0123-0004" in text and "已核對" in text and "不是法律意見" in text
    assert "沒有發現需要特別留意" in text
    # 報告不在同意書清單裡
    assert all("報告" not in d["name"] for d in r["documents"])


def test_report_lists_legal_issues_and_todo_c02(client):
    cid, token = ready_case(client, "C02")
    r = answer_all(client, token, **{"q2": "other", "q3": "承租", "L-lease": "yes", "L-lease-375": "unsure"})
    assert "共有土地" in r["report"]["issues"]
    text = report_text(cid)
    assert "共有土地" in text and "可能性分數" in text and "待法律專業確認" in text
    assert "請問地政事務所或農會" in text


def test_report_draft_when_unreadable_c03(client):
    cid, token = ready_case(client, "C03")
    r = answer_all(client, token)
    assert r["report"]["draft"] and r["report"]["todo"] >= 1
    text = report_text(cid)
    assert "土地分析報告（草稿）" in text and "有字看不清" in text and "印出來後請對照謄本寫上" in text


def test_ask_desk(client):
    cid, token = ready_case(client, "C01")
    r = client.post(f"/api/f/{token}/ask", json={"text": "現在要做什麼", "channel": "voice"}).json()
    assert r["id"] == "next" and r["answer"].startswith("現在請你回答：")
    r = client.post(f"/api/f/{token}/ask", json={"text": "這樣簽會不會有問題"}).json()
    assert r["id"] == "legal"
    assert client.post("/api/f/not-a-token/ask", json={"text": "你好"}).status_code == 404
    events = client.get(f"/api/cases/{cid}").json()["events"]
    assert sum(e["action"] == "回答農民的問題" for e in events) == 2
    assert client.get(f"/api/f/{token}/report").status_code == 404
