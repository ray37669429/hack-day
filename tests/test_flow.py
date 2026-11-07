"""端到端測試：用假謄本跑完整流程（照片 → 擷取 → 核對 → 農民自己確認與回答 → 同意書）。

協助者角色已取消：所有確認都由農民在手機上完成。只用虛構資料。
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

import pytest
from docx import Document

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "data" / "samples" / "fake-transcripts"
ROC = datetime.now().year - 1911

SAY = {
    "q1": "這幾筆，是你的地嗎？請說，是，或是，不是。",
    "C-land": "請看一下，這筆地，跟你的謄本上寫的一樣嗎？",
    "C-owner": "請看一下，地主的名字和持分，跟謄本上一樣嗎？",
    "q2": "這些地，是誰在種？是你自己，還是別人？",
    "q3": "用什麼方式給人種？承租、託耕、輪耕，還是分耕？",
    "period": "這份同意書要簽幾年？一年、三年，還是五年？",
}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("HACKDAY_DATA", str(tmp_path))
    monkeypatch.delenv("EXTRACT_ENGINE", raising=False)
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)


def upload(client, token, page, path):
    with open(path, "rb") as f:
        return client.post(f"/api/f/{token}/photos", data={"page": str(page)}, files={"file": (path.name, f, "image/jpeg")})


def start_case(client, sample):
    r = client.post("/api/cases", json={"sample_id": sample})
    assert r.status_code == 200
    return r.json()["id"], r.json()["farmer_token"]


def ready_case(client, sample):
    cid, token = start_case(client, sample)
    assert upload(client, token, 1, SAMPLES / sample / "photo_page1.jpg").json()["ok"]
    assert upload(client, token, 2, SAMPLES / sample / "page2.png").json()["all_pages_done"]
    assert client.get(f"/api/cases/{cid}").json()["stage"] == "reviewing"
    return cid, token


def answer(client, token, q, v, **kw):
    return client.post(f"/api/f/{token}/answers", json={"question": q, "value": v, **kw})


DEFAULT = {"q1": "yes", "q2": "self", "q3": "承租", "period": "3", "L-coowner": "yes", "L-lease": "no"}


def answer_all(client, token, **override):
    """一直回答到沒有題目為止；核對題預設「一樣」。回傳最後一次 POST 的回應。"""
    vals = {**DEFAULT, **override}
    last = None
    for _ in range(30):
        fv = client.get(f"/api/f/{token}").json()
        todo = [q for q in fv["questions"] if q["id"] not in fv["answers"]]
        if not todo:
            return last
        q = todo[0]
        v = vals.get(q["id"], "yes" if q["id"].startswith("C-") else "no")
        last = answer(client, token, q["id"], v)
        assert last.status_code == 200, last.text
        last = last.json()
    raise AssertionError("題目答不完")


def doc_path(cid, name):
    return Path(os.environ["HACKDAY_DATA"]) / "cases" / cid / "documents" / name


def table_text(path):
    doc = Document(path)
    return "\n".join(c.text for t in doc.tables for row in t.rows for c in row.cells)


def is_draft(path):
    doc = Document(path)
    return any("草稿" in p.text for s in doc.sections for p in s.header.paragraphs)


def test_bad_photo_is_rejected(client):
    cid, token = start_case(client, "C03")
    r = upload(client, token, 1, SAMPLES / "C03" / "photo_page1_bad.jpg").json()
    assert r["ok"] is False and "暗" in r["reason"]
    assert client.get(f"/api/cases/{cid}").json()["stage"] == "collecting"


def test_c01_full_flow_by_farmer_only(client):
    cid, token = ready_case(client, "C01")
    fv = client.get(f"/api/f/{token}").json()
    assert set(fv) == {"stage", "pages_expected", "pages_done", "lands", "photos", "questions", "answers",
                       "documents", "todo", "retake", "report"}
    qs = fv["questions"]
    assert [q["id"] for q in qs] == ["q1", "C-land-P1", "C-land-P2", "C-owner-P1-O1", "C-owner-P2-O1",
                                     "q2", "q3", "period"]
    assert all(set(q) == {"id", "text", "say", "kind", "options", "why", "legal", "card"} for q in qs)
    assert [q["kind"] for q in qs] == ["yesno", "same", "same", "same", "same", "who", "cat", "years"]
    assert {q["id"]: q["say"] for q in qs if not q["id"].startswith("C-")} == \
        {k: v for k, v in SAY.items() if not k.startswith("C-")}
    assert all(q["say"] == SAY["C-land"] for q in qs if q["id"].startswith("C-land-"))
    assert all(q["say"] == SAY["C-owner"] for q in qs if q["id"].startswith("C-owner-"))

    land = qs[1]
    assert land["text"] == "第 1 筆地，跟謄本上寫的一樣嗎？"
    assert [(o["value"], o["label"]) for o in land["options"]] == [("yes", "一樣"), ("no", "不一樣"), ("unsure", "我不確定")]
    assert land["card"] == {"rows": [{"label": "坐落", "value": "範例縣試驗鄉示範段"},
                                     {"label": "地號", "value": "0123-0004"},
                                     {"label": "面積", "value": "1234.56 平方公尺"}], "photo_page": 1,
                            # 虛構段名不在內政部清單裡 → 核對 agent 的警示用農民的說法出現在卡片上
                            "warn": ["段名跟官方的名單對不起來，請仔細對一下"]}
    owner = qs[4]
    assert owner["text"] == "第 2 筆地的地主，跟謄本上一樣嗎？"
    assert owner["card"] == {"rows": [{"label": "地主", "value": "農民A"}, {"label": "身分證", "value": "A12345****"},
                                      {"label": "持分", "value": "全部 1分之1"}], "photo_page": 2, "warn": []}
    assert qs[0]["card"] is None and qs[-1]["card"] is None
    period = qs[-1]
    assert period["text"] == "這份同意書要簽幾年？"
    assert [(o["value"], o["label"]) for o in period["options"]] == [
        ("1", f"1 年（{ROC} 年）"), ("3", f"3 年（{ROC}–{ROC + 2} 年）"), ("5", f"5 年（{ROC}–{ROC + 4} 年）"),
        ("unsure", "我不確定")]
    assert fv["documents"] == [] and fv["todo"] == ["還有題目沒回答"]

    # 語音要附原文；不在選項內的值不收
    assert answer(client, token, "q1", "yes", channel="voice").status_code == 400
    assert answer(client, token, "q1", "yes", channel="voice", transcript="是").status_code == 200
    assert answer(client, token, "q2", "maybe").status_code == 400
    assert answer(client, token, "period", "2").status_code == 400
    assert answer(client, token, "C-land-P9", "yes").status_code == 400

    r = answer_all(client, token)
    assert set(r) == {"ok", "answers", "questions", "documents", "todo", "report"}
    assert r["todo"] == []
    assert r["documents"] == [{"name": "同意書_1_正式.docx", "url": f"/api/f/{token}/documents/%E5%90%8C%E6%84%8F%E6%9B%B8_1_%E6%AD%A3%E5%BC%8F.docx", "draft": False}]
    assert r["answers"]["C-land-P1"] == "一樣" and r["answers"]["period"] == f"3 年（{ROC}–{ROC + 2} 年）"

    case = client.get(f"/api/cases/{cid}").json()
    assert case["stage"] == "documented" and case["missing"] == [] and case["todo"] == []
    assert all(c["status"] == "confirmed" and c["confirmed_by"] == "farmer" for c in case["claims"])
    assert case["tasks"] == []

    got = client.get(r["documents"][0]["url"])
    assert got.status_code == 200 and got.content == doc_path(cid, "同意書_1_正式.docx").read_bytes()
    path = doc_path(cid, "同意書_1_正式.docx")
    assert not is_draft(path)
    text = table_text(path)
    # C01：1,234.56 m² → 0.1235；2,345.67 m² → 0.2346；持分 1 → 權利面積相同
    assert text.count("0.1235") == 2 and text.count("0.2346") == 2
    assert f"{ROC}.01.01起\n{ROC + 2}.12.31止" in text
    assert "範例縣試驗鄉示範段\n0123-0004" in text and "農民A\nA12345****" in text and "承租" in text
    assert "待確認" not in text
    preamble = "\n".join(p.text for p in Document(path).paragraphs)
    assert "（以下簡稱乙方）" + "　" * 8 + "等" in preamble   # 乙方留白，簽約時手寫


def test_document_download_only_for_own_case(client):
    cid, token = ready_case(client, "C01")
    other = start_case(client, "C02")[1]
    r = answer_all(client, token)
    name = r["documents"][0]["name"]
    assert client.get(f"/api/f/{token}/documents/{name}").status_code == 200
    assert client.get(f"/api/f/{other}/documents/{name}").status_code == 404
    assert client.get(f"/api/f/not-a-token/documents/{name}").status_code == 404
    assert client.get(f"/api/f/{token}/documents/..%2Fcase.json").status_code == 404
    assert client.get(f"/api/f/{token}/documents/x.docx").status_code == 404
    assert client.get(f"/api/cases/{cid}/documents/{name}").status_code == 200


def test_agent_cannot_confirm(client):
    from app import actions, store
    cid, _ = ready_case(client, "C01")
    case = store.load(cid)
    for actor in ("agent:extract", "agent:check", "agent:triage", "agent:document", "system", "helper"):
        for fn in (actions.confirm_claim, actions.reject_claim):
            with pytest.raises(actions.ActionError):
                fn(case, actor, "P1-lot_no")
        with pytest.raises(actions.ActionError):
            actions.answer(case, actor, "C-land-P1", "yes", "button")
    assert all(c.status == "pending" for c in case.claims)
    # 舊的協助者動作都拿掉了
    assert not hasattr(actions, "set_manual") and not hasattr(actions, "resolve_legal")
    with pytest.raises(actions.ActionError):
        actions.create_case("helper")
    assert client.post(f"/api/cases/{cid}/claims/P1-lot_no/confirm", json={}).status_code in (404, 405)
    assert client.put(f"/api/cases/{cid}/manual", json={}).status_code in (404, 405)
    assert client.post(f"/api/cases/{cid}/documents").status_code in (404, 405)


def test_c03_unreadable_share_stays_pending(client):
    from app import actions, store
    cid, token = ready_case(client, "C03")
    fv = client.get(f"/api/f/{token}")
    assert "□□" not in fv.text   # 不放地址
    owner2 = next(q for q in fv.json()["questions"] if q["id"] == "C-owner-P2-O1")
    assert {r["label"]: r["value"] for r in owner2["card"]["rows"]}["持分"] == "（看不清）"
    assert owner2["card"]["photo_page"] == 2

    # 看不清的欄位，農民說「一樣」也不能確認
    with pytest.raises(actions.ActionError):
        actions.confirm_claim(store.load(cid), "farmer", "P2-O1-share")
    r = answer_all(client, token)
    assert "第 2 筆地：有字看不清楚，請重拍第 2 張" in r["todo"]
    assert r["documents"] == [{"name": "同意書_1_草稿.docx", "url": r["documents"][0]["url"], "draft": True}]
    case = client.get(f"/api/cases/{cid}").json()
    claims = {c["id"]: c for c in case["claims"]}
    assert claims["P2-O1-share"]["status"] == "pending" and claims["P2-O1-owner"]["status"] == "confirmed"
    assert "未確認：P2-O1-share" in case["missing"] and "無法計算：P2-O1 權利面積（公頃）" in case["missing"]
    path = doc_path(cid, "同意書_1_草稿.docx")
    assert is_draft(path)
    text = table_text(path)
    # 1,000.05 m² → 0.1000；2,499.95 m² → 0.2500（本筆面積可算）；第 2 筆權利面積待確認
    assert text.count("0.1000") == 2 and "0.2500" in text and "待確認" in text
    assert "0005-0001" in text   # 前導零保留


def test_check_different_then_same(client):
    cid, token = ready_case(client, "C01")
    r = answer_all(client, token, **{"C-land-P1": "no"})
    assert r["todo"] == ["第 1 筆地：資料跟謄本不一樣，請重拍第 1 張"]
    assert r["documents"][0]["draft"]
    case = client.get(f"/api/cases/{cid}").json()
    claims = {c["id"]: c for c in case["claims"]}
    assert all(claims[f"P1-{f}"]["status"] == "rejected" for f in ("location", "lot_no", "area_m2"))
    assert "已退回：P1-lot_no" in case["missing"]

    # 改答「我不確定」→ 回到待確認
    r = answer(client, token, "C-land-P1", "unsure").json()
    assert r["todo"] == ["第 1 筆地：你還不確定資料對不對，請再看一次"] and r["documents"][0]["draft"]
    claims = {c["id"]: c for c in client.get(f"/api/cases/{cid}").json()["claims"]}
    assert claims["P1-lot_no"]["status"] == "pending" and claims["P1-lot_no"]["confirmed_by"] is None

    # 再改答「一樣」→ 確認，同意書自動重新產生成正式版
    r = answer(client, token, "C-land-P1", "yes").json()
    assert r["todo"] == [] and r["documents"] == [
        {"name": "同意書_1_正式.docx", "url": r["documents"][0]["url"], "draft": False}]
    events = [e["action"] for e in client.get(f"/api/cases/{cid}").json()["events"]]
    assert "退回欄位" in events and "確認欄位" in events and "欄位改回待確認" in events


def test_farmer_says_not_mine(client):
    cid, token = ready_case(client, "C02")
    r = answer(client, token, "q1", "no").json()
    assert [q["id"] for q in r["questions"]] == ["q1"]
    assert r["todo"] == ["你說這不是你的地，請拍你自己的謄本"]
    assert r["documents"] and all(d["draft"] for d in r["documents"])
    assert answer(client, token, "C-land-P1", "yes").status_code == 400
    case = client.get(f"/api/cases/{cid}").json()
    assert "農民第 1 題回答「不是」" in case["missing"]
    assert case["tasks"] == []


def test_q3_unsure_leaves_category_blank(client):
    cid, token = ready_case(client, "C01")
    r = answer_all(client, token, q3="unsure", period="1")
    assert r["todo"] == [] and not r["documents"][0]["draft"]
    path = doc_path(cid, r["documents"][0]["name"])
    rows = Document(path).tables[0].rows
    assert rows[2].cells[0].text == "" and rows[3].cells[0].text == ""   # 類別留白手寫
    assert rows[2].cells[4].text == f"{ROC}.01.01起\n{ROC}.12.31止"
    assert rows[2].cells[7].text == ""   # 耕作人留白


def test_period_unsure_blocks(client):
    cid, token = ready_case(client, "C01")
    r = answer_all(client, token, period="unsure")
    assert r["todo"] == ["還沒決定要簽幾年"] and r["documents"][0]["draft"]
    assert "實施期間未決定" in client.get(f"/api/cases/{cid}").json()["missing"]


def test_retake_page_reextracts(client):
    """回到拍照：重拍第 2 張 → 清掉擷取與核對答案，其他答案保留；拍好後自動重新讀謄本。"""
    cid, token = ready_case(client, "C03")
    answer_all(client, token)
    fv = client.get(f"/api/f/{token}").json()
    assert fv["retake"] == [2] and fv["documents"]
    assert client.post(f"/api/f/{token}/retake", json={"page": 9}).status_code == 400
    r = client.post(f"/api/f/{token}/retake", json={"page": 2})
    assert r.status_code == 200
    fv = r.json()
    assert fv["stage"] == "collecting" and fv["pages_done"] == [1] and fv["documents"] == [] and fv["report"] is None
    case = client.get(f"/api/cases/{cid}").json()
    assert case["claims"] == [] and not any(q.startswith("C-") for q in case["answers"])
    assert {"q1", "q2", "q3", "period"} <= set(case["answers"])
    assert any(e["action"] == "重拍" for e in case["events"])
    # 舊照片不再提供；重拍後自動重新擷取，回到待核對
    assert client.get(f"/api/f/{token}/photos/2").status_code == 404
    assert upload(client, token, 2, SAMPLES / "C03" / "page2.png").json()["all_pages_done"]
    fv = client.get(f"/api/f/{token}").json()
    assert fv["stage"] == "reviewing" and any(q["id"].startswith("C-") for q in fv["questions"])
    assert client.get(f"/api/f/{token}/photos/2").status_code == 200


def test_frontend_not_cached_stale(client):
    """前端檔案要求瀏覽器每次確認新版，避免展示時跑到舊版頁面。"""
    for path in ("/web/dev.html", "/web/farmer.html", "/web/voice.js"):
        r = client.get(path)
        assert r.status_code == 200 and r.headers["cache-control"] == "no-cache", path
