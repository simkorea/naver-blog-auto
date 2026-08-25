# -*- coding: utf-8 -*-
"""
음성 전처리 — 전사 정확도를 올리기 위한 사전 손질.

왜 필요한가
  통화 녹음은 조건이 나쁘다. 8kHz로 압축되고, 잡음이 섞이고,
  목소리 크기가 들쭉날쭉하다. Whisper 한국어 인식률은 그렇지 않아도
  영어보다 낮은데, 이런 음질에서는 더 떨어진다.

  전처리로 잡음을 줄이고 음량을 고르게 하면 인식률이 눈에 띄게 오른다.
  잘못 받아 적힌 발언을 나중에 사람이 찾아 고치는 것보다,
  처음부터 제대로 받아 적는 편이 훨씬 낫다.

원본은 절대 건드리지 않는다.
전처리 결과는 evidence_work/ 아래 임시 사본으로 만들고, 전사에만 쓴다.
발췌본은 언제나 **원본에서** 잘라낸다.
"""
import hashlib
import subprocess
from pathlib import Path

from .. import config, integrity

# ffmpeg 필터 설명
#   highpass=f=80      80Hz 이하 저역 제거 (에어컨·차량 소음 등 웅웅거림)
#   lowpass=f=7500     7.5kHz 이상 제거 (사람 목소리 대역 밖의 잡음)
#   afftdn             주파수 영역 잡음 제거 (백색소음·히스)
#   dynaudnorm         구간별 음량 평준화 (멀리서 말한 부분도 들리게)
FILTERS = {
    "light": "highpass=f=60,dynaudnorm=f=200:g=5",
    "standard": "highpass=f=80,lowpass=f=7500,afftdn=nr=12:nf=-30,dynaudnorm=f=200:g=8",
    "strong": "highpass=f=100,lowpass=f=7000,afftdn=nr=20:nf=-25,"
              "dynaudnorm=f=150:g=12,alimiter=limit=0.95",
}

# Whisper가 기대하는 형식
TARGET_RATE = 16000
TARGET_CHANNELS = 1


def cache_path(src, level: str) -> Path:
    """
    전처리 결과 캐시 경로.
    같은 파일을 다시 전사할 때 전처리를 되풀이하지 않는다.
    """
    key = hashlib.sha256(f"{Path(src).resolve()}|{level}".encode()).hexdigest()[:16]
    d = config.WORK_DIR / "prepared"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{Path(src).stem[:30]}_{key}.wav"


def prepare(src, level: str = "standard", force: bool = False) -> tuple[Path, str]:
    """
    전사용 사본을 만든다. 돌려주는 값: (사본 경로, 적용한 처리 설명)

    실패하면 원본 경로를 그대로 돌려준다 — 전처리가 안 된다고 해서
    전사 자체를 못 하면 안 된다.
    """
    src = Path(src)
    if level in (None, "none", "off"):
        return src, "전처리 없음 (원본 그대로)"

    exe = config.ffmpeg_path()
    if not exe:
        return src, "전처리 건너뜀 (ffmpeg 없음)"

    filt = FILTERS.get(level, FILTERS["standard"])
    out = cache_path(src, level)

    if out.exists() and not force and out.stat().st_size > 1000:
        return out, f"전처리 사본 재사용 ({level})"

    integrity.guard_not_original(out)      # 원본을 덮어쓰지 않는지 확인

    cmd = [exe, "-y", "-i", str(src),
           "-af", filt,
           "-ar", str(TARGET_RATE), "-ac", str(TARGET_CHANNELS),
           "-c:a", "pcm_s16le", "-vn", str(out)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           errors="ignore", timeout=3600)
    except Exception as e:
        return src, f"전처리 실패, 원본으로 진행 ({type(e).__name__})"

    if r.returncode != 0 or not out.exists() or out.stat().st_size < 1000:
        return src, "전처리 실패, 원본으로 진행"

    integrity.log("audio_prepared", src=str(src), out=str(out), level=level)
    return out, f"잡음 제거·음량 평준화 적용 ({level})"


def probe(src) -> dict:
    """
    파일의 음질을 살펴 어떤 전처리가 맞을지 정한다.

    통화 녹음(8kHz 모노)은 이미 대역이 좁아 강한 필터를 걸면
    오히려 목소리가 깎인다. 그래서 표본율에 따라 다르게 다룬다.
    """
    exe = config.ffmpeg_path()
    info = {"sample_rate": None, "channels": None, "codec": None,
            "suggested": "standard"}
    if not exe:
        return info

    try:
        r = subprocess.run([exe, "-i", str(src)], capture_output=True,
                           text=True, errors="ignore", timeout=60)
        err = r.stderr or ""
    except Exception:
        return info

    import re
    m = re.search(r"Audio:\s*([\w]+).*?(\d+)\s*Hz,\s*([\w.()]+)", err)
    if m:
        info["codec"] = m.group(1)
        info["sample_rate"] = int(m.group(2))
        info["channels"] = m.group(3)

    rate = info["sample_rate"] or 0
    if rate and rate <= 8000:
        # 이미 좁은 대역 — 세게 깎으면 목소리가 상한다
        info["suggested"] = "light"
    elif rate >= 44100:
        info["suggested"] = "standard"
    return info


def cleanup(older_than_days: int = 7) -> int:
    """오래된 전처리 사본을 지운다. 용량이 꽤 커진다."""
    import time
    d = config.WORK_DIR / "prepared"
    if not d.exists():
        return 0
    cutoff = time.time() - older_than_days * 86400
    n = 0
    for f in d.glob("*.wav"):
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
                n += 1
        except OSError:
            continue
    return n


def cache_size_mb() -> float:
    d = config.WORK_DIR / "prepared"
    if not d.exists():
        return 0.0
    return round(sum(f.stat().st_size for f in d.glob("*.wav")) / 1024 / 1024, 1)
