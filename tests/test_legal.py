"""法律注意事項：固定規則 → 給農民的固定範本題目 ＋ 給協助者的待辦。系統不下法律結論。"""
from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "data" / "samples" / "fake-transcripts"

SAY = {
    "q1": "這幾筆，是你的地嗎？請說，是，或是，不是。",
    "q2": "這些地，是誰在種？是你自己，還是別人？",
    "q3": "用什麼方式給人種？承租、託耕、輪耕，還是分耕？",
}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("HACKDAY_DATA", str(tmp_path))
    monkeypatch.delenv("EXTRACT_ENGINE", raising=False)
    monkeypatch.delenv("HELPER_NAME", raising=False)
    monkeypatch.delenv("HELPER_PHONE", raising=False)
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)


def upload(client, token, page, path):
    with open(path, "rb") as f:
        return client.post(f"/api/f/{token}/photos", data={"page": str(page)}, files={"file": (path.name, f, "image/jpeg")})


def ready_case(client, sample):
    r = client.post("/api/cases", json={"sample_id": sample}).json()
    cid, token = r["id"], r["farmer_token"]
    upload(client, token, 1, SAMPLES / sample / "photo_page1.jpg")
    upload(client, token, 2, SAMPLES / sample / "page2.png")
    assert client.get(f"/api/cases/{cid}").json()["stage"] == "reviewing"
    return cid, token


def answer(client, token, q, v):
    return client.post(f"/api/f/{token}/answers", json={"question": q, "value": v})


def test_c01_has_no_legal_questions(client):
    cid, token = ready_case(client, "C01")
    fv = client.get(f"/api/f/{token}").json()
    qs = fv["questions"]
    assert [q["id"] for q in qs] == ["q1", "q2", "q3"]
    assert {q["id"]: q["say"] for q in qs} == SAY
    assert [q["kind"] for q in qs] == ["yesno", "who", "cat"]
    assert [o["value"] for o in qs[2]["options"]][-1] == "unsure"
    assert qs[0]["options"][0] == {"value": "yes", "label": "是"}
    assert not any(q["legal"] for q in qs)
    # 土地、照片、協助者
    assert fv["lands"][0] == {"pid": "P1", "location": "範例縣試驗鄉示範段", "lot_no": "0123-0004",
                              "area_raw": "1234.56", "area_unit": "平方公尺", "page": 1}
    assert [p["page"] for p in fv["photos"]] == [1, 2]
    assert fv["photos"][0]["url"] == f"/api/f/{token}/photos/1"
    assert fv["helper"] == {"name": "協助者", "phone": ""}
    case = client.get(f"/api/cases/{cid}").json()
    assert case["legal"] == []
    assert not any("法律" in m for m in case["missing"])


def test_c02_coowner(client):
    from app import actions, store
    cid, token = ready_case(client, "C02")
    r = client.get(f"/api/f/{token}")
    assert "農民B" not in r.text and "B23456" not in r.text and "△△" not in r.text
    q = next(q for q in r.json()["questions"] if q["id"] == "L-coowner")
    assert q["legal"] and q["kind"] == "yesno" and q["why"] == "因為這筆地有好幾個地主"
    assert [o["label"] for o in q["options"]] == ["知道", "不知道", "我不確定"]

    helper = client.get(f"/api/cases/{cid}").json()
    issue = next(i for i in helper["legal"] if i["id"] == "coowner")
    assert issue["reference"].endswith("（待法律專業確認）")
    assert issue["question_id"] == "L-coowner" and issue["answer_label"] is None and not issue["resolved"]
    assert "農民還沒回答：這筆地還有其他地主，他們知道你要簽同意書嗎？" in helper["missing"]
    assert any(m.startswith("法律注意事項未處理：共有土地") for m in helper["missing"])

    # 回答（不在選項內的值不收）
    assert answer(client, token, "L-coowner", "other").status_code == 400
    r = answer(client, token, "L-coowner", "no")
    assert r.status_code == 200 and r.json()["answers"]["L-coowner"] == "不知道"
    assert "農民B" not in r.text and "B23456" not in r.text
    helper = client.get(f"/api/cases/{cid}").json()
    assert any("不知道" in t["text"] and "共有土地" in t["text"] for t in helper["tasks"])
    assert next(i for i in helper["legal"] if i["id"] == "coowner")["answer_label"] == "不知道"
    assert not any(m.startswith("農民還沒回答：這筆地") for m in helper["missing"])
    assert any(m.startswith("法律注意事項未處理：共有土地") for m in helper["missing"])

    # 農民與 agent 不能處理；協助者可以
    case = store.load(cid)
    for actor in ("farmer", "agent:triage", "agent:check", "agent:document", "system"):
        with pytest.raises(actions.ActionError):
            actions.resolve_legal(case, actor, "coowner", "x")
    assert client.post(f"/api/cases/{cid}/legal/lease/resolve", json={"note": "x"}).status_code == 404
    r = client.post(f"/api/cases/{cid}/legal/coowner/resolve", json={"note": "已聯絡另一位共有人，會一起簽"})
    assert r.status_code == 200
    issue = next(i for i in r.json()["legal"] if i["id"] == "coowner")
    assert issue["resolved"] and issue["note"] == "已聯絡另一位共有人，會一起簽"
    assert not any("法律注意事項" in m for m in r.json()["missing"])


