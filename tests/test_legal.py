"""法律注意事項：固定規則 → 給農民的固定範本題目；回答了就算處理過，風險寫進同意書備註。系統不下法律結論。"""
from __future__ import annotations

from pathlib import Path

import pytest
from docx import Document

from test_flow import SAMPLES, answer, answer_all, doc_path, ready_case, upload


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("HACKDAY_DATA", str(tmp_path))
    monkeypatch.delenv("EXTRACT_ENGINE", raising=False)
    monkeypatch.delenv("LEGAL_MAX_FARMER_QUESTIONS", raising=False)
    monkeypatch.delenv("LEGAL_MAX_TOTAL", raising=False)
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)


def legal_ids(questions):
    return [q["id"] for q in questions if q["legal"]]


def notes(path: Path) -> list[str]:
    """同意書每一列的備註欄（第 10 欄）。"""
    rows = Document(path).tables[0].rows[2:]
    return [r.cells[9].text for r in rows if r.cells[1].text]


def test_c01_has_no_legal_questions(client):
    cid, token = ready_case(client, "C01")
    fv = client.get(f"/api/f/{token}").json()
    assert legal_ids(fv["questions"]) == []
    assert "helper" not in fv
    assert fv["lands"][0] == {"pid": "P1", "location": "範例縣試驗鄉示範段", "lot_no": "0123-0004",
                              "area_raw": "1234.56", "area_unit": "平方公尺", "page": 1}
    assert [p["page"] for p in fv["photos"]] == [1, 2]
    assert fv["photos"][0]["url"] == f"/api/f/{token}/photos/1"
    case = client.get(f"/api/cases/{cid}").json()
    assert case["legal"] == []


def test_c02_coowner_answered_is_handled_and_noted(client):
    cid, token = ready_case(client, "C02")
    r = client.get(f"/api/f/{token}")
    assert "△△" not in r.text and "□□" not in r.text   # 不放地址
    q = next(q for q in r.json()["questions"] if q["id"] == "L-coowner")
    assert q["legal"] and q["kind"] == "yesno" and q["why"] == "因為這筆地有好幾個地主" and q["card"] is None
    assert [o["label"] for o in q["options"]] == ["知道", "不知道", "我不確定"]
    assert "協助者" not in r.text

    admin = client.get(f"/api/cases/{cid}").json()
    issue = next(i for i in admin["legal"] if i["id"] == "coowner")
    assert issue["reference"].endswith("（待法律專業確認）")
    assert issue["question_id"] == "L-coowner" and issue["answer_label"] is None and not issue["handled"]

    assert answer(client, token, "L-coowner", "other").status_code == 400
    r = answer(client, token, "L-coowner", "no").json()
    assert r["answers"]["L-coowner"] == "不知道"
    assert legal_ids(r["questions"]) == ["L-coowner", "L-coowner-reach"]

    r = answer_all(client, token, **{"L-coowner-reach": "yes"})
    # 回答了就算處理過：不擋正式版
    assert r["todo"] == [] and [d["draft"] for d in r["documents"]] == [False, False]
    admin = client.get(f"/api/cases/{cid}").json()
    assert admin["missing"] == [] and admin["tasks"] == []
    assert next(i for i in admin["legal"] if i["id"] == "coowner")["handled"]

    # 共有：兩位所有權人各一份；3,210.00 m² → 0.3210，持分 2分之1 → 0.1605
    for d in r["documents"]:
        path = doc_path(cid, d["name"])
        text = "\n".join(c.text for row in Document(path).tables[0].rows for c in row.cells)
        assert "0.3210" in text and "0.1605" in text
        assert notes(path) == ["共有土地：需其他共有人同意；其他共有人尚不知情"]


def test_unanswered_legal_question_blocks(client):
    cid, token = ready_case(client, "C02")
    admin = client.get(f"/api/cases/{cid}").json()
    assert "農民還沒回答：這筆地還有其他地主，他們知道你要簽同意書嗎？" in admin["missing"]
    answer(client, token, "L-coowner", "unsure")
    admin = client.get(f"/api/cases/{cid}").json()
    assert not any("其他地主" in m for m in admin["missing"])


def test_legal_question_not_active_is_rejected(client):
    _, token = ready_case(client, "C01")
    assert answer(client, token, "L-coowner", "yes").status_code == 400
    assert answer(client, token, "L-lease", "yes").status_code == 400


