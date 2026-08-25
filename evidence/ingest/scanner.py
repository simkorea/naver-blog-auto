# -*- coding: utf-8 -*-
"""
폴더 스캔 — 증거 자료를 프로그램에 들여오는 입구.

하는 일
  1. 지정한 폴더를 재귀 탐색
  2. 확장자로 종류 분류 (녹음/카톡/문서/이미지)
  3. SHA-256 해시 봉인
  4. 같은 해시는 한 건으로 병합 (같은 파일을 여러 폴더에 복사해둔 경우)
  5. 파일명·메타데이터에서 발생 일시 추정

원본은 읽기만 한다. 이동·개명·수정하지 않는다.
"""
import re
from datetime import datetime
from pathlib import Path

from .. import config, db, integrity

# 건너뛸 것들
SKIP_DIRS = {".git", "__pycache__", "venv", ".venv", "node_modules",
             "$RECYCLE.BIN", "System Volume Information", "evidence_work"}
SKIP_NAMES = {"Thumbs.db", ".DS_Store", "desktop.ini"}
MIN_BYTES = 100          # 빈 파일 · 잔여물 제외


# ─────────────────────────────────────────────────────────
# 발생 일시 추정
# ─────────────────────────────────────────────────────────
# 통화 녹음 앱들이 쓰는 파일명 패턴. 소송에서 시각은 결정적이라
# 최대한 파일명에서 정확히 뽑아내고, 못 뽑으면 추정으로 표시한다.
_DATE_PATTERNS = [
    # 20250314_143022 / 20250314-143022 / 20250314 143022
    (re.compile(r"(20\d{2})(\d{2})(\d{2})[ _\-]?(\d{2})(\d{2})(\d{2})"), "ymdhms"),
    # 2025-03-14 14.30.22 / 2025.03.14 14:30
    (re.compile(r"(20\d{2})[.\-](\d{1,2})[.\-](\d{1,2})[ _]+(\d{1,2})[.:](\d{2})(?:[.:](\d{2}))?"), "ymdhms"),
    # 20250314
    (re.compile(r"(20\d{2})(\d{2})(\d{2})"), "ymd"),
    # 2025-03-14 / 2025.03.14
    (re.compile(r"(20\d{2})[.\-](\d{1,2})[.\-](\d{1,2})"), "ymd"),
]


def guess_occurred_at(path) -> tuple[str | None, bool]:
    """
    발생 일시를 추정한다. 돌려주는 값: (ISO 문자열, 추정값 여부)

    파일명에 날짜가 박혀 있으면 그것을 신뢰하고(추정 아님),
    없으면 파일 수정 시각을 쓰되 추정으로 표시한다.
    """
    name = Path(path).name
    for rx, kind in _DATE_PATTERNS:
        m = rx.search(name)
        if not m:
            continue
        g = [int(x) if x else 0 for x in m.groups()]
        try:
            if kind == "ymdhms":
                dt = datetime(g[0], g[1], g[2], g[3], g[4], g[5] if len(g) > 5 else 0)
            else:
                dt = datetime(g[0], g[1], g[2])
            if 2000 <= dt.year <= datetime.now().year + 1:
                return dt.isoformat(timespec="seconds"), False
        except ValueError:
            continue

    try:
        st = Path(path).stat()
        return datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"), True
    except OSError:
        return None, True


def audio_duration(path) -> float | None:
    """ffprobe 없이 ffmpeg로 길이를 재본다. 실패해도 등록은 진행한다."""
    exe = config.ffmpeg_path()
    if not exe:
        return None
    import subprocess
    try:
        r = subprocess.run(
            [exe, "-i", str(path), "-hide_banner"],
            capture_output=True, text=True, timeout=60,
            errors="ignore",
        )
        m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", r.stderr or "")
        if m:
            h, mnt, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
            return h * 3600 + mnt * 60 + s
    except Exception:
        pass
    return None


