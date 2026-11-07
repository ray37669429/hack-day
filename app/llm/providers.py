"""選擇供應商。環境變數 LLM_PROVIDER：openai（預設）、replay、record。測試可用 override() 換掉。"""
from __future__ import annotations

import os
from contextlib import contextmanager

from .base import Provider

_override: Provider | None = None


def get() -> Provider:
    if _override is not None:
        return _override
    name = os.getenv("LLM_PROVIDER", "openai")
    if name == "replay":
        from .replay import ReplayProvider
        return ReplayProvider()
    from .openai_provider import OpenAIProvider
    if name == "record":
        from .replay import RecordingProvider
        return RecordingProvider(OpenAIProvider())
    if name == "openai":
        return OpenAIProvider()
    raise ValueError(f"不認得的 LLM_PROVIDER：{name}")


@contextmanager
def override(provider: Provider):
    global _override
    old, _override = _override, provider
    try:
        yield provider
    finally:
        _override = old
