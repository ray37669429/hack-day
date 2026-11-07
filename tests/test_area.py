"""面積換算：平方公尺 → 公頃（小數 4 位、四捨五入），權利面積 = 四捨五入後的本筆面積 × 持分。"""
from __future__ import annotations

from fractions import Fraction

import pytest

from app.agents.area import parse_share, right_ha, to_ha


@pytest.mark.parametrize("m2, ha", [
    ("1234.56", "0.1235"),     # 0.123456
    ("1,234.56", "0.1235"),    # 千分位逗號
    ("2345.67", "0.2346"),     # 0.234567
    ("1234.5", "0.1235"),      # 0.12345 剛好一半 → 進位（不是銀行家捨入的 0.1234）
    ("12345.5", "1.2346"),     # 1.23455 → 進位
    ("1,000.05", "0.1000"),    # 0.100005：第 5 位是 0 → 捨去
    ("2,499.95", "0.2500"),    # 0.249995 → 進位
    ("3210.00", "0.3210"),
    ("１２３４．５６", "0.1235"),  # 全形數字
    ("0", "0.0000"),
])
def test_to_ha(m2, ha):
    assert to_ha(m2) == ha


@pytest.mark.parametrize("bad", ["", "待確認", "abc", "-5", "1.2.3", "12 34a"])
def test_to_ha_unreadable(bad):
    assert to_ha(bad) is None


@pytest.mark.parametrize("text, share", [
    ("2分之1", Fraction(1, 2)),
    ("1分之1", Fraction(1)),
    ("全部", Fraction(1)),
    ("全部 1分之1", Fraction(1)),
    (" 3 分之 2 ", Fraction(2, 3)),
    ("*2分之1*", Fraction(1, 2)),
    ("4分之2", Fraction(1, 2)),
])
def test_parse_share(text, share):
    assert parse_share(text) == share


@pytest.mark.parametrize("bad", ["", "待確認", "garbage", "1/2", "0分之1", "2分之0", "2分之3", "分之1", "部分"])
def test_parse_share_unreadable(bad):
    assert parse_share(bad) is None


def test_right_ha():
    assert right_ha("0.3210", Fraction(1, 2)) == "0.1605"
    assert right_ha("0.1235", Fraction(1)) == "0.1235"
    assert right_ha("0.0003", Fraction(1, 2)) == "0.0002"   # 0.00015 → 進位
    assert right_ha("0.1235", Fraction(1, 3)) == "0.0412"   # 0.041166…
    assert right_ha("abc", Fraction(1, 2)) is None
    assert right_ha("0.1235", None) is None


def test_right_ha_uses_rounded_area():
    # 1234.56 m² → 0.1235 ha（先四捨五入），× 1/2 = 0.06175 → 0.0618
    # （若用沒四捨五入的 0.123456 × 1/2 = 0.061728 → 0.0617，規則不是這樣）
    assert right_ha(to_ha("1234.56"), parse_share("2分之1")) == "0.0618"
