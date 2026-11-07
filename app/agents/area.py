"""面積換算（純函式，不改資料）。

規則（已確認）：
- 本筆面積（公頃）= 面積（平方公尺）÷ 10000，四捨五入到小數 4 位。
- 權利面積（公頃）= 四捨五入後的本筆面積 × 持分，再四捨五入到小數 4 位。
- 只能用「已確認」的值來算；呼叫端負責只傳已確認的值。讀不懂就回傳 None（= 待確認），不猜。
"""
from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction

PLACES = Decimal("0.0001")
_NUM = re.compile(r"\d+(\.\d+)?")
_SHARE = re.compile(r"(?:全部)?(\d+)分之(\d+)")
_STRIP = str.maketrans({" ": "", "　": "", "\t": "", "*": "", "＊": "", ",": "", "，": ""})
_FULLWIDTH = str.maketrans("０１２３４５６７８９．", "0123456789.")


def _clean(text: str) -> str:
    return (text or "").translate(_FULLWIDTH).translate(_STRIP)


def _round(x: Decimal) -> str:
    return str(x.quantize(PLACES, rounding=ROUND_HALF_UP))


def to_ha(area_m2: str) -> str | None:
    """「1,234.56」（平方公尺）→「0.1235」（公頃）。不是數字回傳 None。"""
    text = _clean(area_m2)
    if not _NUM.fullmatch(text):
        return None
    return _round(Decimal(text) / Decimal(10000))


def parse_share(text: str) -> Fraction | None:
    """權利範圍原文 → 持分。「2分之1」→ 1/2；「1分之1」「全部」「全部 1分之1」→ 1。讀不懂回傳 None。"""
    t = _clean(text)
    if t == "全部":
        return Fraction(1)
    m = _SHARE.fullmatch(t)
    if not m:
        return None
    den, num = int(m.group(1)), int(m.group(2))
    if den == 0 or num == 0 or num > den:
        return None
    return Fraction(num, den)


def right_ha(area_ha: str, share: Fraction) -> str | None:
    """權利面積（公頃）= 本筆面積（公頃，已四捨五入）× 持分，四捨五入到小數 4 位。"""
    text = _clean(area_ha)
    if share is None or not _NUM.fullmatch(text):
        return None
    return _round(Decimal(text) * share.numerator / share.denominator)
