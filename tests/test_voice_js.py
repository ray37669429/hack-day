"""web/voice.js：speak() 一定會結束（不然阿伯的對話框會卡在回答上）。需要 node，沒有就略過。"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.skipif(shutil.which("node") is None, reason="沒有 node")
def test_speak_always_finishes():
    r = subprocess.run(["node", str(ROOT / "tests" / "js" / "voice_speak.mjs")], capture_output=True, text=True,
                       encoding="utf-8", timeout=30)
    assert r.returncode == 0, r.stderr + r.stdout
    assert "ok" in r.stdout