# ─────────────────────────────────────────────────────────
# 스캔
# ─────────────────────────────────────────────────────────
def walk(folder) -> list[Path]:
    """대상 파일 목록을 모은다."""
    root = Path(folder)
    if not root.exists():
        raise FileNotFoundError(f"폴더를 찾을 수 없습니다: {folder}")
    if root.is_file():
        return [root]

    found = []
    for p in root.rglob("*"):
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        if not p.is_file() or p.name in SKIP_NAMES or p.name.startswith("~$"):
            continue
        try:
            if p.stat().st_size < MIN_BYTES:
                continue
        except OSError:
            continue
        if config.classify(p) is None:
            continue
        if _is_kakao_continuation(p):
            # 카카오톡은 대화가 길면 1MB 단위로 파일을 쪼갠다.
            # 첫 조각을 파싱할 때 뒷조각까지 이어 붙이므로, 뒷조각을 따로
            # 등록하면 같은 메시지가 두 번 들어간다.
            continue
        found.append(p)
    return sorted(found)


def _is_kakao_continuation(p: Path) -> bool:
    """KakaoTalk_Chats_2.txt 처럼 앞 조각이 존재하는 뒷조각인지 판별."""
    if p.suffix.lower() != ".txt":
        return False
    m = re.match(r"^(?P<base>.+)_(?P<n>\d+)$", p.stem)
    if not m or int(m.group("n")) < 2:
        return False
    first = p.parent / f"{m.group('base')}{p.suffix}"
    if not first.exists():
        return False
    return config.classify(first) == config.KIND_KAKAO


def scan(conn, folder, progress=None, defaults: dict = None) -> dict:
    """
    폴더를 스캔해 원본으로 등록한다.

    progress: 콜백(현재, 전체, 파일명)
    defaults: 전체에 일괄 적용할 값 (예: counterparty)
    """
    defaults = defaults or {}
    files = walk(folder)
    added, duplicate, failed = [], [], []

    for i, p in enumerate(files, 1):
        if progress:
            progress(i, len(files), p.name)
        try:
            kind = config.classify(p)
            fp = integrity.fingerprint(p)
            occurred, estimated = guess_occurred_at(p)

            extra = dict(defaults)
            extra.update(occurred_at=occurred, occurred_at_est=estimated)
            if kind == config.KIND_AUDIO:
                extra["duration_sec"] = audio_duration(p)
            else:
                # 녹음이 아니면 통신비밀보호법 쟁점 자체가 없다
                extra.setdefault("is_my_conversation", "NA")

            sid, is_new = db.add_source(conn, fp, kind, **extra)
            if is_new:
                added.append((sid, p))
                integrity.log("register", source_id=sid, path=str(p),
                              sha256=fp["sha256"], kind=kind, bytes=fp["bytes"])
            else:
                duplicate.append((sid, p))
        except Exception as e:
            failed.append((p, str(e)))
            integrity.log("register_failed", path=str(p), error=str(e))

    return {
        "total": len(files),
        "added": added,
        "duplicate": duplicate,
        "failed": failed,
    }


def list_sources(conn, kind=None, status=None) -> list:
    sql = "SELECT * FROM sources"
    where, args = [], []
    if kind:
        where.append("kind = ?")
        args.append(kind)
    if status:
        where.append("status = ?")
        args.append(status)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY COALESCE(occurred_at, ingested_at), id"
    return conn.execute(sql, args).fetchall()


def update_source(conn, source_id: int, **fields) -> None:
    """사용자가 화면에서 고친 값(적법성·상대방·일시)을 반영한다."""
    allowed = {"is_my_conversation", "counterparty", "occurred_at",
               "occurred_at_est", "memo", "duration_sec"}
    sets, args = [], []
    for k, v in fields.items():
        if k in allowed:
            sets.append(f"{k} = ?")
            args.append(v)
    if not sets:
        return
    args.append(source_id)
    db.write(conn, f"UPDATE sources SET {', '.join(sets)} WHERE id = ?", args)
    integrity.log("source_updated", source_id=source_id, **fields)
