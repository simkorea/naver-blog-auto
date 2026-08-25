# -*- coding: utf-8 -*-
"""
증거 위치 색인표 — "어느 파일 몇 분 몇 초에 이 말이 있다".

이 문서 하나면 원본을 그대로 넘겨도 받는 사람이 바로 그 지점을 찾는다.
발췌본을 만들지 않아도 되는 경우가 많고, 발췌본을 만들더라도
이 표가 원본과 발췌본을 잇는 대응표가 된다.
"""
from pathlib import Path

from ..search.hybrid import timecode


def rows_from_basket(conn) -> list[dict]:
    from .. import basket
    return _build(conn, basket.items(conn))


def rows_from_segments(conn, segment_ids: list[int]) -> list[dict]:
    if not segment_ids:
        return []
    marks = ",".join("?" * len(segment_ids))
    rows = conn.execute(
        f"""SELECT s.*, src.path, src.kind, src.sha256, src.counterparty,
                   src.occurred_at AS src_occurred_at, src.is_my_conversation,
                   n.verified_by_ear, n.corrected_text, n.verdict,
                   b.clip_start_sec, b.clip_end_sec, b.reason
            FROM segments s
            JOIN sources src ON src.id = s.source_id
            LEFT JOIN notes n ON n.segment_id = s.id
            LEFT JOIN basket b ON b.segment_id = s.id
            WHERE s.id IN ({marks})
            ORDER BY COALESCE(src.occurred_at, ''), s.seq""",
        segment_ids,
    ).fetchall()
    return _build(conn, [dict(r) for r in rows])


def _build(conn, items: list[dict]) -> list[dict]:
    """색인표 한 줄씩 조립한다."""
    out = []
    for i, it in enumerate(items, 1):
        kind = it.get("kind")
        start = it.get("clip_start_sec")
        end = it.get("clip_end_sec")
        if start is None:
            start = it.get("seg_start", it.get("start_sec"))
            end = it.get("seg_end", it.get("end_sec"))

        # 위치 표기 — 종류마다 다르다
        if kind == "audio" and start is not None:
            location = f"{timecode(start)} ~ {timecode(end)}"
            length = f"{(end or 0) - (start or 0):.0f}초"
        elif it.get("page_no"):
            location = f"{it['page_no']}쪽"
            length = ""
        else:
            location = (it.get("occurred_at") or it.get("src_occurred_at") or "")[:16].replace("T", " ")
            length = ""

        # 확인 상태 — 청취 전 구간을 확정 사실처럼 내보내지 않기 위한 표시
        if kind != "audio":
            verified = "문자기록"
        elif it.get("verified_by_ear"):
            verified = "청취 확인"
        else:
            verified = "미검증"

        conf = it.get("confidence")
        if kind != "audio":
            reliability = "—"
        elif it.get("alt_mismatch"):
            reliability = f"확인 필요 ({it.get('mismatch_kind') or '전사 불일치'})"
        elif it.get("hallucination_risk"):
            reliability = "확인 필요 (환청 의심)"
        elif conf is None:
            reliability = "—"
        elif conf >= 0.8:
            reliability = "높음"
        elif conf >= 0.6:
            reliability = "보통"
        else:
            reliability = "낮음"

        # 청취 후 고친 내용이 있으면 그것이 진짜다
        text = it.get("corrected_text") or it.get("text") or ""

        out.append({
            "no": i,
            "file": Path(it["path"]).name,
            "path": it["path"],
            "kind": kind,
            "when": (it.get("occurred_at") or it.get("src_occurred_at") or "")[:16].replace("T", " "),
            "location": location,
            "length": length,
            "start_sec": start,
            "end_sec": end,
            "speaker": it.get("speaker_label") or it.get("speaker") or "",
            "text": text.replace("\n", " ").strip(),
            "issue": _issue_of(conn, it.get("segment_id") or it.get("id")),
            "stance": it.get("verdict") or _stance_of(conn, it.get("segment_id") or it.get("id")),
            "reliability": reliability,
            "verified": verified,
            "reason": it.get("reason") or "",
            "sha256": it.get("sha256", ""),
            "legal_flag": it.get("is_my_conversation"),
            "segment_id": it.get("segment_id") or it.get("id"),
        })
    return out


def _issue_of(conn, segment_id):
    if not segment_id:
        return ""
    r = conn.execute(
        "SELECT group_concat(tag, ', ') FROM tags "
        "WHERE segment_id = ? AND category = '쟁점'", (segment_id,)
    ).fetchone()
    return r[0] or "" if r else ""


def _stance_of(conn, segment_id):
    if not segment_id:
        return ""
    r = conn.execute(
        "SELECT tag FROM tags WHERE segment_id = ? AND category = '유불리' LIMIT 1",
        (segment_id,)
    ).fetchone()
    return r[0] if r else ""


def warnings(rows: list[dict]) -> list[str]:
    """색인표를 내보내기 전에 짚어야 할 것."""
    out = []
    unver = [r for r in rows if r["verified"] == "미검증"]
    if unver:
        out.append(
            f"녹음 구간 {len(unver)}건이 청취 확인되지 않았습니다. "
            "AI 전사는 오인식이 있을 수 있으므로 제출 전에 원본을 들어 확인하세요. "
            "(문서에는 '미검증'으로 표시됩니다)"
        )
    risky = [r for r in rows if "확인 필요" in r["reliability"]]
    if risky:
        kinds = {r["reliability"] for r in risky}
        out.append(f"전사가 의심스러운 구간 {len(risky)}건이 있습니다 — {', '.join(kinds)}")
    illegal = [r for r in rows if r["legal_flag"] == "N"]
    if illegal:
        out.append(f"제3자 녹음으로 표시된 자료 {len(illegal)}건이 포함되어 있습니다.")
    return out
