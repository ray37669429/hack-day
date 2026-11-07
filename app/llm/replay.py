"""不用網路的供應商：測試、評分、展示備案都靠它。

ScriptedProvider  依序回傳寫好的輸出（單元測試用）
ReplayProvider    依請求內容的雜湊，讀取之前錄下的回應（tests/fixtures/llm/）
RecordingProvider 包住真的供應商，把回應錄下來給 ReplayProvider 用
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .base import LLMError, LLMRequest, LLMResponse, Provider

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "llm"


def request_key(req: LLMRequest) -> str:
    h = hashlib.sha256()
    for part in (req.task, req.prompt_version, req.system, req.text):
        h.update(part.encode("utf-8"))
    for img in req.images:
        h.update(img.label.encode("utf-8"))
        h.update(hashlib.sha256(img.path.read_bytes()).digest())
    return h.hexdigest()[:24]


class ScriptedProvider:
    name = "scripted"

    def __init__(self, outputs: list[str]):
        self.outputs = list(outputs)
        self.requests: list[LLMRequest] = []

    def complete(self, req: LLMRequest) -> LLMResponse:
        self.requests.append(req)
        if not self.outputs:
            raise LLMError("ScriptedProvider 沒有更多輸出")
        return LLMResponse(text=self.outputs.pop(0), provider=self.name, model="scripted")


class ReplayProvider:
    name = "replay"

    def __init__(self, directory: Path = FIXTURES):
        self.directory = directory

    def complete(self, req: LLMRequest) -> LLMResponse:
        path = self.directory / req.task / f"{request_key(req)}.json"
        if not path.exists():
            raise LLMError(f"沒有錄好的回應：{path.name}（先用 LLM_PROVIDER=record 錄一次）")
        data = json.loads(path.read_text(encoding="utf-8"))
        return LLMResponse(text=data["text"], provider=self.name, model=data.get("model", "replay"))


class RecordingProvider:
    name = "record"

    def __init__(self, inner: Provider, directory: Path = FIXTURES):
        self.inner, self.directory = inner, directory

    def complete(self, req: LLMRequest) -> LLMResponse:
        rsp = self.inner.complete(req)
        path = self.directory / req.task / f"{request_key(req)}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"text": rsp.text, "model": rsp.model, "prompt_version": req.prompt_version},
                                   ensure_ascii=False, indent=2), encoding="utf-8")
        return rsp
