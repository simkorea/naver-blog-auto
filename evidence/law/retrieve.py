# -*- coding: utf-8 -*-
"""
증거 구간 → 관련 조문·판례 찾기.

증거를 검색하는 것과 같은 방식(키워드 + 의미, RRF 융합)을 법령에도 쓴다.
찾아낸 원문만이 코멘트의 근거가 되며, 모델 기억에서 나온 법은 쓰지 않는다.
"""
import sqlite3

from .. import db
from ..search.hybrid import RRF_K, _fts_escape, _split_terms


def _keyword(conn, query: str, limit: int) -> list[tuple]:
    """
    키워드로 조문·판례를 찾는다.

    법률 용어는 "설명", "고지", "동의"처럼 두 글자가 많은데
    trigram MATCH는 3글자 미만을 못 받는다. 그래서 짧은 용어는
    LIKE로 따로 훑어 합친다. 이게 없으면 정작 중요한 조문을 놓친다.
    """
    terms = _split_terms(query)
    long_ = [t for t in terms if len(t) >= 3]
    short = [t for t in terms if 2 <= len(t) < 3]

    ranked = []
    if long_:
        expr = " OR ".join(_fts_escape(t) for t in long_)
        try:
            rows = conn.execute(
                "SELECT ref_type, ref_id, bm25(law_fts) AS rank FROM law_fts "
                "WHERE law_fts MATCH ? ORDER BY rank LIMIT ?", (expr, limit)
            ).fetchall()
            ranked = [(r["ref_type"], r["ref_id"]) for r in rows]
        except sqlite3.OperationalError:
            ranked = []

    if short:
        where = " OR ".join("body LIKE ?" for _ in short)
        rows = conn.execute(
            f"SELECT ref_type, ref_id FROM law_fts WHERE {where} LIMIT ?",
            [f"%{t}%" for t in short] + [limit],
        ).fetchall()
        for r in rows:
            key = (r["ref_type"], r["ref_id"])
            if key not in ranked:
                ranked.append(key)

    return [(t, i, n + 1) for n, (t, i) in enumerate(ranked)]


def _semantic(conn, query: str, limit: int) -> list[tuple]:
    from ..search import embed
    if not embed.embedder_ready() or not db.vec_available(conn):
        return []
    vec = embed.embed_query(query)
    if vec is None:
        return []
    try:
        rows = conn.execute(
            "SELECT rowid, distance FROM vec_law "
            "WHERE embedding MATCH ? AND k = ? ORDER BY distance",
            (embed.serialize(vec), limit)).fetchall()
    except sqlite3.OperationalError:
        return []
    out = []
    for i, r in enumerate(rows):
        ref = conn.execute("SELECT ref_type, ref_id FROM law_fts WHERE rowid = ?",
                           (r["rowid"],)).fetchone()
        if ref:
            out.append((ref["ref_type"], ref["ref_id"], i + 1))
    return out


def find(conn, query: str, limit: int = 6) -> list[dict]:
    """관련 조문·판례를 찾아 원문과 함께 돌려준다."""
    scores = {}
    for group in (_keyword(conn, query, limit * 4),
                  _semantic(conn, query, limit * 4)):
        for ref_type, ref_id, rank in group:
            key = (ref_type, ref_id)
            scores[key] = scores.get(key, 0.0) + 1.0 / (RRF_K + rank)

    ranked = sorted(scores.items(), key=lambda x: -x[1])[:limit]
    return [dict(fetch(conn, t, i), score=round(s, 5))
            for (t, i), s in ranked if fetch(conn, t, i)]


def fetch(conn, ref_type: str, ref_id: int) -> dict | None:
    """근거 하나의 원문. 인용문은 언제나 여기서 나온다."""
    if ref_type == "article":
        r = conn.execute("SELECT * FROM law_articles WHERE id = ?", (ref_id,)).fetchone()
        if not r:
            return None
        label = f"{r['law_name']} {r['article_no']}"
        if r["article_title"]:
            label += f" ({r['article_title']})"
        return {"ref_type": "article", "ref_id": r["id"], "label": label,
                "body": r["body"], "url": r["source_url"],
                "extra": f"시행 {r['enforce_date']}" if r["enforce_date"] else ""}

    r = conn.execute("SELECT * FROM precedents WHERE id = ?", (ref_id,)).fetchone()
    if not r:
        return None
    label = f"{r['court'] or '법원'} {r['decided_on'] or ''} 선고 {r['case_no']}"
    body = "\n\n".join(filter(None, [
        f"[판시사항]\n{r['holding']}" if r["holding"] else "",
        f"[판결요지]\n{r['summary']}" if r["summary"] else "",
    ])) or (r["body"] or "")[:2000]
    return {"ref_type": "precedent", "ref_id": r["id"], "label": label.strip(),
            "body": body, "url": r["source_url"], "extra": r["case_name"] or ""}


def for_issue(conn, issue_name: str, sample_texts: list[str] = None,
              limit: int = 6) -> list[dict]:
    """쟁점 이름과 실제 발언을 함께 넣어 더 정확히 찾는다."""
    query = issue_name
    if sample_texts:
        query += " " + " ".join(t[:200] for t in sample_texts[:3])
    return find(conn, query, limit=limit)
