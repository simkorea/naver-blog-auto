# -*- coding: utf-8 -*-
"""
검색 — 키워드와 의미를 함께 쓴다.

두 갈래로 찾는다.
  키워드 검색  FTS5 trigram. "환불" 같이 정확한 단어를 찾을 때.
  의미 검색    BGE-M3 임베딩 + sqlite-vec. "고객이 계약을 인정하는 뉘앙스"
               처럼 표현이 다를 수 있는 상황을 찾을 때.

두 결과는 RRF(Reciprocal Rank Fusion)로 합친다. 점수 체계가 전혀 다른
두 순위를 안전하게 섞는 방법으로, 각 결과의 '순위'만 쓰기 때문에
한쪽 점수가 폭주해도 결과가 망가지지 않는다.

한국어 처리 주의점:
  trigram 인덱스는 3글자 미만 검색어에 MATCH를 쓸 수 없다.
  그래서 2글자 이하는 LIKE로 넘긴다 (trigram 인덱스가 LIKE도 가속한다).
"""
import re
import sqlite3

from .. import config, db

RRF_K = 60          # RRF 상수. 관례적으로 60을 쓴다.


# ─────────────────────────────────────────────────────────
# 검색어 처리
# ─────────────────────────────────────────────────────────
def _fts_escape(term: str) -> str:
    """FTS5 특수문자를 무력화한다 (사용자가 따옴표를 넣어도 깨지지 않게)."""
    return '"' + term.replace('"', '""') + '"'


def _split_terms(query: str) -> list[str]:
    """공백으로 나누되 따옴표로 묶인 구절은 하나로 본다."""
    terms = re.findall(r'"([^"]+)"|(\S+)', query.strip())
    return [a or b for a, b in terms if (a or b)]


def keyword_search(conn, query: str, limit: int = 200,
                   filters: dict = None) -> list[dict]:
    """
    키워드 검색. 여러 단어를 넣으면 모두 포함하는 구간을 찾는다(AND).

    3글자 이상 → FTS5 MATCH (빠름, 순위 있음)
    2글자 이하 → LIKE (trigram 인덱스가 가속)
    """
    terms = _split_terms(query)
    if not terms:
        return []

    short = [t for t in terms if len(t) < 3]
    long_ = [t for t in terms if len(t) >= 3]

    where, args = [], []
    if long_:
        match_expr = " AND ".join(_fts_escape(t) for t in long_)
        base = ("SELECT s.id AS segment_id, bm25(segments_fts) AS rank "
                "FROM segments_fts f JOIN segments s ON s.id = f.rowid "
                "WHERE segments_fts MATCH ?")
        args.append(match_expr)
    else:
        base = ("SELECT s.id AS segment_id, 0.0 AS rank "
                "FROM segments s WHERE 1=1")

    for t in short:
        where.append("s.text LIKE ?")
        args.append(f"%{t}%")

    sql, fargs = _apply_filters(base, where, args, filters, conn)
    sql += " ORDER BY rank LIMIT ?" if long_ else " LIMIT ?"
    fargs.append(limit)

    try:
        rows = conn.execute(sql, fargs).fetchall()
    except sqlite3.OperationalError:
        # 검색어에 FTS 문법 오류가 있으면 전부 LIKE로 대체
        return _like_only(conn, terms, limit, filters)

    return [{"segment_id": r["segment_id"], "rank": i + 1,
             "score": -(r["rank"] or 0)} for i, r in enumerate(rows)]


def _like_only(conn, terms, limit, filters):
    where = ["s.text LIKE ?" for _ in terms]
    args = [f"%{t}%" for t in terms]
    sql, fargs = _apply_filters(
        "SELECT s.id AS segment_id FROM segments s WHERE 1=1",
        where, args, filters, conn)
    sql += " LIMIT ?"
    fargs.append(limit)
    rows = conn.execute(sql, fargs).fetchall()
    return [{"segment_id": r["segment_id"], "rank": i + 1, "score": 0.0}
            for i, r in enumerate(rows)]