def test_legal_question_not_active_is_rejected(client):
    _, token = ready_case(client, "C01")
    assert answer(client, token, "L-coowner", "yes").status_code == 400
    assert answer(client, token, "L-lease", "yes").status_code == 400


def test_other_cultivator_adds_lease_question(client):
    cid, token = ready_case(client, "C01")
    r = answer(client, token, "q2", "self").json()
    assert [q["id"] for q in r["questions"]] == ["q1", "q2", "q3"]
    r = answer(client, token, "q2", "other").json()
    lease = next(q for q in r["questions"] if q["id"] == "L-lease")
    assert lease["kind"] == "have" and lease["legal"]
    assert lease["say"] == "你跟種田的人，有沒有簽租約？請說，有，或是，沒有。"
    assert [(o["value"], o["label"]) for o in lease["options"]] == [("yes", "有"), ("no", "沒有"), ("unsure", "我不確定")]
    assert answer(client, token, "L-lease", "unsure").json()["answers"]["L-lease"] == "我不確定"
    helper = client.get(f"/api/cases/{cid}").json()
    issue = next(i for i in helper["legal"] if i["id"] == "lease")
    assert "三七五" in issue["reference"] and issue["reference"].endswith("（待法律專業確認）")
    assert any("租約" in t["text"] for t in helper["tasks"])


def test_unclear_share_is_helper_only(client):
    cid, token = ready_case(client, "C03")
    assert not any(q["legal"] for q in client.get(f"/api/f/{token}").json()["questions"])
    helper = client.get(f"/api/cases/{cid}").json()
    issue = next(i for i in helper["legal"] if i["id"] == "unclear-share")
    assert issue["question_id"] is None and "P2-O1-share" in issue["detail"]
    assert issue["reference"].endswith("（待法律專業確認）")
    # 協助者對照原件確認後就不再是「看不清」
    client.post(f"/api/cases/{cid}/claims/P2-O1-share/confirm", json={"value": "全部 1分之1"})
    assert not any(i["id"] == "unclear-share" for i in client.get(f"/api/cases/{cid}").json()["legal"])


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
    # 不合格的照片不提供
    assert client.get(f"/api/f/{token}/photos/1").status_code == 404
    # 打不開的檔案 → checks 為空
    r = client.post(f"/api/f/{token}/photos", data={"page": "1"}, files={"file": ("x.jpg", b"not an image", "image/jpeg")})
    assert r.json()["checks"] == []


# ───── 選題：打分、上限、追問

def legal_ids(questions):
    return [q["id"] for q in questions if q["legal"]]


def test_ranked_by_score_and_capped(client, monkeypatch):
    cid, token = ready_case(client, "C02")              # 共有 → coowner（55）
    answer(client, token, "q2", "other")
    r = answer(client, token, "q3", "承租").json()        # 承租 → lease（90）排第一
    assert legal_ids(r["questions"]) == ["L-lease", "L-coowner"]
    legal = client.get(f"/api/cases/{cid}").json()["legal"]
    assert [i["id"] for i in legal] == ["lease", "coowner"]
    assert legal[0]["score"] == 90 and "承租" in legal[0]["score_reason"]
    assert all(i["asked"] for i in legal)

    # 上限 1 題：只問分數最高的；沒問的仍要協助者處理，並寫出原因
    monkeypatch.setenv("LEGAL_MAX_FARMER_QUESTIONS", "1")
    assert legal_ids(client.get(f"/api/f/{token}").json()["questions"]) == ["L-lease"]
    assert answer(client, token, "L-coowner", "yes").status_code == 400
    helper = client.get(f"/api/cases/{cid}").json()
    coowner = next(i for i in helper["legal"] if i["id"] == "coowner")
    assert not coowner["asked"] and "沒有問農民" in coowner["selection"]
    assert any(m.startswith("法律注意事項未處理：共有土地") for m in helper["missing"])
    assert not any("其他地主" in m for m in helper["missing"])


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
    fu = r["questions"][-1]
    assert fu["why"] == "因為你說有簽租約" and fu["legal"]
    r = answer(client, token, "L-lease-375", "yes").json()
    assert r["answers"]["L-lease-375"] == "是"
    helper = client.get(f"/api/cases/{cid}").json()
    lease = next(i for i in helper["legal"] if i["id"] == "lease")
    assert lease["followup"] == {"question_id": "L-lease-375", "text": "這份租約，是三七五租約嗎？", "answer_label": "是"}
    assert any("三七五" in t["text"] for t in helper["tasks"])
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
    assert len(legal_ids(r["questions"])) <= 3
