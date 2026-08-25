# -*- coding: utf-8 -*-
"""
발췌본 추출 — 원본에서 필요한 구간만 잘라 별도 사본을 만든다.

원본은 절대 건드리지 않는다. 무결성을 지키는 것은 코덱이 아니라
"원본을 그대로 두는 것"이다.

추출 방식이 두 가지인 이유
  정밀 추출 (기본, pcm)
      ffmpeg -i 원본 -ss 시작 -t 길이 -c:a pcm_s16le → WAV
      -ss를 -i 뒤에 두어 샘플 단위로 정확히 자른다. 무압축이라
      재압축 손실이 없고, 30초 클립이 약 5MB로 부담도 없다.
      WAV는 어느 컴퓨터에서나 코덱 없이 열려서, 받는 쪽이
      "재생이 안 된다"고 할 여지가 없다. 그래서 기본값이다.

  스트림 복사 (copy)
      원본 코덱을 그대로 옮긴다. 빠르고 파일이 작다.
      다만 프레임 경계로만 잘린다: 음성 전용 AAC는 프레임이
      약 23ms라 실측상 오차가 없었지만(마커 테스트 0.000초),
      **영상이 포함된 녹화 파일(mp4·mov)은 키프레임 간격이 수 초라
      지정한 시각과 눈에 띄게 어긋날 수 있다.** 컨테이너에 따라
      복사 자체가 실패하기도 한다(그럴 때는 자동으로 정밀 추출로 내려간다).
      쓸 경우 대응표에 방식을 반드시 남긴다.

파일명에 원본과 위치를 새긴다. 파일명만 봐도 어디서 나온 구간인지
알 수 있어야 "잘라냈다"는 의심을 덜 산다.
"""
import re
import subprocess
from datetime import datetime
from pathlib import Path

from .. import config, db, integrity

MODE_PCM = "pcm"
MODE_COPY = "copy"


class ClipError(RuntimeError):
    pass


def _safe(name: str, limit: int = 40) -> str:
    """파일명에 쓸 수 없는 글자를 없앤다. 한글은 그대로 둔다."""
    s = re.sub(r'[\\/:*?"<>|]', "", name)
    s = re.sub(r"\s+", "", s).strip("._")
    return s[:limit] or "증거"


def _tc(sec) -> str:
    sec = int(float(sec or 0))
    return f"{sec // 3600:02d}-{(sec % 3600) // 60:02d}-{sec % 60:02d}"


def clip_name(no: int, source_path, start, end, speaker="", ext=".wav") -> str:
    """
    증거01_20250314통화_00-12-34~00-13-02_고객발언.wav

    파일명만 봐도 원본과 위치를 알 수 있게 만든다.
    """
    stem = _safe(Path(source_path).stem, 24)
    parts = [f"증거{no:02d}", stem, f"{_tc(start)}~{_tc(end)}"]
    if speaker:
        parts.append(_safe(speaker, 12))
    return "_".join(parts) + ext


def extract(source_path, start_sec: float, end_sec: float, out_path,
            mode: str = MODE_PCM) -> dict:
    """
    한 구간을 잘라낸다. 돌려주는 값에 실제 사용한 방식이 담긴다
    (요청한 방식이 실패해 다른 방식으로 내려갔을 수 있다).
    """
    exe = config.ffmpeg_path()
    if not exe:
        raise ClipError("ffmpeg을 찾을 수 없습니다 → pip install imageio-ffmpeg")

    src = Path(source_path)
    if not src.exists():
        raise ClipError(f"원본을 찾을 수 없습니다: {src}")

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # 원본을 덮어쓰려는 시도를 막는다
    integrity.guard_not_original(out_path)

    duration = max(0.05, float(end_sec) - float(start_sec))
    used = mode

    if mode == MODE_COPY:
        cmd = [exe, "-y", "-ss", f"{start_sec:.3f}", "-i", str(src),
               "-t", f"{duration:.3f}", "-c", "copy", str(out_path)]
    else:
        # -ss 를 -i 뒤에 두어야 샘플 단위로 정확하다
        cmd = [exe, "-y", "-i", str(src),
               "-ss", f"{start_sec:.3f}", "-t", f"{duration:.3f}",
               "-c:a", "pcm_s16le", "-vn", str(out_path)]

    r = subprocess.run(cmd, capture_output=True, text=True,
                       errors="ignore", timeout=600)
    if r.returncode != 0 or not out_path.exists() or out_path.stat().st_size < 100:
        if mode == MODE_COPY:
            # 스트림 복사가 안 되는 컨테이너였다 → 정밀 추출로 내려간다
            return extract(source_path, start_sec, end_sec, out_path, MODE_PCM)
        raise ClipError(f"구간 추출 실패: {(r.stderr or '')[-400:]}")

    return {
        "path": out_path,
        "mode": used,
        "bytes": out_path.stat().st_size,
        "duration_sec": round(duration, 3),
        "sha256": integrity.sha256_file(out_path),
    }


def export_basket(conn, out_dir, mode: str = MODE_PCM, progress=None) -> list[dict]:
    """
    장바구니에 담긴 구간을 전부 잘라낸다.
    녹음이 아닌 자료(카톡·문서)는 잘라낼 것이 없으므로 건너뛴다.
    """
    from .. import basket

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    items = [i for i in basket.items(conn) if i["kind"] == "audio"]
    results = []

    for n, item in enumerate(items, 1):
        if progress:
            progress(n, len(items), Path(item["path"]).name)

        start = item["clip_start_sec"]
        end = item["clip_end_sec"]
        if start is None or end is None:
            continue

        name = clip_name(n, item["path"], start, end,
                         item.get("speaker_label") or "")
        try:
            got = extract(item["path"], start, end, out_dir / name, mode)
        except ClipError as e:
            results.append({"ok": False, "name": name, "error": str(e),
                            "orig": item["path"]})
            continue

        db.write(conn,
                 """INSERT INTO clips
                    (basket_id, out_path, sha256, bytes, duration_sec, extract_mode,
                     orig_path, orig_sha256, orig_start_sec, orig_end_sec, exported_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                 (item["id"], str(got["path"]), got["sha256"], got["bytes"],
                  got["duration_sec"], got["mode"], item["path"], item["sha256"],
                  start, end, datetime.now().isoformat(timespec="seconds")))

        integrity.log("clip_exported", basket_id=item["id"], out=str(got["path"]),
                      mode=got["mode"], orig=item["path"],
                      orig_range=f"{start:.2f}-{end:.2f}", sha256=got["sha256"])

        results.append({"ok": True, "no": n, "name": name, **got,
                        "orig": item["path"], "orig_sha256": item["sha256"],
                        "orig_start": start, "orig_end": end,
                        "reason": item.get("reason") or ""})
    return results


def mode_note(mode: str) -> str:
    """대응표에 적을 추출 방식 설명. 숨기지 않고 밝힌다."""
    if mode == MODE_COPY:
        return ("원본 스트림 복사 — 재인코딩 없이 원본 코덱을 그대로 옮겼습니다. "
                "프레임 경계로 잘리므로, 영상이 포함된 파일의 경우 구간 경계가 "
                "지정한 시각과 다소 어긋날 수 있습니다.")
    return ("무압축 PCM 정밀 추출 — 지정한 시각에서 샘플 단위로 정확히 잘렸으며, "
            "재압축에 의한 음질 손상이 없습니다.")
