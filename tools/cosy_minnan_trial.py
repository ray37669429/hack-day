"""Fun-CosyVoice3 閩南語試跑。

用法：C:\Users\Ray\cosyvoice\venv\Scripts\python tools/cosy_minnan_trial.py C:\Users\Ray\cosyvoice web/audio/nan_trial
需先下載 FunAudioLLM/Fun-CosyVoice3-0.5B-2512 到 <repo>/pretrained_models/Fun-CosyVoice3-0.5B。
"""
import os
import sys
import time

repo, out = sys.argv[1], sys.argv[2]
os.makedirs(out, exist_ok=True)
os.chdir(repo)
sys.path[:0] = [repo, os.path.join(repo, "third_party", "Matcha-TTS")]

import torchaudio  # noqa: E402
from cosyvoice.cli.cosyvoice import AutoModel  # noqa: E402

model = AutoModel(model_dir="pretrained_models/Fun-CosyVoice3-0.5B")
MINNAN = "You are a helpful assistant. 请用闽南话表达。<|endofprompt|>"
tests = [
    ("nan_q1_tw", "這幾筆土地，敢是你的？請講，是，抑是，毋是。", MINNAN),       # 台語漢字（繁體）
    ("nan_q1_zh", "這幾筆，是你的地嗎？請說，是，或是，不是。", MINNAN),          # 國語用字，請它用閩南話念
    ("nan_done", "多謝你，回答好矣。同意書準備好了後，協助者會佮你約時間，紮印仔來簽名。", MINNAN),
]
for name, text, instruct in tests:
    t = time.time()
    for i, j in enumerate(model.inference_instruct2(text, instruct, "./asset/zero_shot_prompt.wav", stream=False)):
        path = os.path.join(out, f"{name}.wav")
        torchaudio.save(path, j["tts_speech"], model.sample_rate)
        secs = j["tts_speech"].shape[1] / model.sample_rate
    print(f"{name}: 產生 {time.time() - t:.1f} 秒，音檔長 {secs:.1f} 秒 -> {path}", flush=True)
