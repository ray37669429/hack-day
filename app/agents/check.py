"""③ 核對 agent：固定規則檢查，只加註警示，不改值、不確認。"""
from __future__ import annotations

import re
from fractions import Fraction

from .. import actions
from ..models import Case, ClaimField, Extraction
from ..refdata.sections import lookup

ACTOR = "agent:check"
LOT_RE = re.compile(r"^\d{4}-\d{4}$")
SHARE_RE = re.compile(r"(\d+)\s*分之\s*(\d+)")


def parse_share(text: str) -> Fraction | None:
    """「2分之1」→ 1/2；「全部 1分之1」→ 1。讀不出來回傳 None。"""
    m = SHARE_RE.search(text or "")
    if not m or int(m.group(1)) == 0:
        return None
    return Fraction(int(m.group(2)), int(m.group(1)))


def run(case: Case, ex: Extraction | None = None) -> list[str]:
    """ex：擷取 agent 的原始結果（有縣、鄉、段分開的欄位），用來比對官方段名清單。"""
    found: list[str] = []
    for p in (ex.parcels if ex else []):
        r = lookup(p.county, p.township, p.section, p.subsection)
        if not r.found and not r.skipped:
            actions.add_flag(case, ACTOR, f"{p.parcel_id}-location", r.message)
            found.append(f"{p.parcel_id} 段名不在官方清單")
    lots = [c for c in case.claims if c.field == ClaimField.lot_no]
    for c in lots:
        if not LOT_RE.match(c.ai_value):
            actions.add_flag(case, ACTOR, c.id, "地號格式不是 0000-0000")
            found.append(f"{c.target} 地號格式異常")
        if any(o is not c and o.ai_value == c.ai_value for o in lots):
            actions.add_flag(case, ACTOR, c.id, "另一筆土地有相同地號，請核對段名")
            found.append(f"{c.target} 與其他土地地號相同")
    for c in case.claims:
        if not c.ai_value:
            actions.add_flag(case, ACTOR, c.id, "看不清，需人工填入")
            found.append(f"{c.id} 看不清")
    for p in case.parcels:
        shares = [c for c in case.claims if c.field == ClaimField.share and c.target.startswith(p.pid + "-")]
        values = [parse_share(c.ai_value) for c in shares]
        if values and all(v is not None for v in values) and sum(values) != 1:
            for c in shares:
                actions.add_flag(case, ACTOR, c.id, f"這筆地的持分加總是 {sum(values)}，不是 1")
            found.append(f"{p.pid} 持分加總不是 1")
    return found
