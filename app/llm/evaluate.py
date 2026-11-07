"""擷取評分：拿模型輸出和假謄本答案檔（answer.json）逐欄比對。

最重要的指標是「猜測」：答案是「待確認」但模型填了值。猜測必須是 0（硬規則：不猜）。
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from ..models import PENDING, Extraction


def _area(s: str) -> str:
    s = (s or "").replace(",", "").replace("*", "").replace("平方公尺", "").strip()
    try:
        return str(Decimal(s).normalize())
    except InvalidOperation:
        return s


def _share(s: str) -> str:
    return (s or "").replace("*", "").replace(" ", "").strip()


def score(truth: dict, pred: Extraction) -> dict:
    checks: list[dict] = []
    guesses: list[str] = []

    def check(where: str, field: str, want: str, got: str) -> None:
        if want == PENDING:
            if got != PENDING:
                guesses.append(f"{where} {field}：答案是待確認，模型填了「{got}」")
            checks.append({"where": where, "field": field, "ok": got == PENDING})
            return
        checks.append({"where": where, "field": field, "ok": want == got, "want": want, "got": got})

    key = lambda section, sub, lot: f"{section}{sub or ''}/{lot}"
    t_parcels = {key(p["section"], p.get("subsection"), p["lot_no"]): p for p in truth["parcels"]}
    p_parcels = {key(p.section, p.subsection, p.lot_no): p for p in pred.parcels}
    missing = sorted(set(t_parcels) - set(p_parcels))
    extra = sorted(set(p_parcels) - set(t_parcels))
    t_pid = {p["parcel_id"]: key(p["section"], p.get("subsection"), p["lot_no"]) for p in truth["parcels"]}
    p_pid = {p.parcel_id: key(p.section, p.subsection, p.lot_no) for p in pred.parcels}

    for k in sorted(set(t_parcels) & set(p_parcels)):
        t, p = t_parcels[k], p_parcels[k]
        check(k, "縣市", t["county"], p.county)
        check(k, "鄉鎮", t["township"], p.township)
        check(k, "面積", _area(t["area_raw"]) if t["area_raw"] != PENDING else PENDING,
              _area(p.area_raw) if p.area_raw != PENDING else PENDING)

    t_owns = {(t_pid[o["parcel_id"]], o["owner"]): o for o in truth["ownerships"]}
    p_owns = {(p_pid.get(o.parcel_id, "?"), o.owner): o for o in pred.ownerships}
    missing_owners = sorted(f"{a}:{b}" for a, b in set(t_owns) - set(p_owns))
    extra_owners = sorted(f"{a}:{b}" for a, b in set(p_owns) - set(t_owns))
    for k in sorted(set(t_owns) & set(p_owns)):
        t, p = t_owns[k], p_owns[k]
        where = f"{k[0]}:{k[1]}"
        check(where, "統一編號", t["id_masked"], p.id_masked)
        check(where, "權利範圍", _share(t["share_raw"]) if t["share_raw"] != PENDING else PENDING,
              _share(p.share_raw) if p.share_raw != PENDING else PENDING)

    total = len(checks) + len(missing) + len(extra) + len(missing_owners) + len(extra_owners)
    correct = sum(c["ok"] for c in checks)
    return {
        "accuracy": round(correct / total, 4) if total else 0.0,
        "correct": correct, "total": total,
        "missing_parcels": missing, "extra_parcels": extra,
        "missing_owners": missing_owners, "extra_owners": extra_owners,
        "guesses": guesses,
        "wrong": [c for c in checks if not c["ok"]],
        "passed": not guesses and correct == total,
    }