def test_other_cultivator_adds_lease_question(client):
    cid, token = ready_case(client, "C01")
    r = answer(client, token, "q2", "self").json()
    assert legal_ids(r["questions"]) == []
    r = answer(client, token, "q2", "other").json()
    ids = [q["id"] for q in r["questions"]]
    assert ids.index("q3") < ids.index("L-lease") < ids.index("period")   # 法律題在 q3 之後、實施期間之前
    lease = next(q for q in r["questions"] if q["id"] == "L-lease")
    assert lease["kind"] == "have" and lease["legal"]
    assert lease["say"] == "你跟種田的人，有沒有簽租約？請說，有，或是，沒有。"
    assert [(o["value"], o["label"]) for o in lease["options"]] == [("yes", "有"), ("no", "沒有"), ("unsure", "我不確定")]
    assert answer(client, token, "L-lease", "unsure").json()["answers"]["L-lease"] == "我不確定"
    issue = next(i for i in client.get(f"/api/cases/{cid}").json()["legal"] if i["id"] == "lease")
    assert "三七五" in issue["reference"] and issue["reference"].endswith("（待法律專業確認）")


@pytest.mark.parametrize("answers, note", [
    ({"L-lease": "no"}, ""),
    ({"L-lease": "yes", "L-lease-375": "no"}, "有耕地租約"),
    ({"L-lease": "yes", "L-lease-375": "yes"}, "三七五租約"),
    ({"L-lease": "yes", "L-lease-375": "unsure"}, "租約情況未確認"),
    ({"L-lease": "unsure"}, "租約情況未確認"),
])
def test_lease_remarks_in_document(client, answers, note):
    cid, token = ready_case(client, "C01")
    r = answer_all(client, token, q2="other", **answers)
    assert r["todo"] == [] and not r["documents"][0]["draft"]   # 不確定也不擋
    assert notes(doc_path(cid, r["documents"][0]["name"])) == [note, note]


def test_remarks_follow_current_answers(client):
    from app import store
    from app.agents import legal
    cid, token = ready_case(client, "C01")
    answer_all(client, token, q2="other", **{"L-lease": "yes", "L-lease-375": "yes"})
    assert legal.remarks_for(store.load(cid), "P1") == [legal.REMARK_LEASE_375]
    answer(client, token, "q2", "self")   # 改成自己種 → 租約題不再有效，備註也拿掉
    assert legal.remarks_for(store.load(cid), "P1") == []


def test_unclear_share_not_asked(client):
    cid, token = ready_case(client, "C03")
    assert legal_ids(client.get(f"/api/f/{token}").json()["questions"]) == []
    issue = next(i for i in client.get(f"/api/cases/{cid}").json()["legal"] if i["id"] == "unclear-share")
    assert issue["question_id"] is None and "P2-O1-share" in issue["detail"] and not issue["asked"]
    assert issue["reference"].endswith("（待法律專業確認）")


def test_photo_served_only_to_own_token(client):
    r = client.post("/api/cases", json={"sample_id": "C01"}).json()
    token = r["farmer_token"]
    other = client.post("/api/cases", json={"sample_id": "C02"}).json()["farmer_token"]
    up = upload(client, token, 1, SAMPLES / "C01" / "photo_page1.jpg").json()
    assert up["ok"]
    assert [c["id"] for c in up["checks"]] == ["bright", "sharp"]
    assert all(c["ok"] for c in up["checks"]) and up["checks"][0]["text"] == "夠亮"

    got = client.get(f"/api/f/{token}/photos/1")
    assert got.status_code == 200
    assert got.content == (SAMPLES / "C01" / "photo_page1.jpg").read_bytes()
    assert client.get(f"/api/f/{other}/photos/1").status_code == 404
    assert client.get(f"/api/f/not-a-token/photos/1").status_code == 404
    assert client.get(f"/api/f/{token}/photos/2").status_code == 404
    assert client.get(f"/api/f/{token}/photos/..%2Fcase.json").status_code in (404, 422)


