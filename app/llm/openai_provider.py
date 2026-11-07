"""OpenAI 供應商：Responses API + 結構化輸出（responses.parse，text_format=Pydantic 模型）。

設定（.env）：
    OPENAI_API_KEY=...
    OPENAI_MODEL=gpt-6-astra          # 預設旗艦模型；省錢可改 gpt-6-luna
    OPENAI_REASONING_EFFORT=high      # 擷取準確度優先
"""
from __future__ import annotations

import base64
import io
import os

import openai
from PIL import Image, ImageOps

from .base import LLMRefusal, LLMRequest, LLMResponse, LLMUnavailable

MAX_SIDE = 2400  # 手機照片先縮小，謄本文字仍清楚，也省流量


def encode_image(path) -> str:
    img = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


class OpenAIProvider:
    name = "openai"

    def __init__(self, model: str | None = None, effort: str | None = None, client: openai.OpenAI | None = None):
        self.model = model or os.getenv("OPENAI_MODEL", "gpt-6-astra")
        self.effort = effort or os.getenv("OPENAI_REASONING_EFFORT", "high")
        self.client = client or openai.OpenAI(max_retries=3, timeout=180)  # SDK 會自動重試 429、5xx、連線錯誤

    def build_input(self, req: LLMRequest) -> list[dict]:
        content: list[dict] = []
        for img in req.images:
            content.append({"type": "input_text", "text": img.label})
            content.append({"type": "input_image", "image_url": encode_image(img.path), "detail": "high"})
        content.append({"type": "input_text", "text": req.text})
        return [{"role": "system", "content": req.system}, {"role": "user", "content": content}]

    def complete(self, req: LLMRequest) -> LLMResponse:
        try:
            rsp = self.client.responses.parse(
                model=self.model,
                input=self.build_input(req),
                text_format=req.output_model,
                reasoning={"effort": self.effort},
                max_output_tokens=req.max_output_tokens,
            )
        except openai.AuthenticationError:
            raise LLMUnavailable("OpenAI 金鑰無效或沒有設定（OPENAI_API_KEY）")
        except openai.RateLimitError:
            raise LLMUnavailable("OpenAI 流量或額度限制，請稍後再試")
        except openai.BadRequestError as e:
            raise LLMUnavailable(f"OpenAI 拒絕這個請求：{e.message}")
        except openai.APIStatusError as e:
            raise LLMUnavailable(f"OpenAI 服務錯誤（{e.status_code}）")
        except openai.APIConnectionError:
            raise LLMUnavailable("連不上 OpenAI")

        for item in rsp.output:
            for part in getattr(item, "content", None) or []:
                if getattr(part, "type", "") == "refusal":
                    raise LLMRefusal(f"模型拒絕回答：{getattr(part, 'refusal', '')}")
        if getattr(rsp, "status", "completed") == "incomplete":
            reason = getattr(getattr(rsp, "incomplete_details", None), "reason", "")
            raise LLMUnavailable(f"輸出不完整（{reason}）")

        usage = rsp.usage
        details = getattr(usage, "input_tokens_details", None)
        return LLMResponse(
            text=rsp.output_text,
            provider=self.name,
            model=rsp.model,
            input_tokens=getattr(usage, "input_tokens", 0) or 0,
            output_tokens=getattr(usage, "output_tokens", 0) or 0,
            cached_tokens=getattr(details, "cached_tokens", 0) or 0,
            request_id=getattr(rsp, "_request_id", "") or "",
        )
