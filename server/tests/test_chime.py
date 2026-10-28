"""整點報時：時間表、回應標頭與音檔轉換。"""

import math
import shutil
import struct
import wave
from datetime import datetime

import pytest

from scoreboard import chime as chime_mod
from scoreboard.chime import Chime
from scoreboard.config import Config

BASE = Config.load(None)
TZ = BASE.tz


def _cfg(tmp_path, **over):
    wav = tmp_path / "chime.wav"
    with wave.open(str(wav), "wb") as w:  # 0.5 秒、22.05kHz、雙聲道的 440Hz 測試音
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(22050)
        w.writeframes(b"".join(struct.pack("<hh", v, v) for v in
                               (int(8000 * math.sin(2 * math.pi * 440 * i / 22050)) for i in range(11025))))
    conf = {**BASE.raw["chime"], "enabled": True, "file": str(wav), **over}
    return Config({**BASE.raw, "chime": conf})


def test_weekday_and_weekend_hours(tmp_path):
    c = Chime(_cfg(tmp_path))
    wed, sat = datetime(2026, 10, 28, tzinfo=TZ).date(), datetime(2026, 10, 31, tzinfo=TZ).date()
    assert list(c.hours(wed)) == list(range(9, 21))  # 平日 09:00～20:00，共 12 次
    assert list(c.hours(sat)) == list(range(12, 21))  # 假日 12:00～20:00，共 9 次


def test_next_chime(tmp_path):
    c = Chime(_cfg(tmp_path))
    assert c.next_chime(datetime(2026, 10, 28, 8, 59, 50, tzinfo=TZ)) == datetime(2026, 10, 28, 9, tzinfo=TZ)
    # 整點剛過 10 秒：還是這一次（看板晚一點來抓畫面也會播）
    assert c.next_chime(datetime(2026, 10, 28, 9, 0, 10, tzinfo=TZ)) == datetime(2026, 10, 28, 9, tzinfo=TZ)
    assert c.next_chime(datetime(2026, 10, 28, 9, 1, tzinfo=TZ)) == datetime(2026, 10, 28, 10, tzinfo=TZ)
    # 平日 20:00 是最後一次，下一次是隔天（週四）09:00
    assert c.next_chime(datetime(2026, 10, 28, 20, 5, tzinfo=TZ)) == datetime(2026, 10, 29, 9, tzinfo=TZ)
    # 週五晚上 → 週六 12:00
    assert c.next_chime(datetime(2026, 10, 30, 21, tzinfo=TZ)) == datetime(2026, 10, 31, 12, tzinfo=TZ)


def test_holidays_and_workdays(tmp_path):
    c = Chime(_cfg(tmp_path, holidays=["2026-10-28"], workdays=["2026-10-31"]))
    assert c.next_chime(datetime(2026, 10, 28, 8, tzinfo=TZ)) == datetime(2026, 10, 28, 12, tzinfo=TZ)
    assert c.next_chime(datetime(2026, 10, 31, 8, tzinfo=TZ)) == datetime(2026, 10, 31, 9, tzinfo=TZ)


def test_headers(tmp_path):
    c = Chime(_cfg(tmp_path, volume=55))
    h = c.headers(datetime(2026, 10, 28, 8, 59, 30, tzinfo=TZ))
    assert h["X-Chime-In"] == "30000" and h["X-Chime-Id"] == "20261028090000"
    assert h["X-Chime-Volume"] == "55" and len(h["X-Chime-Ver"]) == 12
    assert c.headers(datetime(2026, 10, 28, 7, 30, tzinfo=TZ)) == {}  # 一小時以後的不用先講
    assert Chime(_cfg(tmp_path, enabled=False)).headers(datetime(2026, 10, 28, 8, 59, tzinfo=TZ)) == {}


def test_test_button(tmp_path):
    c = Chime(_cfg(tmp_path))
    now = datetime(2026, 10, 28, 7, 0, tzinfo=TZ)
    c.test(now)
    assert c.headers(now)["X-Chime-In"] == "0"


@pytest.mark.parametrize("use_ffmpeg", [False, True])
def test_convert_to_48k_mono(tmp_path, monkeypatch, use_ffmpeg):
    if use_ffmpeg and not shutil.which("ffmpeg"):
        pytest.skip("沒有 ffmpeg")
    if not use_ffmpeg:
        monkeypatch.setattr(chime_mod.shutil, "which", lambda _: None)
    pcm = Chime(_cfg(tmp_path)).pcm()
    seconds = len(pcm) / 2 / 48000
    assert abs(seconds - 0.5) < 0.02  # 0.5 秒的音檔，轉成 48kHz 單聲道 16-bit
    assert max(abs(v) for v in struct.unpack(f"<{len(pcm) // 2}h", pcm)) > 6000


def test_missing_file(tmp_path):
    c = Chime(_cfg(tmp_path, file=str(tmp_path / "nope.mp3")))
    assert c.pcm() is None and "找不到音檔" in c.error
    assert c.headers(datetime(2026, 10, 28, 8, 59, tzinfo=TZ)) == {}
