"""⑤ 文件 agent：依確認過的資料產生土地使用同意書。

送出條件：actions.missing(case) 為空才是正式版；否則整份標「草稿」。
一位所有權人一份（docs/agreement-spec.md 產生規則 1）。
"""
from __future__ import annotations

import sys
from pathlib import Path

from .. import actions, store
from ..models import Case, PENDING

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from make_agreement import Agreement, Line, build  # noqa: E402

ACTOR = "agent:document"


def run(case: Case) -> list[str]:
    miss = actions.missing(case)
    draft = bool(miss)
    a, m = case.answers, case.manual
    category = a["q3"].value if "q3" in a and a["q3"].value != "unsure" else PENDING
    cultivator = m.cultivator or PENDING

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
                area_ha=m.area_ha.get(o.pid) or PENDING,
                right_area_ha=m.right_area_ha.get(o.oid) or PENDING,
                period=m.period or PENDING,
                owner=f"{owner}\n{idn}" if owner != PENDING and idn else PENDING,
                cultivator=cultivator,
            ))
        ag = Agreement(party_a="" if owner == PENDING else owner,
                       party_b="" if cultivator == PENDING else cultivator.split()[0],
                       lines=lines, force_draft=draft)
        name = f"同意書_{i}_{'草稿' if ag.is_draft else '正式'}.docx"
        build(ag).save(out_dir / name)
        files.append(name)
    actions.record_documents(case, ACTOR, files, draft)
    return files
