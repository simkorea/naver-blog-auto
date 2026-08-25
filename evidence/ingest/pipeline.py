# -*- coding: utf-8 -*-
"""
추출 오케스트레이터 — 등록된 원본을 종류별 담당자에게 넘긴다.

음성은 느리고(모델 로딩 + GPU 연산) 텍스트는 빠르다.
그래서 텍스트를 먼저 다 처리해 사용자가 곧바로 검색을 써볼 수 있게 하고,
음성은 그다음에 돌린다.
"""
from .. import config, db, integrity


def extract_one(conn, source_row, **kwargs) -> tuple[int, str]:
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
            n = audio.extract(conn, source_row, **kwargs)
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


def run(conn, kinds=None, redo: bool = False, progress=None, **kwargs) -> dict:
    """
    일괄 처리. progress 콜백: (현재, 전체, 파일명, 메시지)
    """
    rows = pending(conn, kinds=kinds, redo=redo)
    done, failed, segments = 0, 0, 0

    for i, row in enumerate(rows, 1):
        from pathlib import Path
        name = Path(row["path"]).name
        if progress:
            progress(i, len(rows), name, "처리 중...")

        n, msg = extract_one(conn, row, **kwargs)
        segments += n
        if n > 0 or "실패" not in msg:
            done += 1
        else:
            failed += 1
        if progress:
            progress(i, len(rows), name, msg)

    return {"total": len(rows), "done": done, "failed": failed,
            "segments": segments}
