"""用 Qwen3 TTS 把 web/audio/prompts.json 的固定語句產生成音檔。

產出：web/audio/zh/<id>.wav、web/audio/nan/<id>.wav、web/audio/manifest.json
測試台（web/prototype.html）會讀 manifest.json，有音檔就播音檔，沒有就退回瀏覽器內建語音。

用法：
    pip install dashscope requests
    python tools/gen_tts.py --dry-run        # 只列出要產生的句子，不呼叫 API
    python tools/gen_tts.py                  # 產生國語＋台語
    python tools/gen_tts.py --lang zh        # 只產生國語

設定（放在 .env，不要 commit）：
    DASHSCOPE_API_KEY=...
    DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/api/v1   # 北京區；國際版用 https://dashscope-intl.aliyuncs.com/api/v1
    QWEN_TTS_MODEL=qwen3-tts-flash
    QWEN_TTS_VOICE_ZH=Cherry
    QWEN_TTS_VOICE_NAN=Roy        # 閩南語聲音，名稱為二手資訊，請以官方「支援的音色」頁面核對

注意：
- 依阿里雲文件，閩南語目前列在 qwen3-tts-flash 的中國（北京）區域；國際版是否支援請先確認。
- 這支腳本依官方說明使用 dashscope.MultiModalConversation 呼叫，尚未用真實金鑰測試過；第一次使用時請先跑一句確認參數。
- 只送固定語句，不要送姓名、身分證號等個資。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AUDIO = ROOT / "web" / "audio"


def load_env() -> None:
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def synthesize(text: str, voice: str, model: str, api_key: str) -> bytes:
    import dashscope
    import requests

    base = os.getenv("DASHSCOPE_BASE_URL")
    if base:
        dashscope.base_http_api_url = base
    resp = dashscope.MultiModalConversation.call(
        model=model, api_key=api_key, text=text, voice=voice, language_type="Chinese", stream=False,
    )
    if getattr(resp, "status_code", 200) != 200:
        raise RuntimeError(f"Qwen3 TTS 失敗：{getattr(resp, 'code', '')} {getattr(resp, 'message', resp)}")
    out = resp.output
    audio = out["audio"] if isinstance(out, dict) else out.audio
    url = audio["url"] if isinstance(audio, dict) else audio.url
    r = requests.get(url, timeout=60)  # 官方說明：網址 24 小時內有效，要立即下載
    r.raise_for_status()
    return r.content


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", choices=["zh", "nan", "all"], default="all")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", help="只產生某個 id，例如 q1")
    args = ap.parse_args()

    load_env()
    prompts = json.loads((AUDIO / "prompts.json").read_text(encoding="utf-8"))["items"]
    langs = ["zh", "nan"] if args.lang == "all" else [args.lang]
    model = os.getenv("QWEN_TTS_MODEL", "qwen3-tts-flash")
    voices = {"zh": os.getenv("QWEN_TTS_VOICE_ZH", "Cherry"), "nan": os.getenv("QWEN_TTS_VOICE_NAN", "Roy")}
    key = os.getenv("DASHSCOPE_API_KEY", "")

    manifest_path = AUDIO / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {"model": model, "items": {}}

    if not args.dry_run and not key:
        print("找不到 DASHSCOPE_API_KEY，請放進 .env（可先用 --dry-run 確認句子）", file=sys.stderr)
        return 1

    for item in prompts:
        if args.only and item["id"] != args.only:
            continue
        entry = manifest["items"].setdefault(item["id"], {"zh_text": item["zh"], "files": {}})
        entry["zh_text"] = item["zh"]
        for lang in langs:
            text = item[lang]
            rel = f"{lang}/{item['id']}.wav"
            print(f"[{lang}] {item['id']}: {text}")
            if args.dry_run:
                continue
            (AUDIO / lang).mkdir(parents=True, exist_ok=True)
            (AUDIO / rel).write_bytes(synthesize(text, voices[lang], model, key))
            entry["files"][lang] = rel
            entry.setdefault("voices", {})[lang] = voices[lang]

    if not args.dry_run:
        manifest["model"] = model
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        print("已更新", manifest_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
