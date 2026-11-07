"""⑤ 文件 agent：依確認過的資料產生土地使用同意書。

送出條件：actions.missing(case) 為空才是正式版；否則整份標「草稿」。
一位所有權人一份（docs/agreement-spec.md 產生規則 1）。
- 本筆面積、權利面積：由已確認的面積與持分計算（app/agents/area.py）；不能算就填「待確認」。
- 實施期間：農民選的年數。類別：第 3 題的答案；農民答「我不確定」就留白給簽約時手寫。
- 乙方耕作人姓名及 ID：一律留白，簽約時手寫（留白不算草稿）。
- 備註：法律注意事項的固定短句（legal.remarks_for）。
"""
from __future__ import annotations

import sys
from pathlib import Path

from .. import actions, store
from ..models import Case, PENDING
from . import legal

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from make_agreement import CATEGORIES, Agreement, Line, build  # noqa: E402

ACTOR = "agent:document"


def _category(case: Case) -> str:
    a = case.answers.get("q3")
    if a is None:
        return PENDING
    return a.value if a.value in CATEGORIES else ""  # 不確定 → 留白手寫


def run(case: Case) -> list[str]:
    miss = actions.missing(case)
    draft = bool(miss)
    category = _category(case)
    period = actions.period(case) or PENDING

    # 確認過的所有權人才依姓名合併；沒確認的各自一份，避免把不同的人自動合併
    groups: dict[str, tuple[str, list]] = {}
    for o in case.ownerships:
        name = actions.confirmed(case, f"{o.oid}-owner")
        key = f"owner:{name}" if name else f"unconfirmed:{o.oid}"
        groups.setdefault(key, (name or PENDING, []))[1].append(o)

    out_dir = store.case_dir(case.id) / "documents"
    out_dir.mkdir(exist_ok=True)
    for old in out_dir.glob("*.docx"):
        old.unlink()
    files: list[str] = []
    for i, (owner, owns) in enumerate(groups.values(), 1):
        lines = []
        for o in owns:
            loc, lot = actions.confirmed(case, f"{o.pid}-location"), actions.confirmed(case, f"{o.pid}-lot_no")
            idn = actions.confirmed(case, f"{o.oid}-id_no")
            lines.append(Line(
                category=category,
                location=f"{loc}\n{lot}" if loc and lot else PENDING,
                area_ha=actions.area_ha(case, o.pid) or PENDING,
                right_area_ha=actions.right_area_ha(case, o.oid) or PENDING,
                period=period,
                owner=f"{owner}\n{idn}" if owner != PENDING and idn else PENDING,
                cultivator="",
                note="；".join(legal.remarks_for(case, o.pid)),
            ))
        ag = Agreement(party_a="" if owner == PENDING else owner, party_b="", lines=lines, force_draft=draft)
        name = f"同意書_{i}_{'草稿' if ag.is_draft else '正式'}.docx"
        build(ag).save(out_dir / name)
        files.append(name)
    actions.record_documents(case, ACTOR, files, draft)
    return files
