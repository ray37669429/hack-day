"""用假謄本評分擷取任務。

    .venv\Scripts\python tools/eval_extract.py                    # 用 LLM_PROVIDER（預設 openai）跑 C01–C03
    set LLM_PROVIDER=record & .venv\Scripts\python tools/eval_extract.py   # 跑真的模型並錄下回應
    set LLM_PROVIDER=replay & .venv\Scripts\python tools/eval_extract.py   # 用錄好的回應重播，不花錢
    .venv\Scripts\python tools/eval_extract.py --clean            # 用乾淨掃描頁，不用模擬手機照片

結果寫到 data/output/evals/。有任何「猜測」時結束代碼為 1。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import load_env  # noqa: E402

load_env()

from app.llm import harness, providers  # noqa: E402
from app.llm.base import ImageInput, LLMError  # noqa: E402
from app.llm.evaluate import score  # noqa: E402
from app.llm.tasks.extract_transcript import TASK  # noqa: E402

SAMPLES = ROOT / "data" / "samples" / "fake-transcripts"


def case_images(case_id: str, clean: bool) -> list[ImageInput]:
    d = SAMPLES / case_id
    first = d / ("page1.png" if clean else "photo_page1.jpg")
    return [ImageInput(f"第 1 頁，檔名 {first.name}", first), ImageInput("第 2 頁，檔名 page2.png", d / "page2.png")]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", nargs="*", default=["C01", "C02", "C03"])
    ap.add_argument("--clean", action="store_true")
    args = ap.parse_args()

    provider = providers.get()
    results = {}
    for cid in args.cases:
        truth = json.loads((SAMPLES / cid / "answer.json").read_text(encoding="utf-8"))
        try:
            r = harness.run(TASK, provider, case_images(cid, args.clean))
            rep = score(truth, r.value)
            rep["attempts"] = r.attempts
            rep["tokens"] = sum(x.input_tokens + x.output_tokens for x in r.responses)
        except LLMError as e:
            rep = {"error": str(e), "passed": False, "guesses": []}
        results[cid] = rep
        status = "通過" if rep["passed"] else "未通過"
        acc = f"{rep['accuracy']:.0%}" if "accuracy" in rep else "-"
        print(f"{cid}：{status}　正確率 {acc}　猜測 {len(rep['guesses'])}　{rep.get('error', '')}")
        for g in rep["guesses"]:
            print(f"   ⚠ {g}")
        for w in rep.get("wrong", [])[:5]:
            print(f"   ✗ {w['where']} {w['field']}：應為「{w.get('want', '待確認')}」，得到「{w.get('got', '')}」")

    out = ROOT / "data" / "output" / "evals"
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{datetime.now():%Y%m%d-%H%M%S}_{TASK.prompt_version}_{provider.name}.json"
    path.write_text(json.dumps({"task": TASK.name, "prompt_version": TASK.prompt_version, "provider": provider.name,
                                "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    print("結果：", path)
    return 1 if any(r["guesses"] for r in results.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
