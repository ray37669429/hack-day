"""② 擷取 agent：從謄本照片讀出欄位，輸出 app.models.Extraction（格式同假謄本的 answer.json）。

引擎（環境變數 EXTRACT_ENGINE）：
  oracle  讀假謄本答案檔，當作「完美擷取」測試整條流程（案例有 sample_id 時的預設）
  vision  透過 LLM harness（app/llm/）呼叫視覺模型，任務定義在 app/llm/tasks/extract_transcript.py
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from ..models import Case, Extraction

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = ROOT / "data" / "samples" / "fake-transcripts"


def run(case: Case, photos: list[tuple[int, Path]]) -> Extraction:
    """photos：依頁碼排序的（頁碼, 照片路徑）。"""
    engine = os.getenv("EXTRACT_ENGINE") or ("oracle" if case.sample_id else "vision")
    if engine == "oracle":
        if not case.sample_id:
            raise RuntimeError("oracle 引擎只能用在假謄本案例")
        data = json.loads((SAMPLES / case.sample_id / "answer.json").read_text(encoding="utf-8"))
        return Extraction.model_validate(data)
    if engine == "vision":
        return run_vision(photos)
    raise RuntimeError(f"不認得的擷取引擎：{engine}")


def run_vision(photos: list[tuple[int, Path]]) -> Extraction:
    """透過 LLM harness 呼叫視覺模型（供應商由 LLM_PROVIDER 決定，預設 OpenAI）。"""
    from ..llm import harness, providers
    from ..llm.base import ImageInput
    from ..llm.tasks.extract_transcript import TASK

    images = [ImageInput(label=f"第 {page} 頁，檔名 {path.name}", path=path) for page, path in photos]
    return harness.run(TASK, providers.get(), images).value
