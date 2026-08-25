# -*- coding: utf-8 -*-
"""
발췌 장바구니 — 제출할 구간을 모으는 곳.

검색하다 "이건 유리하다" 싶은 구간을 담아두고, 나중에 한 번에
발췌본으로 뽑아 제출 패키지를 만든다.

담을 때 앞뒤로 여유(pad)를 준다. 말이 시작되기 직전과 끝난 직후를
포함해야 맥락이 살고, "잘라냈다"는 반박도 줄어든다.
"""
from datetime import datetime

from . import db

PAD_BEFORE = 2.0        # 구간 앞 여유 (초)
PAD_AFTER = 2.0         # 구간 뒤 여유 (초)


def add(conn, segment_id: int, reason: str = None) -> int:
    row = conn.execute(
        """SELECT s.source_id, s.start_sec, s.end_sec, src.duration_sec
           FROM segments s JOIN sources src ON src.id = s.source_id
           WHERE s.id = ?""", (segment_id,)
    ).fetchone()
    if not row:
        raise ValueError(f"구간을 찾을 수 없습니다: {segment_id}")

    start = row["start_sec"]
    end = row["end_sec"]
    if start is not None:
        start = max(0.0, start - PAD_BEFORE)
        limit = row["duration_sec"] or (end + PAD_AFTER)
        end = min(float(limit), (end or start) + PAD_AFTER)

    nxt = conn.execute("SELECT COALESCE(MAX(order_no), 0) + 1 FROM basket").fetchone()[0]
    db.write(conn,
             """INSERT OR REPLACE INTO basket
                (segment_id, source_id, clip_start_sec, clip_end_sec,
                 order_no, reason, created_at)
                VALUES (?,?,?,?,?,?,?)""",
             (segment_id, row["source_id"], start, end, nxt, reason,
              datetime.now().isoformat(timespec="seconds")))
    return nxt


def remove(conn, segment_id: int) -> None:
    db.write(conn, "DELETE FROM basket WHERE segment_id = ?", (segment_id,))


def get(conn, segment_id: int):
    return conn.execute(
        "SELECT * FROM basket WHERE segment_id = ?", (segment_id,)
    ).fetchone()


def update(conn, segment_id: int, **fields) -> None:
    allowed = {"clip_start_sec", "clip_end_sec", "order_no", "reason"}
    sets, args = [], []
    for k, v in fields.items():
        if k in allowed:
            sets.append(f"{k} = ?")
            args.append(v)
    if not sets:
        return
    args.append(segment_id)
    db.write(conn, f"UPDATE basket SET {', '.join(sets)} WHERE segment_id = ?", args)


def items(conn) -> list[dict]:
    """장바구니 전체. 제출 순서대로."""
    rows = conn.execute(
        """SELECT b.*, s.text, s.speaker_label, s.speaker, s.start_sec AS seg_start,
                  s.end_sec AS seg_end, s.page_no, s.occurred_at, s.confidence,
                  s.alt_mismatch, s.hallucination_risk,
                  src.path, src.kind, src.sha256, src.counterparty,
                  src.occurred_at AS src_occurred_at, src.is_my_conversation,
                  n.verified_by_ear, n.corrected_text, n.verdict
           FROM basket b
           JOIN segments s ON s.id = b.segment_id
           JOIN sources src ON src.id = b.source_id
           LEFT JOIN notes n ON n.segment_id = s.id
           ORDER BY COALESCE(src.occurred_at, ''), b.order_no"""
    ).fetchall()
    return [dict(r) for r in rows]


def clear(conn) -> None:
    db.write(conn, "DELETE FROM basket")


def warnings(conn) -> list[str]:
    """
    제출 전에 짚어야 할 것들.
    산출물을 만들기 전에 이 목록을 사용자에게 보여준다.
    """
    out = []
    rows = items(conn)
    if not rows:
        return ["발췌 장바구니가 비어 있습니다."]

    unverified = [r for r in rows if r["kind"] == "audio" and not r["verified_by_ear"]]
    if unverified:
        out.append(
            f"녹음 구간 {len(unverified)}건이 아직 **청취 확인되지 않았습니다.** "
            "AI 전사는 한국어에서 오인식이 적지 않으므로, 제출 전에 원본을 들어 "
            "확인하시기를 강력히 권합니다."
        )
    risky = [r for r in rows if r["alt_mismatch"] or r["hallucination_risk"]]
    if risky:
        out.append(f"전사가 의심스러운 구간 {len(risky)}건이 포함되어 있습니다.")

    illegal = [r for r in rows if r["is_my_conversation"] == "N"]
    if illegal:
        out.append(
            f"제3자 간 대화로 표시된 자료 {len(illegal)}건이 담겨 있습니다. "
            "통신비밀보호법 위반 소지가 있어 제출 시 오히려 불리해질 수 있습니다."
        )
    unknown = [r for r in rows
               if r["kind"] == "audio" and r["is_my_conversation"] == "UNKNOWN"]
    if unknown:
        out.append(f"적법성이 미확인된 녹음 {len(unknown)}건이 담겨 있습니다.")
    return out
