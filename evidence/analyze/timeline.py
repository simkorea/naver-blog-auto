# -*- coding: utf-8 -*-
"""
타임라인 — 흩어진 자료를 하나의 시간축에 올린다.

소송에서 시간 순서는 그 자체로 증거다.
"고객은 3월 14일에 설명을 들었다고 했는데, 3월 20일부터 못 들었다고
말을 바꿨다" — 이런 것은 시간순으로 늘어놓아야만 보인다.

추정 시각은 반드시 구분해 표시한다. 파일 수정 시각으로 추정한 것을
확정 시각처럼 제출하면, 그 하나 때문에 전체 신빙성이 흔들린다.
"""
from datetime import datetime

from .. import db


def events(conn, issue: str = None, speaker: str = None,
           only_tagged: bool = False, limit: int = 500) -> list[dict]:
    """
    시간순 사건 목록.

    녹음 구간·카톡 메시지·문서·메일을 한 줄씩 섞어 정렬한다.
    """
    sql = """
        SELECT s.id, s.text, s.speaker_label, s.speaker, s.start_sec, s.end_sec,
               s.page_no, s.confidence, s.alt_mismatch, s.mismatch_kind,
               s.hallucination_risk, s.speaker_uncertain,
               COALESCE(s.occurred_at, src.occurred_at) AS at,
               src.occurred_at_est, src.path, src.kind, src.counterparty,
               src.is_my_conversation,
               n.verified_by_ear, n.verdict, n.corrected_text,
               (SELECT tag FROM tags WHERE segment_id = s.id
                  AND category = '쟁점' LIMIT 1) AS issue,
               (SELECT tag FROM tags WHERE segment_id = s.id
                  AND category = '유불리' LIMIT 1) AS stance,
               (SELECT 1 FROM basket b WHERE b.segment_id = s.id) AS in_basket
        FROM segments s
        JOIN sources src ON src.id = s.source_id
        LEFT JOIN notes n ON n.segment_id = s.id
        WHERE src.is_my_conversation != 'N'
    """
    args = []
    if issue:
        sql += (" AND EXISTS (SELECT 1 FROM tags t WHERE t.segment_id = s.id "
                "AND t.category = '쟁점' AND t.tag = ?)")
        args.append(issue)
    if speaker:
        sql += " AND s.speaker_label = ?"
        args.append(speaker)
    if only_tagged:
        sql += " AND EXISTS (SELECT 1 FROM tags t WHERE t.segment_id = s.id)"

    sql += """ ORDER BY CASE WHEN at IS NULL THEN 1 ELSE 0 END,
                        at, src.id, s.seq LIMIT ?"""
    args.append(limit)
    return [dict(r) for r in conn.execute(sql, args).fetchall()]


def by_day(rows: list[dict]) -> list[tuple]:
    """날짜별로 묶는다. 화면과 문서 모두 이 형태를 쓴다."""
    groups, order = {}, []
    for r in rows:
        at = r.get("at")
        day = (at or "")[:10] or "날짜 미상"
        if day not in groups:
            groups[day] = []
            order.append(day)
        groups[day].append(r)
    return [(d, groups[d]) for d in order]


def contradictions(conn) -> list[dict]:
    """
    상대방 진술의 앞뒤 모순을 찾는다.

    같은 쟁점에서 '유리'로 분류된 발언과 '불리'로 분류된 발언이
    같은 사람 입에서 시차를 두고 나왔다면, 그것은 말을 바꾼 것이다.
    이 사건에서 가장 강력한 증거가 될 수 있다.
    """
    rows = conn.execute(
        """SELECT s.id, s.text, s.speaker_label,
                  COALESCE(s.occurred_at, src.occurred_at) AS at,
                  s.start_sec, src.path, src.kind,
                  t.tag AS issue, u.tag AS stance
           FROM segments s
           JOIN sources src ON src.id = s.source_id
           JOIN tags t ON t.segment_id = s.id AND t.category = '쟁점'
           JOIN tags u ON u.segment_id = s.id AND u.category = '유불리'
           WHERE src.is_my_conversation != 'N'
             AND s.speaker_label IS NOT NULL
             AND u.tag IN ('유리', '불리')
           ORDER BY at"""
    ).fetchall()

    # 사람별로 '유리'와 '불리' 발언을 모은다
    by_person = {}
    for r in rows:
        by_person.setdefault(r["speaker_label"], {"유리": [], "불리": []})
        by_person[r["speaker_label"]][r["stance"]].append(dict(r))

    out = []
    for person, buckets in by_person.items():
        # 내 발언의 유불리는 모순이 아니다. 상대방 진술만 본다.
        if person in ("나", "본인"):
            continue
        for good in buckets["유리"]:
            for bad in buckets["불리"]:
                if not good["at"] or not bad["at"]:
                    continue
                if good["at"] >= bad["at"]:
                    continue        # 인정이 먼저, 부인이 나중일 때만 모순
                out.append({
                    "person": person,
                    "earlier": good,
                    "later": bad,
                    "days": _daygap(good["at"], bad["at"]),
                })
    # 시차가 짧은(=대비가 선명한) 것부터
    out.sort(key=lambda x: (x["person"], x["days"]))
    return out


def _daygap(a: str, b: str) -> int:
    try:
        d1 = datetime.fromisoformat(a[:19])
        d2 = datetime.fromisoformat(b[:19])
        return abs((d2 - d1).days)
    except Exception:
        return 0


def summary(conn) -> dict:
    rows = events(conn, limit=100000)
    dated = [r for r in rows if r.get("at")]
    return {
        "events": len(rows),
        "dated": len(dated),
        "estimated": sum(1 for r in dated if r.get("occurred_at_est")),
        "first": dated[0]["at"][:16].replace("T", " ") if dated else None,
        "last": dated[-1]["at"][:16].replace("T", " ") if dated else None,
        "contradictions": len(contradictions(conn)),
    }
