"""任務：從土地登記謄本照片擷取欄位。

改提示詞時請升級 PROMPT_VERSION，並重新跑評分（tools/eval_extract.py）。
"""
from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict

from ...models import ExOwnership, ExParcel, ExPending, Extraction, PENDING, Source
from ..base import ImageInput, Task

PROMPT_VERSION = "extract-v1"

SYSTEM = f"""你是土地登記謄本的轉錄員。你的工作是把照片上印的字「照抄」成結構化資料，給協助者逐欄核對。

規則：
1. 只抄照片上看得到的字，不推測、不補、不改寫。看不清、被遮住、被污損的欄位，一律填「{PENDING}」，並在 pending 寫明哪一欄、為什麼。
2. 地號照原樣抄，保留前導零與連字號，例如 0005-0001。
3. 段名要完整抄，注意相似段名（例如「示範段」與「示範一段」是不同的段）。小段沒有就填空字串。
4. 面積只抄數字（area_raw），去掉星號與「平方公尺」，保留小數與千分位逗號都可以。
5. 權利範圍照抄（share_raw），例如「全部 1分之1」「2分之1」，去掉星號。
6. 統一編號照原樣抄，遮蔽用的星號要保留，例如 A12345****。
7. 每筆土地依出現順序編 parcel_id：P1、P2…。所有權部要對到它所屬的土地；「續次頁／接前頁」是同一筆土地。
8. source 填資料所在照片的檔名與頁碼（照片前會標示）。
9. 不要輸出照片上沒有的土地或所有權人。"""

INSTRUCTIONS = "請轉錄以下謄本照片。"


# ───── 模型輸出格式（不設預設值，讓結構化輸出要求每個欄位都必填）

class LSource(BaseModel):
    model_config = ConfigDict(extra="forbid")
    file: str
    page: int


class LParcel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    parcel_id: str
    county: str
    township: str
    section: str
    subsection: str
    lot_no: str
    area_raw: str
    source: LSource


class LOwnership(BaseModel):
    model_config = ConfigDict(extra="forbid")
    parcel_id: str
    owner: str
    id_masked: str
    share_raw: str
    source: LSource


class LPending(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: str
    parcel_id: str
    note: str


class LExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    parcels: list[LParcel]
    ownerships: list[LOwnership]
    pending: list[LPending]


# ───── 確定性整理與檢查

LOT_RE = re.compile(r"^\d{4}-\d{4}$")
AREA_RE = re.compile(r"^\d+(\.\d+)?$")
SHARE_RE = re.compile(r"\d+\s*分之\s*\d+")
ID_RE = re.compile(r"^[A-Z][0-9*]{9}$")


def _clean(s: str) -> str:
    return s.replace("*", "").strip()


def clean_area(s: str) -> str:
    s = _clean(s).replace("平方公尺", "").replace(",", "").replace("，", "").strip()
    return s


def clean_share(s: str) -> str:
    s = re.sub(r"\s+", " ", _clean(s))
    return re.sub(r"(全部)\s*(\d)", r"\1 \2", s)


def postprocess(out: LExtraction, images: list[ImageInput]) -> tuple[Extraction, list[str]]:
    problems: list[str] = []
    files = {img.path.name for img in images}
    pages = range(1, len(images) + 1)

    def check_source(src: LSource, where: str) -> None:
        if src.file not in files:
            problems.append(f"{where} 的 source.file「{src.file}」不是提供的照片檔名")
        if src.page not in pages:
            problems.append(f"{where} 的 source.page 超出範圍")

    pids = [p.parcel_id for p in out.parcels]
    if not pids:
        problems.append("沒有任何土地")
    if len(set(pids)) != len(pids):
        problems.append("parcel_id 重複")

    parcels: list[ExParcel] = []
    for p in out.parcels:
        lot = _clean(p.lot_no)
        area = clean_area(p.area_raw) if _clean(p.area_raw) != PENDING else PENDING
        if lot != PENDING and not LOT_RE.match(lot):
            problems.append(f"{p.parcel_id} 地號「{lot}」不是 0000-0000 格式；看不清請填{PENDING}")
        if area != PENDING and not AREA_RE.match(area):
            problems.append(f"{p.parcel_id} 面積不是數字；看不清請填{PENDING}")
        check_source(p.source, p.parcel_id)
        parcels.append(ExParcel(parcel_id=p.parcel_id, county=_clean(p.county), township=_clean(p.township),
                                section=_clean(p.section), subsection=_clean(p.subsection), lot_no=lot,
                                area_raw=area, source=Source(**p.source.model_dump())))

    by_pid = {p.parcel_id: p for p in parcels}
    owners: list[ExOwnership] = []
    for i, o in enumerate(out.ownerships, 1):
        if o.parcel_id not in by_pid:
            problems.append(f"第 {i} 筆所有權對到不存在的土地 {o.parcel_id}")
            continue
        share = clean_share(o.share_raw) if _clean(o.share_raw) != PENDING else PENDING
        idm = o.id_masked.strip()
        if share != PENDING and not SHARE_RE.search(share):
            problems.append(f"{o.parcel_id} 第 {i} 筆權利範圍格式不對；看不清請填{PENDING}")
        if idm != PENDING and not ID_RE.match(idm):
            problems.append(f"{o.parcel_id} 第 {i} 筆統一編號格式不對（應像 A12345****）")
        check_source(o.source, f"{o.parcel_id} 第 {i} 筆所有權")
        p = by_pid[o.parcel_id]
        owners.append(ExOwnership(parcel_id=o.parcel_id, section=p.section, lot_no=p.lot_no, owner=_clean(o.owner),
                                  id_masked=idm, share_raw=share, source=Source(**o.source.model_dump())))
    for p in parcels:
        if not any(o.parcel_id == p.parcel_id for o in owners):
            problems.append(f"{p.parcel_id} 沒有任何所有權人")

    pending = [ExPending(field=x.field, parcel_id=x.parcel_id, note=x.note) for x in out.pending if x.parcel_id in by_pid]
    return Extraction(parcels=parcels, ownerships=owners, pending=pending), problems


TASK: Task[LExtraction, Extraction] = Task(
    name="extract_transcript", prompt_version=PROMPT_VERSION, system=SYSTEM, instructions=INSTRUCTIONS,
    output_model=LExtraction, postprocess=postprocess, max_attempts=2,
)
