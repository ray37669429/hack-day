"""LLM harness 主流程：呼叫 → 驗證格式 → 確定性整理 → 內容檢查 → 不通過就帶著原因重試 → 記錄。

護欄：
- 輸出一定要通過 Pydantic 驗證與任務自己的檢查，否則丟出 LLMOutputError，由流程轉人工。
- harness 只回傳資料，不寫入案例；寫入一律經過 app.actions（擷取結果只能是「待確認」）。
- 紀錄只寫任務、模型、token、耗時、錯誤類型，不寫圖片與欄位值（個資）。
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path

from pydantic import ValidationError

from .base import HarnessResult, ImageInput, LLMOutputError, LLMRequest, Provider, Task

ROOT = Path(__file__).resolve().parents[2]


def _log_path() -> Path:
    d = Path(os.getenv("HACKDAY_DATA", ROOT / "data" / "output")) / "llm_logs"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{datetime.now():%Y%m%d}.jsonl"


def _log(record: dict) -> None:
    with _log_path().open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def run(task: Task, provider: Provider, images: list[ImageInput], context: str = "") -> HarnessResult:
    feedback = ""
    responses = []
    for attempt in range(1, task.max_attempts + 1):
        text = task.instructions + (f"\n\n{context}" if context else "")
        if feedback:
            text += f"\n\n上一次的輸出沒有通過檢查，請修正以下問題後重新輸出完整結果：\n{feedback}"
        req = LLMRequest(task=task.name, prompt_version=task.prompt_version, system=task.system,
                         text=text, images=images, output_model=task.output_model)
        t0 = time.monotonic()
        record = {"at": datetime.now().isoformat(timespec="seconds"), "task": task.name,
                  "prompt_version": task.prompt_version, "provider": provider.name, "attempt": attempt,
                  "images": len(images)}
        try:
            rsp = provider.complete(req)
        except Exception as e:
            _log({**record, "ok": False, "error": type(e).__name__, "ms": round((time.monotonic() - t0) * 1000)})
            raise
        responses.append(rsp)
        record.update(model=rsp.model, ms=round((time.monotonic() - t0) * 1000), input_tokens=rsp.input_tokens,
                      output_tokens=rsp.output_tokens, cached_tokens=rsp.cached_tokens, request_id=rsp.request_id)
        try:
            parsed = task.output_model.model_validate_json(rsp.text)
        except ValidationError as e:
            problems = [f"{'.'.join(map(str, err['loc']))}：{err['msg']}" for err in e.errors()[:10]]
        else:
            value, problems = task.postprocess(parsed, images)
            if not problems:
                _log({**record, "ok": True})
                return HarnessResult(value=value, attempts=attempt, responses=responses)
        _log({**record, "ok": False, "problems": len(problems)})
        feedback = "\n".join(f"- {p}" for p in problems)
    raise LLMOutputError(f"{task.name} 輸出連續 {task.max_attempts} 次沒有通過檢查：{feedback[:300]}")
