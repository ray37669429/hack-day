"""端到端測試：用假謄本跑完整流程（照片 → 擷取 → 核對 → 回答 → 確認 → 同意書）。"""
from __future__ import annotations

from pathlib import Path

import pytest
from docx import Document

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "data" / "samples" / "fake-transcripts"


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


def test_bad_photo_is_rejected(client):
    cid, token = start_case(client, "C03")
    r = upload(client, token, 1, SAMPLES / "C03" / "photo_page1_bad.jpg").json()
    assert r["ok"] is False and "暗" in r["reason"]
    assert client.get(f"/api/cases/{cid}").json()["stage"] == "collecting"


def test_full_flow_c03(client):
    cid, token = start_case(client, "C03")
    assert upload(client, token, 1, SAMPLES / "C03" / "photo_page1.jpg").json()["ok"]
    r = upload(client, token, 2, SAMPLES / "C03" / "page2.png").json()
    assert r["ok"] and r["all_pages_done"]

    case = client.get(f"/api/cases/{cid}").json()
    assert case["stage"] == "reviewing"
    claims = {c["id"]: c for c in case["claims"]}
    assert len(claims) == 12
    assert all(c["status"] == "pending" for c in claims.values())
    # 陷阱：同地號不同段、污損的權利範圍
    assert any("相同地號" in f for f in claims["P1-lot_no"]["flags"])
    assert claims["P2-O1-share"]["ai_value"] == "" and claims["P2-O1-share"]["note"]
    assert claims["P1-lot_no"]["ai_value"] == "0005-0001"  # 前導零保留

    # 農民端看不到身分證號
    fv = client.get(f"/api/f/{token}").text
    assert "C34567" not in fv and "0005-0001" in fv

    # 農民回答（語音要附原文）
    assert client.post(f"/api/f/{token}/answers", json={"question": "q1", "value": "yes", "channel": "voice"}).status_code == 400
    assert client.post(f"/api/f/{token}/answers", json={"question": "q1", "value": "yes", "channel": "voice", "transcript": "著"}).status_code == 200
    assert client.post(f"/api/f/{token}/answers", json={"question": "q2", "value": "maybe"}).status_code == 400
    client.post(f"/api/f/{token}/answers", json={"question": "q2", "value": "other"})
    client.post(f"/api/f/{token}/answers", json={"question": "q3", "value": "承租"})

    # 還沒確認 → 草稿
    d = client.post(f"/api/cases/{cid}/documents").json()
    assert d["draft"] and all("草稿" in f for f in d["files"])

    # 看不清的欄位不能空值確認
    assert client.post(f"/api/cases/{cid}/claims/P2-O1-share/confirm", json={}).status_code == 400
    client.post(f"/api/cases/{cid}/claims/P2-O1-share/confirm", json={"value": "全部 1分之1"})
    for c in claims:
        if c != "P2-O1-share":
            assert client.post(f"/api/cases/{cid}/claims/{c}/confirm", json={}).status_code == 200
    manual = {"area_ha": {"P1": "0.1000", "P2": "0.2500"}, "right_area_ha": {"P1-O1": "0.1000", "P2-O1": "0.2500"},
              "period": "116.01.01起\n118.12.31止", "cultivator": "農民D D45678****"}
    assert client.put(f"/api/cases/{cid}/manual", json=manual).status_code == 200

    d = client.post(f"/api/cases/{cid}/documents").json()
    assert d["missing"] == [] and not d["draft"]
    assert d["files"] == ["同意書_1_正式.docx"]
    r = client.get(f"/api/cases/{cid}/documents/{d['files'][0]}")
    assert r.status_code == 200
    path = Path(client.app and __import__("os").environ["HACKDAY_DATA"]) / "cases" / cid / "documents" / d["files"][0]
    doc = Document(path)
    text = "\n".join(c.text for t in doc.tables for row in t.rows for c in row.cells)
    assert "示範一段" in text and "0005-0001" in text and "農民D" in text
    assert not any("草稿" in p.text for s in doc.sections for p in s.header.paragraphs)


def test_agent_cannot_confirm(client):
    from app import actions, store
    cid, token = start_case(client, "C01")
    upload(client, token, 1, SAMPLES / "C01" / "photo_page1.jpg")
    upload(client, token, 2, SAMPLES / "C01" / "page2.png")
    case = store.load(cid)
    for actor in ("agent:extract", "agent:check", "agent:triage", "agent:document", "farmer"):
        with pytest.raises(actions.ActionError):
            actions.confirm_claim(case, actor, "P1-lot_no")


def test_farmer_says_not_mine_forces_draft(client):
    cid, token = start_case(client, "C02")
    upload(client, token, 1, SAMPLES / "C02" / "photo_page1.jpg")
    upload(client, token, 2, SAMPLES / "C02" / "page2.png")
    client.post(f"/api/f/{token}/answers", json={"question": "q1", "value": "no"})
    case = client.get(f"/api/cases/{cid}").json()
    assert any("不是他的地" in t["text"] for t in case["tasks"])
    assert any("第 1 題" in m for m in case["missing"])
    # C02 共有：兩位所有權人 → 兩份同意書
    d = client.post(f"/api/cases/{cid}/documents").json()
    assert len(d["files"]) == 2 and d["draft"]
