"""農民頁會唸的固定句子都要在 web/audio/prompts.json 裡，才能事先用 Qwen3 TTS 產生音檔。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import collect_prompts  # noqa: E402


def test_all_spoken_sentences_listed():
    missing = [t for _, t in collect_prompts.wanted()
               if t not in {p["zh"] for p in __import__("json").loads(collect_prompts.PROMPTS.read_text(encoding="utf-8"))["items"]}]
    assert missing == [], "請執行 python tools/collect_prompts.py，再用 tools/gen_tts.py --missing 產生音檔"
