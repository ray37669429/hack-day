"""案例儲存：每個案例一個 JSON。放在 data/output/（不進 git）。

測試時可用環境變數 HACKDAY_DATA 指到暫存資料夾。
"""
from __future__ import annotations

import os
import secrets
import threading
from datetime import datetime
from pathlib import Path

from .models import Case

ROOT = Path(__file__).resolve().parent.parent
_lock = threading.RLock()


def cases_dir() -> Path:
    d = Path(os.getenv("HACKDAY_DATA", ROOT / "data" / "output")) / "cases"
    d.mkdir(parents=True, exist_ok=True)
    return d


def case_dir(case_id: str) -> Path:
    if not case_id.replace("-", "").isalnum():
        raise ValueError("案例編號格式不對")
    d = cases_dir() / case_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def new_ids() -> tuple[str, str]:
    case_id = datetime.now().strftime("K%Y%m%d-%H%M%S") + secrets.token_hex(2)
    return case_id, secrets.token_urlsafe(16)  # 128 位元農民連結


def save(case: Case) -> None:
    with _lock:
        path = case_dir(case.id) / "case.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(case.model_dump_json(indent=2), encoding="utf-8")
        tmp.replace(path)


def load(case_id: str) -> Case:
    with _lock:
        path = case_dir(case_id) / "case.json"
        if not path.exists():
            raise KeyError(case_id)
        return Case.model_validate_json(path.read_text(encoding="utf-8"))


def find_by_token(token: str) -> Case:
    with _lock:
        for p in cases_dir().glob("*/case.json"):
            c = Case.model_validate_json(p.read_text(encoding="utf-8"))
            if secrets.compare_digest(c.farmer_token, token):
                return c
    raise KeyError("token")
