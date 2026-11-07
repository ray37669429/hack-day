"""用 Qwen3 TTS 把 web/audio/prompts.json 的固定語句產生成音檔。

產出：web/audio/zh/<id>.wav、web/audio/nan/<id>.wav、web/audio/manifest.json
測試台（web/prototype.html）會讀 manifest.json，有音檔就播音檔，沒有就退回瀏覽器內建語音。

兩種引擎：
  local  本機跑開源版 Qwen3-TTS（需要 NVIDIA 顯示卡）。**只產生國語**：開源版沒有閩南語聲音。
  api    呼叫阿里雲 qwen3-tts-flash。閩南語依官方文件只在中國（北京）區域。

用法：
    python tools/gen_tts.py --dry-run                 # 只列出句子
    <本機環境的 python> tools/gen_tts.py --engine local --only q1   # 本機試一句
    <本機環境的 python> tools/gen_tts.py --engine local             # 本機產生全部國語
    python tools/gen_tts.py --engine api              # 雲端產生國語＋台語

本機環境（在這台電腦已建好）：
    C:\\Users\\Ray\\qwen3-tts\\venv\\Scripts\\python.exe
    重建方式：py -3.13 -m venv venv
              venv\\Scripts\\python -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu128
              venv\\Scripts\\python -m pip install qwen-tts soundfile

設定（.env，不要 commit）：
    # 本機
    QWEN_LOCAL_MODEL=Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice
    QWEN_LOCAL_SPEAKER=Serena          # 溫和女聲；低沉男聲可用 Uncle_Fu
    QWEN_LOCAL_INSTRUCT=用溫和、清楚、稍慢的語氣說，像在跟家裡的長輩說話
    # 雲端
    DASHSCOPE_API_KEY=...
    DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/api/v1
    QWEN_TTS_MODEL=qwen3-tts-flash
    QWEN_TTS_VOICE_ZH=Cherry
    QWEN_TTS_VOICE_NAN=Roy             # 二手資訊，請以官方「支援的音色」頁面核對

只送固定語句，不要送姓名、身分證號等個資。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AUDIO = ROOT / "web" / "audio"


def load_env() -> None:
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


class LocalEngine:
    """開源版 Qwen3-TTS（CustomVoice 內建聲音）。"""
    langs = ("zh",)

    def __init__(self) -> None:
        import torch
        from qwen_tts import Qwen3TTSModel

        if not torch.cuda.is_available():
            raise RuntimeError("找不到 NVIDIA 顯示卡（CUDA），本機模式無法執行")
        self.model_id = os.getenv("QWEN_LOCAL_MODEL", "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice")
        self.speaker = os.getenv("QWEN_LOCAL_SPEAKER", "Serena")
        self.instruct = os.getenv("QWEN_LOCAL_INSTRUCT", "用溫和、清楚、稍慢的語氣說，像在跟家裡的長輩說話")
        print(f"載入 {self.model_id}（第一次會從 Hugging Face 下載）…")
        self.model = Qwen3TTSModel.from_pretrained(
            self.model_id, device_map="cuda:0", dtype=torch.bfloat16, attn_implementation="sdpa",
        )
        self.voice = {"zh": self.speaker}

    def synth(self, text: str, lang: str, path: Path) -> None:
        import soundfile as sf

        kwargs = {"text": text, "language": "Chinese", "speaker": self.speaker}
        if self.instruct:
            kwargs["instruct"] = self.instruct
        wavs, sr = self.model.generate_custom_voice(**kwargs)
        sf.write(str(path), wavs[0], sr)


class ApiEngine:
    """阿里雲 qwen3-tts-flash（尚未用真實金鑰測試，第一次請先 --only q1）。"""
    langs = ("zh", "nan")

    def __init__(self) -> None:
        self.key = os.getenv("DASHSCOPE_API_KEY", "")
        if not self.key:
            raise RuntimeError("找不到 DASHSCOPE_API_KEY，請放進 .env")
        self.model_id = os.getenv("QWEN_TTS_MODEL", "qwen3-tts-flash")
        self.voice = {"zh": os.getenv("QWEN_TTS_VOICE_ZH", "Cherry"), "nan": os.getenv("QWEN_TTS_VOICE_NAN", "Roy")}

    def synth(self, text: str, lang: str, path: Path) -> None:
        import dashscope
        import requests

        base = os.getenv("DASHSCOPE_BASE_URL")
        if base:
            dashscope.base_http_api_url = base
        resp = dashscope.MultiModalConversation.call(
            model=self.model_id, api_key=self.key, text=text, voice=self.voice[lang],
            language_type="Chinese", stream=False,
        )
        if getattr(resp, "status_code", 200) != 200:
            raise RuntimeError(f"Qwen3 TTS 失敗：{getattr(resp, 'code', '')} {getattr(resp, 'message', resp)}")
        out = resp.output
        audio = out["audio"] if isinstance(out, dict) else out.audio
        url = audio["url"] if isinstance(audio, dict) else audio.url
        r = requests.get(url, timeout=60)  # 網址 24 小時內有效，要立即下載
        r.raise_for_status()
        path.write_bytes(r.content)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", choices=["local", "api"], default=os.getenv("QWEN_TTS_ENGINE", "local"))
    ap.add_argument("--lang", choices=["zh", "nan", "all"], default="all")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", help="只產生某個 id，例如 q1")
    args = ap.parse_args()

    load_env()
    prompts = json.loads((AUDIO / "prompts.json").read_text(encoding="utf-8"))["items"]
    if args.only:
        prompts = [p for p in prompts if p["id"] == args.only]
    wanted = ["zh", "nan"] if args.lang == "all" else [args.lang]

    if args.dry_run:
        for p in prompts:
            for lang in wanted:
                print(f"[{lang}] {p['id']}: {p[lang]}")
        return 0

    engine = LocalEngine() if args.engine == "local" else ApiEngine()
    langs = [l for l in wanted if l in engine.langs]
    skipped = [l for l in wanted if l not in engine.langs]
    if skipped:
        print(f"注意：{args.engine} 引擎不支援 {skipped}，略過（開源版沒有閩南語聲音）")

    manifest_path = AUDIO / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {"items": {}}
    for p in prompts:
        entry = manifest["items"].setdefault(p["id"], {"files": {}})
        entry["zh_text"] = p["zh"]
        for lang in langs:
            rel = f"{lang}/{p['id']}.wav"
            (AUDIO / lang).mkdir(parents=True, exist_ok=True)
            t0 = time.time()
            engine.synth(p[lang], lang, AUDIO / rel)
            entry["files"][lang] = rel
            entry.setdefault("engine", {})[lang] = f"{args.engine}:{engine.model_id}:{engine.voice[lang]}"
            print(f"[{lang}] {p['id']} 完成（{time.time() - t0:.1f} 秒）：{p[lang]}")
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print("已更新", manifest_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