def _apply_filters(base_sql, where, args, filters, conn):
    """화자 · 기간 · 종류 · 신뢰도 · 적법성 조건을 덧붙인다."""
    filters = filters or {}
    where = list(where)
    args = list(args)

    if filters.get("speaker"):
        where.append("s.speaker_label = ?")
        args.append(filters["speaker"])
    if filters.get("source_ids"):
        marks = ",".join("?" * len(filters["source_ids"]))
        where.append(f"s.source_id IN ({marks})")
        args.extend(filters["source_ids"])
    if filters.get("kind"):
        where.append("s.source_id IN (SELECT id FROM sources WHERE kind = ?)")
        args.append(filters["kind"])
    if filters.get("date_from"):
        where.append("COALESCE(s.occurred_at, "
                     "(SELECT occurred_at FROM sources WHERE id = s.source_id)) >= ?")
        args.append(filters["date_from"])
    if filters.get("date_to"):
        where.append("COALESCE(s.occurred_at, "
                     "(SELECT occurred_at FROM sources WHERE id = s.source_id)) <= ?")
        args.append(filters["date_to"])
    if filters.get("min_confidence") is not None:
        where.append("(s.confidence IS NULL OR s.confidence >= ?)")
        args.append(filters["min_confidence"])
    if filters.get("only_low_confidence"):
        where.append("(s.alt_mismatch = 1 OR s.hallucination_risk = 1 "
                     "OR (s.confidence IS NOT NULL AND s.confidence < 0.6))")
    if filters.get("exclude_illegal", True):
        # 제3자 녹음으로 표시된 자료는 기본적으로 검색에서 뺀다
        where.append("s.source_id NOT IN "
                     "(SELECT id FROM sources WHERE is_my_conversation = 'N')")
    if filters.get("issue"):
        where.append("s.id IN (SELECT segment_id FROM tags WHERE tag = ?)")
        args.append(filters["issue"])

    sql = base_sql
    if where:
        joiner = " AND " if "WHERE" in base_sql else " WHERE "
        sql += joiner + " AND ".join(where)
    return sql, args


# ─────────────────────────────────────────────────────────
# 의미 검색
# ─────────────────────────────────────────────────────────
def semantic_search(conn, query: str, limit: int = 200,
                    filters: dict = None) -> list[dict]:
    """
    문장으로 검색한다. 임베딩 모델이나 sqlite-vec가 없으면 빈 목록을 돌려주고,
    호출한 쪽은 키워드 결과만 쓰게 된다.
    """
    from .embed import embed_query, embedder_ready
    if not embedder_ready() or not db.vec_available(conn):
        return []

    vec = embed_query(query)
    if vec is None:
        return []

    try:
        rows = conn.execute(
            """SELECT segment_id, distance
               FROM vec_segments
               WHERE embedding MATCH ? AND k = ?
               ORDER BY distance""",
            (_serialize(vec), limit),
        ).fetchall()
    except sqlite3.OperationalError:
        return []

    ids = [r["segment_id"] for r in rows]
    if not ids and filters:
        return []
    allowed = _filter_ids(conn, ids, filters)
    out = []
    for i, r in enumerate(rows):
        if r["segment_id"] in allowed:
            out.append({"segment_id": r["segment_id"], "rank": i + 1,
                        "score": -float(r["distance"])})
    return out


def _serialize(vec):
    import struct
    return struct.pack(f"{len(vec)}f", *vec)


def _filter_ids(conn, ids, filters):
    """의미 검색 결과에 같은 필터를 적용한다."""
    if not ids:
        return set()
    marks = ",".join("?" * len(ids))
    sql, args = _apply_filters(
        f"SELECT s.id AS segment_id FROM segments s WHERE s.id IN ({marks})",
        [], list(ids), filters, conn)
    return {r["segment_id"] for r in conn.execute(sql, args).fetchall()}


