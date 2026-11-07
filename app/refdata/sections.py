"""段名／小段名比對官方清單（內政部地政司「土地段名代碼」）。

只回報「有沒有在官方清單」與相近段名供人工參考，**絕不改值**。
資料檔不存在時回傳 found=True、skipped=True，不讓流程中斷。
"""
from __future__ import annotations

import csv
import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

DATA_PATH = Path(__file__).resolve().parents[2] / "data" / "refdata" / "land_sections.csv"
MAX_SUGGESTIONS = 3

# 縣市改制前的舊名 → 現名（謄本可能仍印舊名）
_COUNTY_ALIASES = {
    "臺北縣": "新北市", "桃園縣": "桃園市", "臺中縣": "臺中市",
    "臺南縣": "臺南市", "高雄縣": "高雄市",
}
_SPLIT_SUB = re.compile(r"^(.+?段)(.+?)小段$")

# 字形相近、容易認錯的字（只用來排序建議，不會拿來改值）
_LOOKALIKE_GROUPS = ["四西", "己已巳", "土士", "未末", "日曰", "大太犬", "王玉", "天夫",
                     "人入八", "千干", "刀力", "田由甲申", "子孑", "東柬", "崙侖", "埔浦",
                     "寮療", "厝措", "林材", "竹什"]
_LOOKALIKE = {(a, b) for g in _LOOKALIKE_GROUPS for a in g for b in g if a != b}


@dataclass
class SectionCheck:
    found: bool
    message: str
    suggestions: list[str] = field(default_factory=list)
    skipped: bool = False          # 沒有比對（資料檔缺、段名空白）
    section_code: str = ""         # 找到時的官方段代碼


@dataclass(frozen=True)
class _Entry:
    county: str
    township: str
    office: str
    section: str        # 官方段名（不含「段」）
    subsection: str     # 官方小段（不含「小段」），沒有則空字串
    code: str

    @property
    def name(self) -> str:
        return f"{self.section}段" + (f"{self.subsection}小段" if self.subsection else "")


def norm(text: str | None) -> str:
    """全形轉半形、去掉所有空白、台→臺。只用於比對，不拿來改值。"""
    t = unicodedata.normalize("NFKC", text or "")
    return re.sub(r"\s+", "", t).replace("台", "臺")


def _strip_suffix(text: str, suffixes: str) -> str:
    return text[:-1] if len(text) > 1 and text[-1] in suffixes else text


def _office_key(text: str) -> str:
    t = norm(text)
    for suf in ("地政事務所", "地政所", "地政"):
        if t.endswith(suf) and len(t) > len(suf):
            return t[: -len(suf)]
    return t


_cache: dict[tuple[str, float], dict[str, list[_Entry]]] = {}


