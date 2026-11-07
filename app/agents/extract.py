"""② 擷取 agent：從謄本照片讀出欄位，輸出 app.models.Extraction（格式同假謄本的 answer.json）。

引擎（環境變數 EXTRACT_ENGINE）：
  oracle  讀假謄本答案檔，當作「完美擷取」測試整條流程（案例有 sample_id 時的預設）
  vision  呼叫視覺 AI。尚未實作。

vision 引擎實作要點：
- 讓 AI 依 Extraction 的 JSON 格式輸出，每個值附來源頁碼。
- 去掉謄本的星號補位（「******1,234.56平方公尺」→「1234.56」）。
- 看不清就填「待確認」並在 pending 說明，絕對不猜。
- 地號一律當文字，保留前導零。同地號可能出現在不同段，段名要一起讀。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from ..models import Case, Extraction

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = ROOT / "data" / "samples" / "fake-transcripts"


def run(case: Case, photos: list[Path]) -> Extraction:
    engine = os.getenv("EXTRACT_ENGINE") or ("oracle" if case.sample_id else "vision")
    if engine == "oracle":
        if not case.sample_id:
            raise RuntimeError("oracle 引擎只能用在假謄本案例")
        data = json.loads((SAMPLES / case.sample_id / "answer.json").read_text(encoding="utf-8"))
        return Extraction.model_validate(data)
    if engine == "vision":
        raise NotImplementedError("視覺 AI 擷取尚未實作，請先用假謄本案例（oracle 引擎）")
    raise RuntimeError(f"不認得的擷取引擎：{engine}")