# ─────────────────────────────────────────────────────────
# 융합
# ─────────────────────────────────────────────────────────
def search(conn, query: str, limit: int = 50, filters: dict = None,
           use_semantic: bool = True) -> list[dict]:
    """
    키워드 + 의미 검색을 RRF로 합친 최종 결과.
    각 항목에는 어느 쪽에서 걸렸는지(matched_by)가 표시된다.
    """
    kw = keyword_search(conn, query, limit=limit * 4, filters=filters)
    sem = semantic_search(conn, query, limit=limit * 4, filters=filters) \
        if use_semantic else []

    scores, origin = {}, {}
    for group, name in ((kw, "키워드"), (sem, "의미")):
        for item in group:
            sid = item["segment_id"]
            scores[sid] = scores.get(sid, 0.0) + 1.0 / (RRF_K + item["rank"])
            origin.setdefault(sid, []).append(name)

    ranked = sorted(scores.items(), key=lambda x: -x[1])[:limit]
    if not ranked:
        return []

    ids = [sid for sid, _ in ranked]
    detail = fetch_segments(conn, ids)
    by_id = {d["id"]: d for d in detail}

    out = []
    for sid, score in ranked:
        d = by_id.get(sid)
        if not d:
            continue
        d = dict(d)
        d["rrf_score"] = round(score, 5)
        d["matched_by"] = "+".join(origin.get(sid, []))
        out.append(d)
    return out


# ─────────────────────────────────────────────────────────
# 구간 상세
# ─────────────────────────────────────────────────────────
def fetch_segments(conn, ids: list[int]) -> list[dict]:
    """구간 정보에 원본 정보와 확인 기록을 붙여 돌려준다."""
    if not ids:
        return []
    marks = ",".join("?" * len(ids))
    rows = conn.execute(
        f"""SELECT s.*,
                   src.path, src.kind, src.sha256, src.counterparty,
                   src.occurred_at AS src_occurred_at, src.duration_sec,
                   src.is_my_conversation, src.occurred_at_est,
                   n.verdict, n.memo AS note_memo, n.verified_by_ear,
                   n.corrected_text,
                   (SELECT 1 FROM basket b WHERE b.segment_id = s.id) AS in_basket
            FROM segments s
            JOIN sources src ON src.id = s.source_id
            LEFT JOIN notes n ON n.segment_id = s.id
            WHERE s.id IN ({marks})""",
        ids,
    ).fetchall()
    return [dict(r) for r in rows]


def context(conn, segment_id: int, before: int = 3, after: int = 3) -> list[dict]:
    """
    앞뒤 맥락을 가져온다.

    증거에서 맥락은 필수다. 한 문장만 떼어내면 의미가 뒤집힐 수 있다.
    """
    row = conn.execute(
        "SELECT source_id, seq FROM segments WHERE id = ?", (segment_id,)
    ).fetchone()
    if not row:
        return []
    rows = conn.execute(
        """SELECT * FROM segments
           WHERE source_id = ? AND seq BETWEEN ? AND ?
           ORDER BY seq""",
        (row["source_id"], row["seq"] - before, row["seq"] + after),
    ).fetchall()
    return [dict(r) for r in rows]


def highlight(text: str, query: str) -> str:
    """검색어에 ** 표시를 붙인다 (Streamlit 마크다운에서 굵게 표시)."""
    terms = sorted(_split_terms(query), key=len, reverse=True)
    out = text
    for t in terms:
        if not t:
            continue
        out = re.sub(f"({re.escape(t)})", r"**\1**", out, flags=re.IGNORECASE)
    return out


def timecode(sec) -> str:
    """초 → 00:12:34 형식. 증거 위치 표기의 기본 단위."""
    if sec is None:
        return ""
    sec = int(float(sec))
    return f"{sec // 3600:02d}:{(sec % 3600) // 60:02d}:{sec % 60:02d}"


def speakers(conn) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT speaker_label FROM segments "
        "WHERE speaker_label IS NOT NULL ORDER BY speaker_label"
    ).fetchall()
    return [r[0] for r in rows]