def test_bad_photo_checks(client):
    token = client.post("/api/cases", json={"sample_id": "C03"}).json()["farmer_token"]
    up = upload(client, token, 1, SAMPLES / "C03" / "photo_page1_bad.jpg").json()
    assert not up["ok"]
    assert {c["id"]: c["text"] for c in up["checks"]} == {"bright": "有點暗", "sharp": "有點糊"}
    assert client.get(f"/api/f/{token}/photos/1").status_code == 404
    r = client.post(f"/api/f/{token}/photos", data={"page": "1"}, files={"file": ("x.jpg", b"not an image", "image/jpeg")})
    assert r.json()["checks"] == []


# ───── 選題：打分、上限、追問

def test_ranked_by_score_and_capped(client, monkeypatch):
    cid, token = ready_case(client, "C02")              # 共有 → coowner（55）
    answer(client, token, "q2", "other")
    r = answer(client, token, "q3", "承租").json()        # 承租 → lease（90）排第一
    assert legal_ids(r["questions"]) == ["L-lease", "L-coowner"]
    legal = client.get(f"/api/cases/{cid}").json()["legal"]
    assert [i["id"] for i in legal] == ["lease", "coowner"]
    assert legal[0]["score"] == 90 and "承租" in legal[0]["score_reason"]
    assert all(i["asked"] for i in legal)

    # 上限 1 題：只問分數最高的；沒問的不擋正式版，但同意書備註照寫
    monkeypatch.setenv("LEGAL_MAX_FARMER_QUESTIONS", "1")
    assert legal_ids(client.get(f"/api/f/{token}").json()["questions"]) == ["L-lease"]
    assert answer(client, token, "L-coowner", "yes").status_code == 400
    admin = client.get(f"/api/cases/{cid}").json()
    coowner = next(i for i in admin["legal"] if i["id"] == "coowner")
    assert not coowner["asked"] and "沒有問農民" in coowner["selection"] and coowner["handled"]
    assert not any("其他地主" in m for m in admin["missing"])
    r = answer_all(client, token, q2="other", q3="承租")
    assert r["todo"] == []
    assert notes(doc_path(cid, r["documents"][0]["name"])) == ["共有土地：需其他共有人同意"]


def test_answered_question_stays_selected(client, monkeypatch):
    monkeypatch.setenv("LEGAL_MAX_FARMER_QUESTIONS", "1")
    cid, token = ready_case(client, "C02")
    assert legal_ids(client.get(f"/api/f/{token}").json()["questions"]) == ["L-coowner"]
    answer(client, token, "L-coowner", "yes")
    answer(client, token, "q2", "other")
    r = answer(client, token, "q3", "承租").json()       # lease 分數較高，但已回答的 coowner 不會被換掉
    assert legal_ids(r["questions"]) == ["L-coowner"]


def test_followup_only_after_risky_answer(client):
    cid, token = ready_case(client, "C01")
    answer(client, token, "q2", "other")
    r = answer(client, token, "L-lease", "no").json()
    assert legal_ids(r["questions"]) == ["L-lease"]
    r = answer(client, token, "L-lease", "yes").json()
    assert legal_ids(r["questions"]) == ["L-lease", "L-lease-375"]
    fu = next(q for q in r["questions"] if q["id"] == "L-lease-375")
    assert fu["why"] == "因為你說有簽租約" and fu["legal"]
    r = answer(client, token, "L-lease-375", "yes").json()
    assert r["answers"]["L-lease-375"] == "是"
    lease = next(i for i in client.get(f"/api/cases/{cid}").json()["legal"] if i["id"] == "lease")
    assert lease["followup"] == {"question_id": "L-lease-375", "text": "這份租約，是三七五租約嗎？", "answer_label": "是"}
    # 改答「沒有」→ 追問與它的答案都不再出現
    r = answer(client, token, "L-lease", "no").json()
    assert legal_ids(r["questions"]) == ["L-lease"] and "L-lease-375" not in r["answers"]


def test_total_cap_includes_followups(client):
    cid, token = ready_case(client, "C02")
    answer(client, token, "q2", "other")
    answer(client, token, "q3", "承租")
    answer(client, token, "L-lease", "yes")                # 追問 375 → 3 題
    r = answer(client, token, "L-coowner", "no").json()    # 共有追問會是第 4 題 → 超過總數上限 3
    assert legal_ids(r["questions"]) == ["L-lease", "L-lease-375", "L-coowner"]
