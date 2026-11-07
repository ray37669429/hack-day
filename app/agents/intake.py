"""① 收件 agent：照片品質檢查（亮度與清晰度）。門檻與 web/prototype.html 相同。

清晰度門檻依真實照片校正（2026-11-07）：清楚的手機照約 520–550、手震模糊的約 150、假謄本壞照片約 4。
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageOps

MIN_BRIGHTNESS = 90
MIN_SHARPNESS = 250
WIDTH = 320


def measure(path: Path) -> tuple[float, float]:
    """回傳（平均亮度, 拉普拉斯變異數）。在縮成 320 px 寬的灰階圖上計算。"""
    img = ImageOps.exif_transpose(Image.open(path)).convert("L")
    h = max(1, round(img.height * WIDTH / img.width))
    img = img.resize((WIDTH, h), Image.BILINEAR)
    g = list(img.tobytes())
    w = WIDTH
    mean = sum(g) / len(g)
    s = s2 = 0.0
    n = 0
    for y in range(1, h - 1):
        row = y * w
        for x in range(1, w - 1):
            i = row + x
            v = 4 * g[i] - g[i - 1] - g[i + 1] - g[i - w] - g[i + w]
            s += v
            s2 += v * v
            n += 1
    sharp = s2 / n - (s / n) ** 2 if n else 0.0
    return mean, sharp


def check(path: Path) -> tuple[bool, str, float, float]:
    """回傳（是否通過, 原因, 亮度, 清晰度）。原因用農民聽得懂的話。"""
    try:
        mean, sharp = measure(path)
    except Exception:
        return False, "照片打不開，請再拍一次", 0.0, 0.0
    if mean < MIN_BRIGHTNESS:
        return False, "照片有點暗，請到亮一點的地方再拍一次", mean, sharp
    if sharp < MIN_SHARPNESS:
        return False, "照片有點糊，請拿穩手機，再拍一次", mean, sharp
    return True, "", mean, sharp
