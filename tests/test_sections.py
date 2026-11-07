"""段名比對官方清單（app/refdata/sections.py）。只回報，不改值。"""
from __future__ import annotations

import pytest

from app.refdata import sections
from app.refdata.sections import DATA_PATH, lookup

needs_data = pytest.mark.skipif(not DATA_PATH.exists(), reason="缺 data/refdata/land_sections.csv")


@needs_data
def test_real_section_found():
    r = lookup("雲林縣", "東勢鄉", "西安段")
    assert r.found and not r.skipped
    assert r.section_code == "1108"


@needs_data
def test_misread_section_flagged_with_suggestion():
    r = lookup("雲林縣", "東勢鄉", "四安段")
    assert not r.found
    assert r.suggestions[0] == "西安段"
    assert 1 <= len(r.suggestions) <= 3
    assert "四安段" in r.message and "西安段" in r.message


@needs_data
@pytest.mark.parametrize("county,township", [
    ("雲林縣", "東勢鄉"), ("雲林縣", " 東勢鄉　"), ("雲林縣", "東勢"),
    ("雲林縣", "台西地政事務所"), ("雲林縣", ""), ("雲林縣", "不存在鄉"),
])
def test_township_lenient(county, township):
    assert lookup(county, township, "西安段").found


@needs_data
def test_tai_variants_and_fullwidth():
    for county in ("臺北市", "台北市", "台北市　"):
        assert lookup(county, "松山區", "西松段", "一小段").found
        assert lookup(county, "松山區", "西松段一小段").found
    # 原始資料寫「台南市」，輸入「臺南市」也要找得到
    assert lookup("臺南市", "新營區", "新營段").found
    assert lookup("台南市", "新營區", "新營段").found


@needs_data
def test_missing_or_wrong_subsection_flagged():
    r = lookup("臺北市", "松山區", "西松段")
    assert not r.found and "西松段一小段" in r.suggestions
    assert not lookup("臺北市", "松山區", "西松段", "九小段").found


@needs_data
@pytest.mark.parametrize("args", [
    ("範例縣", "試驗鄉", "示範段"), ("範例縣", "試驗鄉", "示範一段"),
    ("範例縣", "試驗鄉", "測試段", "北小段"), ("範例縣", "", "測試段北小段"),
])
def test_fictional_sections_not_found_without_error(args):
    r = lookup(*args)
    assert r.found is False and r.message


def test_missing_data_file_skips(tmp_path):
    r = lookup("雲林縣", "東勢鄉", "四安段", data_path=tmp_path / "nope.csv")
    assert r.found and r.skipped and "略過" in r.message


def test_tiny_fixture(tmp_path):
    """虛構資料的小檔（不是官方資料），驗證不依賴真實清單也能跑。"""
    p = tmp_path / "fixture.csv"
    p.write_text(
        "county,township,office,office_code,town_code,section,subsection,section_code,comment\n"
        "範例縣,試驗鄉,範例地政事務所,ZZ,01,示範,,0001,\n"
        "範例縣,試驗鄉,範例地政事務所,ZZ,01,示範一,,0002,\n"
        "範例縣,試驗鄉,範例地政事務所,ZZ,01,測試,北,0003,\n",
        encoding="utf-8",
    )
    assert lookup("範例縣", "試驗鄉", "示範段", data_path=p).found
    assert lookup("範例縣", "試驗鄉", "測試段", "北小段", data_path=p).found
    r = lookup("範例縣", "試驗鄉", "示範二段", data_path=p)
    assert not r.found and r.suggestions[0] == "示範一段"
    assert lookup("範例縣", "試驗鄉", "", data_path=p).skipped
    sections._cache.clear()


def test_check_agent_flags_misread_section():
    """核對 agent 整合：四安段被標警示，值不被改動。"""
    from app import actions
    from app.agents import check
    from app.models import Case, ExOwnership, ExParcel, Extraction, Source
    src = Source(file="p.jpg", page=1)
    ex = Extraction(parcels=[ExParcel(parcel_id="P1", county="雲林縣", township="東勢鄉", section="四安段",
                                      lot_no="0123-0004", area_raw="2022.05", source=src)],
                    ownerships=[ExOwnership(parcel_id="P1", owner="農民A", id_masked="A12345****",
                                            share_raw="全部 1分之1", source=src)])
    case = Case(id="T1", farmer_token="x")
    actions.add_extraction(case, "agent:extract", ex)
    check.run(case, ex)
    loc = next(c for c in case.claims if c.id == "P1-location")
    assert loc.value == "雲林縣東勢鄉四安段"
    assert any("西安段" in f for f in loc.flags)
