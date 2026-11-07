"""資料格式（Ontology）。黑客松開工後凍結：只有 L1 能改，其他人要新欄位請先講。

設計說明見 docs/backend-design.md 第 3 節。
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

PENDING = "待確認"

# 農民的 3 題：題目文字與允許的答案
QUESTIONS: dict[str, tuple[str, set[str]]] = {
    "q1": ("這幾筆是你的地嗎？", {"yes", "no", "unsure"}),
    "q2": ("這些地是誰在種？", {"self", "other", "unsure"}),
    "q3": ("用什麼方式給人種？", {"承租", "託耕", "輪耕", "分耕", "unsure"}),
}
ANSWER_LABEL = {"yes": "是", "no": "不是", "unsure": "我不確定", "self": "我自己", "other": "別人",
                "承租": "承租", "託耕": "託耕", "輪耕": "輪耕", "分耕": "分耕"}
# 農民端顯示用：題型、唸給農民聽的句子、選項順序（固定範本，不由 LLM 產生）
QUESTION_UI: dict[str, dict] = {
    "q1": {"kind": "yesno", "say": "這幾筆，是你的地嗎？請說，是，或是，不是。", "options": ["yes", "no", "unsure"]},
    "q2": {"kind": "who", "say": "這些地，是誰在種？是你自己，還是別人？", "options": ["self", "other", "unsure"]},
    "q3": {"kind": "cat", "say": "用什麼方式給人種？承租、託耕、輪耕，還是分耕？",
           "options": ["承租", "託耕", "輪耕", "分耕", "unsure"]},
}


def now() -> datetime:
    return datetime.now().astimezone()


class Stage(str, Enum):
    collecting = "collecting"      # 收照片中
    extracting = "extracting"      # 擷取中
    reviewing = "reviewing"        # 待核對
    documented = "documented"      # 已產生同意書（可能是草稿）
    needs_human = "needs_human"    # agent 失敗，需人工處理


class ClaimStatus(str, Enum):
    pending = "pending"            # 待確認
    confirmed = "confirmed"        # 已確認
    rejected = "rejected"          # 退回


class ClaimField(str, Enum):
    location = "location"          # 坐落（縣市鄉鎮段小段）
    lot_no = "lot_no"              # 地號（文字，保留前導零）
    area_m2 = "area_m2"            # 面積（平方公尺，原值）
    owner = "owner"                # 所有權人
    id_no = "id_no"                # 統一編號（遮蔽）
    share = "share"                # 權利範圍（原文，如「2分之1」）


FIELD_LABEL = {ClaimField.location: "坐落", ClaimField.lot_no: "地號", ClaimField.area_m2: "面積（平方公尺）",
               ClaimField.owner: "所有權人", ClaimField.id_no: "統一編號", ClaimField.share: "權利範圍"}


class Channel(str, Enum):
    button = "button"
    voice = "voice"


class Source(BaseModel):
    file: str
    page: int


class Photo(BaseModel):
    page: int
    file: str
    ok: bool
    reason: str = ""
    brightness: float
    sharpness: float
    at: datetime = Field(default_factory=now)


class Parcel(BaseModel):
    pid: str
    source: Source


class Ownership(BaseModel):
    oid: str          # 例：P1-O1
    pid: str
    source: Source


class FieldClaim(BaseModel):
    """擷取主張：AI 認為某頁寫了什麼。人確認後 value 才算數。"""
    id: str           # 例：P1-lot_no、P1-O1-owner
    target: str       # pid 或 oid
    field: ClaimField
    ai_value: str     # AI 讀到的原值；看不清為空字串
    value: str        # 目前的值（協助者可修正）
    status: ClaimStatus = ClaimStatus.pending
    note: str = ""
    flags: list[str] = Field(default_factory=list)
    source: Source
    confirmed_by: str | None = None


class FarmerAnswer(BaseModel):
    question: str
    value: str
    channel: Channel
    transcript: str = ""   # 語音辨識原文；不存錄音檔
    at: datetime = Field(default_factory=now)


class Manual(BaseModel):
    """協助者人工填寫。換算規則確認前，面積一律人工填，不自動算。"""
    area_ha: dict[str, str] = Field(default_factory=dict)        # pid -> 本筆面積（公頃）
    right_area_ha: dict[str, str] = Field(default_factory=dict)  # oid -> 權利面積（公頃）
    period: str = ""
    cultivator: str = ""                                         # 耕作人及 ID


class Task(BaseModel):
    id: int
    to: str = "helper"
    text: str
    done: bool = False


class LegalNote(BaseModel):
    """協助者對某個法律注意事項的處理紀錄。系統不下法律結論，只記錄人怎麼處理。"""
    by: str
    note: str = ""
    at: datetime = Field(default_factory=now)


class Event(BaseModel):
    at: datetime = Field(default_factory=now)
    actor: str
    action: str
    detail: str = ""


class Case(BaseModel):
    id: str
    farmer_token: str
    sample_id: str | None = None     # 使用假謄本時填 C01–C03
    stage: Stage = Stage.collecting
    pages_expected: int = 2
    photos: list[Photo] = Field(default_factory=list)
    parcels: list[Parcel] = Field(default_factory=list)
    ownerships: list[Ownership] = Field(default_factory=list)
    claims: list[FieldClaim] = Field(default_factory=list)
    answers: dict[str, FarmerAnswer] = Field(default_factory=dict)
    legal_notes: dict[str, LegalNote] = Field(default_factory=dict)  # 法律注意事項 id -> 協助者處理紀錄
    manual: Manual = Field(default_factory=Manual)
    tasks: list[Task] = Field(default_factory=list)
    events: list[Event] = Field(default_factory=list)
    documents: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=now)


# ───── 擷取 agent 的輸出格式（與 data/samples/fake-transcripts/*/answer.json 相同）

class ExParcel(BaseModel):
    parcel_id: str
    county: str
    township: str
    section: str
    subsection: str = ""
    lot_no: str
    area_raw: str
    area_unit: str = "平方公尺"
    source: Source


class ExOwnership(BaseModel):
    parcel_id: str
    section: str = ""
    lot_no: str = ""
    owner: str
    id_masked: str
    share_raw: str
    source: Source


class ExPending(BaseModel):
    field: str
    parcel_id: str
    note: str = ""


class Extraction(BaseModel):
    parcels: list[ExParcel]
    ownerships: list[ExOwnership]
    pending: list[ExPending] = Field(default_factory=list)
