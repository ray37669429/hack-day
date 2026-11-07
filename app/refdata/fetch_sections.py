"""重新產生 data/refdata/land_sections.csv（內政部地政司「土地段名代碼（API）」）。

用法：
    .venv\\Scripts\\python -m app.refdata.fetch_sections            # 線上下載
    .venv\\Scripts\\python -m app.refdata.fetch_sections 某檔.json  # 用已下載的 JSON

來源：https://data.gov.tw/dataset/122674（政府資料開放授權條款第1版）
"""
from __future__ import annotations

import csv
import json
import sys
import urllib.request
from pathlib import Path

SOURCE_URL = "https://lisp.land.moi.gov.tw/MoiMMSv2/SectionList.ashx"
OUT = Path(__file__).resolve().parents[2] / "data" / "refdata" / "land_sections.csv"
COLUMNS = ["county", "township", "office", "office_code", "town_code",
           "section", "subsection", "section_code", "comment"]


def rows_from(units: list[dict]) -> list[list[str]]:
    rows = []
    for u in units:
        for s in u.get("Sections", []):
            rows.append([
                str(u.get("CITY", "")).strip(), str(u.get("TOWN", "")).strip(),
                str(u.get("UNIT", "")).strip(), str(u.get("OfficeCode", "")).strip(),
                str(u.get("TownCode", "")).strip(),
                str(s.get("Section", "")).strip(), str(s.get("SubSection", "")).strip(),
                str(s.get("SectionCode", "")).strip(), str(s.get("Comment", "")).strip(),
            ])
    return rows


def main(argv: list[str]) -> None:
    if argv:
        raw = Path(argv[0]).read_bytes()
    else:
        with urllib.request.urlopen(SOURCE_URL, timeout=120) as r:
            raw = r.read()
    rows = rows_from(json.loads(raw.decode("utf-8-sig")))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(COLUMNS)
        w.writerows(rows)
    print(f"寫入 {OUT}（{len(rows)} 筆）")


if __name__ == "__main__":
    main(sys.argv[1:])
