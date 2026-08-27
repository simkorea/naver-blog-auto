# -*- coding: utf-8 -*-
"""
오디오 형식 매트릭스 — 통화 녹음이 어떤 형식으로 와도 처리되는가.

왜 따로 두는가
  사용자 녹음은 휴대폰에 있고, 어떤 형식일지 모른다. 기기·앱마다 다르다.
  실제로 두 번 당했다:
    · m4a 를 pyannote 가 못 읽어 화자 분리가 죽었다 (Whisper 는 됐다 — 로더가 다르다)
    · .3ga(삼성 통화 녹음), .opus(카톡 음성메시지)는 확장자 목록에 없어
      **스캔에서 조용히 빠졌다.** 녹음이 누락된 줄도 모를 뻔했다.

  둘 다 코드를 읽어서 찾은 것이 아니라 **실제 파일을 넣어봐서** 나왔다.
  그래서 이 검증은 흉내가 아니라 ffmpeg 로 진짜 파일을 만들어 넣는다.

무엇을 확인하는가
  1. 확장자가 오디오로 분류되는가 (안 되면 스캔에서 빠진다)
  2. 전사용 WAV 사본이 실제로 만들어지는가 (여기서 실패하면 원본 경로가
     그대로 돌아가고, 그 원본을 pyannote 에 넘기면 화자 분리가 죽는다)
  3. 스캔에 넣으면 등록되는가

전사 품질 자체는 여기서 확인하지 않는다 — 실제 모델과 GPU 가 필요하다.
"""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from conftest import Check, use_temp_db

# (확장자, ffmpeg 인코딩 인자) — 실제 기기에서 나오는 것들
FORMATS = [
    (".m4a",  ["-c:a", "aac"]),                       # 삼성·아이폰 통화 녹음
    (".3ga",  ["-c:a", "aac", "-f", "ipod"]),         # 삼성 구형 통화 녹음
    (".opus", ["-c:a", "libopus"]),                   # 카카오톡 음성메시지
    (".amr",  ["-c:a", "libopencore_amrnb",
               "-ar", "8000", "-ac", "1"]),           # 구형 안드로이드
    (".mp3",  ["-c:a", "libmp3lame"]),                # 녹음 앱 일반
    (".ogg",  ["-c:a", "libvorbis"]),
    (".aac",  ["-c:a", "aac"]),
    (".wav",  ["-c:a", "pcm_s16le"]),
    (".flac", ["-c:a", "flac"]),
    (".wma",  ["-c:a", "wmav2"]),
    (".3gp",  ["-c:a", "aac", "-ar", "8000"]),        # 폰 녹화
    (".mp4",  ["-c:a", "aac"]),                       # 영상 파일의 소리
]


def _make(exe, base: Path, out: Path, args: list) -> bool:
    """한 형식으로 만들어 본다. 이 ffmpeg 에 인코더가 없으면 False."""
    cmd = [exe, "-y", "-i", str(base), *args, "-loglevel", "error", str(out)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           errors="ignore", timeout=120)
    except Exception:
        return False
    return r.returncode == 0 and out.exists() and out.stat().st_size > 200


def run(tmp_path) -> bool:
    config = use_temp_db(tmp_path)
    from evidence.ingest import preprocess, scanner
    from evidence import db

    c = Check("오디오 형식")

    exe = config.ffmpeg_path()
    if not exe:
        c.ok(False, "ffmpeg 이 없어 형식 검증을 할 수 없습니다")
        return c.report()

    src = tmp_path / "원본"
    src.mkdir()
    base = tmp_path / "base.wav"
    r = subprocess.run(
        [exe, "-y", "-f", "lavfi", "-i", "sine=frequency=220:duration=2",
         "-ar", "44100", "-ac", "1", "-loglevel", "error", str(base)],
        capture_output=True, text=True, errors="ignore", timeout=120)
    if r.returncode != 0 or not base.exists():
        c.ok(False, "시험용 오디오를 만들지 못했습니다")
        return c.report()

    unsupported = []
    for ext, args in FORMATS:
        f = src / f"녹음{ext}"
        if not _make(exe, base, f, args):
            # 이 ffmpeg 빌드에 해당 인코더가 없는 것뿐이다. 프로그램 결함이 아니다.
            unsupported.append(ext)
            continue

        c.eq(config.classify(f), config.KIND_AUDIO,
             f"{ext} 를 녹음으로 분류한다")

        # 전사·화자분리가 함께 쓰는 WAV 사본이 실제로 만들어져야 한다.
        # 여기서 실패하면 원본 경로가 그대로 돌아가고, 그 원본을 pyannote 에
        # 넘기면 "Format not recognised" 로 화자 분리가 죽는다.
        try:
            out, note = preprocess.prepare(f, "light")
            converted = (Path(out).resolve() != f.resolve()
                         and Path(out).exists()
                         and Path(out).stat().st_size > 1000)
        except BaseException as e:
            converted, note = False, f"{type(e).__name__}: {e}"
        c.ok(converted, f"{ext} 에서 전사용 WAV 사본을 만든다", str(note)[:60])

    if unsupported:
        c.ok(True, "이 ffmpeg 빌드에 인코더가 없어 건너뛴 형식",
             ", ".join(unsupported))

    # 폴더째 스캔했을 때 하나도 빠지지 않아야 한다
    conn = db.init()
    res = scanner.scan(conn, src)
    made_files = {p.name for p in src.iterdir()}
    skipped = {Path(x["path"]).name for x in (res.get("skipped") or [])}
    missed = sorted(skipped & made_files)
    c.ok(not missed, "만든 녹음 중 스캔에서 빠진 것이 없다",
         f"빠진 것: {missed or '없음'}")
    c.ok(res["total"] == len(made_files), "만든 녹음이 모두 등록된다",
         f"{res['total']}/{len(made_files)}")
    conn.close()

    return c.report()


if __name__ == "__main__":
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        sys.exit(0 if run(Path(d)) else 1)
