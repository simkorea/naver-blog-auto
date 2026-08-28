# -*- coding: utf-8 -*-
"""
추출 오케스트레이터 — 등록된 원본을 종류별 담당자에게 넘긴다.

음성은 느리고(모델 로딩 + GPU 연산) 텍스트는 빠르다.
그래서 텍스트를 먼저 다 처리해 사용자가 곧바로 검색을 써볼 수 있게 하고,
음성은 그다음에 돌린다.
"""
from .. import config, db, integrity


def extract_one(conn, source_row, file_progress=None, **kwargs) -> tuple[int, str]:
    """
    원본 하나를 처리한다. 돌려주는 값: (구간 수, 메시지)

    어떤 파일 하나가 깨져 있어도 전체가 멈추지 않게 예외를 여기서 잡는다.
    """
    kind = source_row["kind"]
    try:
        db.set_status(conn, source_row["id"], "extracting")

        if kind == config.KIND_KAKAO:
            from . import kakao
            n = kakao.extract(conn, source_row)
        elif kind == config.KIND_IMAGE:
            from . import images
            n = images.extract(conn, source_row)
        elif kind in (config.KIND_DOC, config.KIND_EMAIL):
            from . import documents
            n = documents.extract(conn, source_row)
        elif kind == config.KIND_AUDIO:
            from . import audio
            # 파일 하나를 처리하는 동안의 진행률. audio.extract 는 원래부터
            # 이 콜백을 받게 되어 있었는데 위에서 넘겨주지 않아 배선이
            # 끊겨 있었다. 그래서 긴 녹음에서 화면이 멈춘 듯 보였다.
            n = audio.extract(conn, source_row, progress=file_progress, **kwargs)
        else:
            db.set_status(conn, source_row["id"], "failed", f"알 수 없는 종류: {kind}")
            return 0, f"알 수 없는 종류: {kind}"

        row = conn.execute("SELECT status_detail FROM sources WHERE id = ?",
                           (source_row["id"],)).fetchone()
        return n, (row["status_detail"] if row else "") or f"{n}개 구간"

    except BaseException as e:
        db.set_status(conn, source_row["id"], "failed", f"{type(e).__name__}: {e}")
        integrity.log("extract_error", source_id=source_row["id"],
                      kind=kind, error=str(e))
        return 0, f"실패: {e}"


# 처리 순서: 빠르고 확실한 것부터. 음성은 마지막.
TEXT_KINDS = (config.KIND_KAKAO, config.KIND_DOC, config.KIND_EMAIL, config.KIND_IMAGE)


def pending(conn, kinds=None, redo: bool = False):
    """아직 처리하지 않은 원본 목록."""
    sql = "SELECT * FROM sources WHERE 1=1"
    args = []
    if not redo:
        sql += " AND status IN ('registered', 'failed', 'extracting')"
    if kinds:
        sql += f" AND kind IN ({','.join('?' * len(kinds))})"
        args.extend(kinds)
    sql += " ORDER BY CASE kind WHEN 'audio' THEN 2 ELSE 1 END, id"
    return conn.execute(sql, args).fetchall()


def already_done(conn, kinds=None) -> int:
    """이미 끝나 이번에 건너뛸 건수. 화면에 보여주기 위한 값."""
    sql = "SELECT count(*) FROM sources WHERE status IN ('extracted','verified')"
    args = []
    if kinds:
        sql += f" AND kind IN ({','.join('?' * len(kinds))})"
        args.extend(kinds)
    r = conn.execute(sql, args).fetchone()
    return r[0] if r else 0


def run(conn, kinds=None, redo: bool = False, progress=None,
        file_progress=None, stop=None, **kwargs) -> dict:
    """
    일괄 처리.

    progress       (현재, 전체, 파일명, 메시지)  — 파일 단위
    file_progress  (현재, 전체, 파일명, 0.0~1.0) — **파일 하나 안에서의 진행률**
    stop           () -> bool. True 를 돌려주면 지금 파일까지만 하고 멈춘다

    파일 안 진행률이 왜 필요한가
      9분짜리 녹음 하나를 처리하는 데 몇 분이 걸리는데 그동안 화면이
      전혀 움직이지 않으면 사용자는 멈춘 줄 안다. 실제로 그렇게 판단해
      다시 누르는 일이 있었다. 그러면 그 파일만 처음부터 다시 한다.
    """
    rows = pending(conn, kinds=kinds, redo=redo)
    done, failed, segments = 0, 0, 0
    stopped = False

    from pathlib import Path
    for i, row in enumerate(rows, 1):
        if stop is not None and stop():
            stopped = True
            break

        name = Path(row["path"]).name
        if progress:
            progress(i, len(rows), name, "처리 중...")

        on_file = None
        if file_progress:
            def on_file(frac, _i=i, _name=name):
                file_progress(_i, len(rows), _name, frac)

        n, msg = extract_one(conn, row, file_progress=on_file, **kwargs)
        segments += n
        if n > 0 or "실패" not in msg:
            done += 1
        else:
            failed += 1
        if progress:
            progress(i, len(rows), name, msg)

    return {"total": len(rows), "done": done, "failed": failed,
            "segments": segments, "stopped": stopped,
            "skipped_done": already_done(conn, kinds)}
