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

# 核對題：農民自己對照謄本確認 AI 讀到的內容（固定範本）
CHECK_OPTIONS = (("yes", "一樣"), ("no", "不一樣"), ("unsure", "我不確定"))
CHECK_LAND_TEXT = "第 {n} 筆地，跟謄本上寫的一樣嗎？"
CHECK_LAND_SAY = "請看一下，這筆地，跟你的謄本上寫的一樣嗎？"
CHECK_OWNER_TEXT = "第 {n} 筆地的地主，跟謄本上一樣嗎？"
CHECK_OWNER_SAY = "請看一下，地主的名字和持分，跟謄本上一樣嗎？"
UNREADABLE = "（看不清）"

# 實施期間：農民選 1、3、5 年，從今年（民國）1 月 1 日起算
PERIOD_TEXT = "這份同意書要簽幾年？"
PERIOD_SAY = "這份同意書要簽幾年？一年、三年，還是五年？"
PERIOD_YEARS = ("1", "3", "5")


def roc_year(when: datetime | None = None) -> int:
    """民國年 = 西元年 − 1911。"""
    return (when or now()).year - 1911


def period_label(years: str, start: int) -> str:
    """選項文字，例如「3 年（115–117 年）」。"""
    n = int(years)
    return f"{n} 年（{start} 年）" if n == 1 else f"{n} 年（{start}–{start + n - 1} 年）"


def period_text(years: str, start: int) -> str:
    """同意書「實施期間」欄的文字，例如「115.01.01起」換行「117.12.31止」。"""
    return f"{start}.01.01起\n{start + int(years) - 1}.12.31止"


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
    retired: bool = False  # 農民按了重拍，這張不再使用（保留紀錄）


class Parcel(BaseModel):
    pid: str
    source: Source


class Ownership(BaseModel):
    oid: str          # 例：P1-O1
    pid: str
    source: Source


class FieldClaim(BaseModel):
    """擷取主張：AI 認為某頁寫了什麼。農民對照謄本說「一樣」後 value 才算數。"""
    id: str           # 例：P1-lot_no、P1-O1-owner
    target: str       # pid 或 oid
    field: ClaimField
    ai_value: str     # AI 讀到的原值；看不清為空字串
    value: str        # 目前的值（= ai_value；農民只能說一樣或不一樣，不能改值）
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


class Task(BaseModel):
    """系統待辦（目前只用在自動處理失敗）。協助者角色已取消，不再產生給協助者的任務。"""
    id: int
    to: str = "helper"
    text: str
    done: bool = False


class LegalNote(BaseModel):
    """舊版協助者對法律注意事項的處理紀錄。協助者角色已取消（農民回答即算處理）；保留只為相容舊資料。"""
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
    legal_notes: dict[str, LegalNote] = Field(default_factory=dict)  # 不再使用，保留相容舊資料
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
