"""LLM harness 的共用型別。供應商（OpenAI、離線重播…）只需實作 Provider.complete。"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Generic, Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)
R = TypeVar("R")


class LLMError(Exception):
    """LLM 相關錯誤的基底。訊息會寫進案例任務，給人看。"""


class LLMUnavailable(LLMError):
    """服務連不上、金鑰錯誤、流量限制等，非輸出內容問題。"""


class LLMRefusal(LLMError):
    """模型拒絕回答。"""


class LLMOutputError(LLMError):
    """輸出格式或內容檢查一直不通過。"""


@dataclass
class ImageInput:
    label: str          # 放在圖片前的說明，例如「第 1 頁，檔名 page1.png」
    path: Path


@dataclass
class LLMRequest:
    task: str
    prompt_version: str
    system: str
    text: str
    images: list[ImageInput]
    output_model: type[BaseModel]   # 要求模型照這個格式輸出
    max_output_tokens: int = 16000


@dataclass
class LLMResponse:
    text: str                        # 原始 JSON 文字；harness 會自己再驗證一次
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    request_id: str = ""


class Provider(Protocol):
    name: str

    def complete(self, req: LLMRequest) -> LLMResponse: ...


@dataclass
class Task(Generic[T, R]):
    """一個 LLM 任務的完整定義。"""
    name: str
    prompt_version: str
    system: str
    instructions: str
    output_model: type[T]
    # 後處理：只做確定性的整理（去星號、去單位），回傳（結果, 檢查不通過的原因）
    postprocess: Callable[[T, list[ImageInput]], tuple[R, list[str]]]
    max_attempts: int = 2


@dataclass
class HarnessResult(Generic[R]):
    value: R
    attempts: int
    responses: list[LLMResponse] = field(default_factory=list)