def _load(path: Path) -> dict[str, list[_Entry]] | None:
    """讀 CSV，依（正規化後的）縣市分組。檔案不存在回傳 None。"""
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    key = (str(path), mtime)
    if key not in _cache:
        by_county: dict[str, list[_Entry]] = {}
        with path.open(encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                e = _Entry(
                    county=norm(r["county"]), township=norm(r["township"]),
                    office=norm(r["office"]), section=norm(r["section"]),
                    subsection=norm(r["subsection"]), code=r["section_code"].strip(),
                )
                by_county.setdefault(e.county, []).append(e)
        _cache.clear()
        _cache[key] = by_county
    return _cache[key]


def _find_county(data: dict[str, list[_Entry]], county: str) -> str | None:
    c = norm(county)
    c = _COUNTY_ALIASES.get(c, c)
    if c in data:
        return c
    bare = _strip_suffix(c, "縣市")
    hits = [k for k in data if _strip_suffix(k, "縣市") == bare]
    return hits[0] if len(hits) == 1 else None


def _match_township(entries: list[_Entry], township: str) -> list[_Entry]:
    t = norm(township)
    if not t:
        return []
    bare = _strip_suffix(t, "鄉鎮市區")
    office = _office_key(t)
    return [e for e in entries
            if e.township == t or _strip_suffix(e.township, "鄉鎮市區") == bare
            or _office_key(e.office) == office]


def _split(section: str, subsection: str) -> tuple[str, str]:
    s, sub = norm(section), norm(subsection)
    if not sub:
        m = _SPLIT_SUB.match(s)
        if m:
            s, sub = m.group(1), m.group(2)
    s = _strip_suffix(s, "段")
    if sub.endswith("小段") and len(sub) > 2:
        sub = sub[:-2]
    return s, sub


def _plain_diffs(a: str, b: str) -> int:
    """同長度時，不算「形近字」的相異字數；長度不同視為很多。"""
    if len(a) != len(b):
        return 99
    return sum(1 for x, y in zip(a, b) if x != y and (x, y) not in _LOOKALIKE)


def _edit_distance(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1]


def _suggest(name: str, entries: list[_Entry]) -> list[str]:
    """依編輯距離挑最接近的官方名稱；同分時形近字優先、再看最長共同片段。"""
    limit = max(1, len(name) // 2)
    scored: dict[str, tuple[int, int, int, int]] = {}
    for i, e in enumerate(entries):
        if e.name in scored:
            continue
        dist = _edit_distance(name, e.name)
        if dist <= limit:
            longest = SequenceMatcher(None, name, e.name).find_longest_match(
                0, len(name), 0, len(e.name)).size
            scored[e.name] = (dist, _plain_diffs(name, e.name), -longest, i)
    return sorted(scored, key=scored.get)[:MAX_SUGGESTIONS]


def lookup(county: str, township: str, section: str, subsection: str = "",
           *, data_path: Path | str | None = None) -> SectionCheck:
    """比對（縣市, 鄉鎮市區或地政事務所, 段, 小段）是否在官方段名清單。

    township 對不上（或空白）時改在整個縣市內找。只回報，不改值。
    """
    data = _load(Path(data_path) if data_path else DATA_PATH)
    if data is None:
        return SectionCheck(True, "找不到官方段名清單檔，略過段名比對", skipped=True)

    sec, sub = _split(section, subsection)
    if not sec:
        return SectionCheck(False, "段名空白，無法比對官方段名清單", skipped=True)
    shown = f"{sec}段" + (f"{sub}小段" if sub else "")

    county_key = _find_county(data, county)
    if county_key is None:
        return SectionCheck(False, f"縣市『{(county or '').strip()}』不在官方段名清單（無法比對段名『{shown}』）")
    county_entries = data[county_key]

    town_entries = _match_township(county_entries, township)
    if town_entries:
        scope, where = town_entries, f"{county_key}{(township or '').strip()}"
    else:
        scope, where = county_entries, county_key
    note = "" if town_entries or not norm(township) else f"（鄉鎮『{township.strip()}』對不上，改查全縣市）"

    exact = [e for e in scope if e.section == sec and e.subsection == sub]
    if exact:
        return SectionCheck(True, f"段名『{shown}』在{where}的官方段名清單{note}",
                            section_code=exact[0].code)

    same_sec = [e for e in scope if e.section == sec]
    if same_sec:
        names = _suggest(shown, same_sec) or sorted({e.name for e in same_sec})[:MAX_SUGGESTIONS]
        what = f"小段『{sub}小段』不在清單" if sub else "未填小段（清單中此段有分小段）"
        if not any(e.subsection for e in same_sec):
            what = "清單中此段沒有小段"
        return SectionCheck(False, f"{where}有『{sec}段』，但{what}{note}，相近：{'、'.join(names)}",
                            suggestions=names)

    suggestions = _suggest(shown, scope)
    tail = f"，相近：{'、'.join(suggestions)}" if suggestions else "，找不到相近段名"
    msg = f"段名『{shown}』不在{where}的官方段名清單{note}{tail}"
    if town_entries:
        elsewhere = sorted({e.township for e in county_entries
                            if e.section == sec and e.subsection == sub})
        if elsewhere:
            msg += f"；但{county_key}{'、'.join(elsewhere)}有同名段，請確認鄉鎮"
    return SectionCheck(False, msg, suggestions=suggestions)
