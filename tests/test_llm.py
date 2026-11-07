"""LLM harness 測試：全部離線（ScriptedProvider），不呼叫真的模型、不花錢。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.llm import harness, providers
from app.llm.base import ImageInput, LLMOutputError
from app.llm.evaluate import score
from app.llm.replay import ScriptedProvider
from app.llm.tasks.extract_transcript import TASK

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "data" / "samples" / "fake-transcripts"


def images(cid: str) -> list[ImageInput]:
    d = SAMPLES / cid
    return [ImageInput("第 1 頁，檔名 photo_page1.jpg", d / "photo_page1.jpg"), ImageInput("第 2 頁，檔名 page2.png", d / "page2.png")]


def model_output(cid: str, *, padded: bool = True, guess_share: str | None = None) -> str:
    """把答案檔轉成「模型會輸出的樣子」：數字前後加星號、檔名換成實際照片。"""
    t = json.loads((SAMPLES / cid / "answer.json").read_text(encoding="utf-8"))
    fname = {"page1.png": "photo_page1.jpg", "page2.png": "page2.png"}
    src = lambda s: {"file": fname[s["file"]], "page": s["page"]}
    pad = (lambda v: f"******{v}平方公尺") if padded else (lambda v: v)
    out = {
        "parcels": [{"parcel_id": p["parcel_id"], "county": p["county"], "township": p["township"], "section": p["section"],
                     "subsection": p.get("subsection", ""), "lot_no": p["lot_no"], "area_raw": pad(p["area_raw"]),
                     "source": src(p["source"])} for p in t["parcels"]],
        "ownerships": [{"parcel_id": o["parcel_id"], "owner": o["owner"], "id_masked": o["id_masked"],
                        "share_raw": (guess_share if guess_share and o["share_raw"] == "待確認" else
                                      (f"{o['share_raw']}*****" if padded and o["share_raw"] != "待確認" else o["share_raw"])),
                        "source": src(o["source"])} for o in t["ownerships"]],
        "pending": [{"field": x["field"], "parcel_id": x["parcel_id"], "note": x.get("note", "")} for x in t.get("pending", [])],
    }
    return json.dumps(out, ensure_ascii=False)


def truth(cid: str) -> dict:
    return json.loads((SAMPLES / cid / "answer.json").read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def tmp_data(tmp_path, monkeypatch):
    monkeypatch.setenv("HACKDAY_DATA", str(tmp_path))


@pytest.mark.parametrize("cid", ["C01", "C02", "C03"])
def test_perfect_output_scores_100(cid):
    r = harness.run(TASK, ScriptedProvider([model_output(cid)]), images(cid))
    rep = score(truth(cid), r.value)
    assert rep["passed"], rep
    assert r.attempts == 1


def test_padding_is_cleaned_and_leading_zeros_kept():
    r = harness.run(TASK, ScriptedProvider([model_output("C03")]), images("C03"))
    p1 = r.value.parcels[0]
    assert p1.area_raw == "1000.05" and p1.lot_no == "0005-0001"
    assert r.value.ownerships[0].share_raw == "全部 1分之1"
    assert r.value.ownerships[1].share_raw == "待確認"


def test_guess_is_caught_by_eval():
    r = harness.run(TASK, ScriptedProvider([model_output("C03", guess_share="全部 1分之1")]), images("C03"))
    rep = score(truth("C03"), r.value)
    assert not rep["passed"] and len(rep["guesses"]) == 1


def test_repair_loop_fixes_bad_first_answer():
    bad = json.loads(model_output("C01"))
    bad["parcels"][0]["lot_no"] = "123-4"            # 格式錯
    bad["ownerships"][0]["parcel_id"] = "P9"         # 對到不存在的土地
    prov = ScriptedProvider([json.dumps(bad, ensure_ascii=False), model_output("C01")])
    r = harness.run(TASK, prov, images("C01"))
    assert r.attempts == 2
    assert "沒有通過檢查" in prov.requests[1].text and "P9" in prov.requests[1].text


def test_gives_up_after_max_attempts():
    with pytest.raises(LLMOutputError):
        harness.run(TASK, ScriptedProvider(["not json", "{}"]), images("C01"))


def test_log_has_no_field_values(tmp_path):
    harness.run(TASK, ScriptedProvider([model_output("C01")]), images("C01"))
    log = next((tmp_path / "llm_logs").glob("*.jsonl")).read_text(encoding="utf-8")
    assert "農民A" not in log and "A12345" not in log and "0123-0004" not in log
    assert '"ok": true' in log


def test_vision_engine_end_to_end_claims_stay_pending(monkeypatch):
    """整條流程用 vision 引擎（假的模型輸出）：擷取結果全部是待確認，模型失敗時轉人工。"""
    monkeypatch.setenv("EXTRACT_ENGINE", "vision")
    from fastapi.testclient import TestClient
    from app.main import app
    client = TestClient(app)

    def run_case(prov):
        r = client.post("/api/cases", json={"sample_id": "C03"}).json()
        cid, token = r["id"], r["farmer_token"]
        with providers.override(prov):
            for page, f in ((1, "photo_page1.jpg"), (2, "page2.png")):
                with open(SAMPLES / "C03" / f, "rb") as fh:
                    client.post(f"/api/f/{token}/photos", data={"page": str(page)}, files={"file": (f, fh, "image/jpeg")})
        return client.get(f"/api/cases/{cid}").json()

    class PerfectModel:
        """依請求裡的照片檔名（上傳後會被改名）產生正確輸出。"""
        name = "perfect"

        def complete(self, req):
            from app.llm.base import LLMResponse
            text = model_output("C03")
            for i, img in enumerate(req.images):
                text = text.replace({0: "photo_page1.jpg", 1: "page2.png"}[i], img.path.name)
            return LLMResponse(text=text, provider=self.name, model="perfect")

    good = run_case(PerfectModel())
    assert good["stage"] == "reviewing"
    assert len(good["claims"]) == 12 and all(c["status"] == "pending" for c in good["claims"])
    share = next(c for c in good["claims"] if c["id"] == "P2-O1-share")
    assert share["ai_value"] == "" and share["note"]          # 看不清 → 空值＋說明，沒有猜

    bad = run_case(ScriptedProvider(["not json", "not json"]))
    assert bad["stage"] == "needs_human"                      # 兩次都失敗 → 轉人工
    assert any("自動處理失敗" in t["text"] for t in bad["tasks"])


def test_fullwidth_stars_and_masked_names_are_normalized():
    out = json.loads(model_output("C01"))
    out["ownerships"][0]["owner"] = "吳＊＊"
    out["ownerships"][0]["id_masked"] = "A12345＊＊＊＊"
    out["ownerships"][1]["owner"] = "吳＊＊"
    out["ownerships"][1]["id_masked"] = "A12345＊＊＊＊"
    r = harness.run(TASK, ScriptedProvider([json.dumps(out, ensure_ascii=False)]), images("C01"))
    assert r.value.ownerships[0].owner == "吳**"
    assert r.value.ownerships[0].id_masked == "A12345****"


def test_blurry_real_world_threshold():
    from app.agents.intake import check
    ok, reason, _, sharp = check(SAMPLES / "C03" / "photo_page1_bad.jpg")
    assert not ok and sharp < 250
    ok, _, _, sharp = check(SAMPLES / "C01" / "photo_page1.jpg")
    assert ok and sharp >= 250
