# -*- coding: utf-8 -*-
"""
법령·판례 적재 — 필요한 법만 골라 원문을 내려받아 둔다.

법 전체를 넣을 필요가 없다. 이 사건에서 다투어질 법령만 골라
조문 원문을 받아 두고, 그것만 근거로 쓴다.

적재한 뒤에는 증거 검색에 쓰는 것과 **같은 검색 엔진**을 그대로 쓴다.
인프라를 두 벌 만들지 않는다.
"""
from datetime import datetime
from pathlib import Path

from .. import config, db, integrity
from . import client

# 부동산 상담 관련 소송에서 통상 다투어지는 범위.
# 사용자가 자기 사건에 맞게 고쳐 쓰는 출발점이다.
DEFAULT_YAML = """\
# ════════════════════════════════════════════════════════
#  이 사건에서 참고할 법령·판례 범위
#
#  · 여기 적은 법령의 조문 원문을 법제처에서 내려받아 근거로 씁니다.
#  · 불리한 쪽 법령도 반드시 넣으세요. 상대가 어느 조문으로 올지
#    먼저 알아야 방어할 수 있습니다.
#  · 법령명은 정식 명칭으로 적어야 찾습니다.
# ════════════════════════════════════════════════════════

법령:
  - 민법                              # 채무불이행·손해배상·불법행위·계약 해제
  - 공인중개사법                        # 확인·설명의무, 손해배상책임
  - 표시·광고의 공정화에 관한 법률          # 허위·과장광고
  - 약관의 규제에 관한 법률
  - 통신비밀보호법                       # 녹음 증거능력

판례_검색어:
  - 중개업자 확인설명의무
  - 설명의무 위반 손해배상
  - 분양 광고 기망
  - 과실상계
  - 계약 해제 원상회복
"""


def ensure_yaml() -> Path:
    if not config.LAW_SCOPE_YAML.exists():
        config.LAW_SCOPE_YAML.write_text(DEFAULT_YAML, encoding="utf-8")
    return config.LAW_SCOPE_YAML


def load_scope() -> dict:
    ensure_yaml()
    import yaml
    data = yaml.safe_load(config.LAW_SCOPE_YAML.read_text(encoding="utf-8")) or {}
    return {
        "laws": [str(x).strip() for x in (data.get("법령") or []) if str(x).strip()],
        "queries": [str(x).strip() for x in (data.get("판례_검색어") or []) if str(x).strip()],
    }


# ─────────────────────────────────────────────────────────
# 적재
# ─────────────────────────────────────────────────────────
def load_law(conn, law_name: str) -> int:
    """법령 하나의 조문을 전부 받아 저장한다."""
    articles = client.fetch_articles(law_name)
    if not articles:
        return 0
    now = datetime.now().isoformat(timespec="seconds")
    db.write_many(
        conn,
        """INSERT INTO law_articles
           (law_name, law_id, article_no, article_title, body,
            enforce_date, source_url, fetched_at)
           VALUES (?,?,?,?,?,?,?,?)
           ON CONFLICT(law_name, article_no) DO UPDATE SET
             body = excluded.body,
             article_title = excluded.article_title,
             enforce_date = excluded.enforce_date,
             fetched_at = excluded.fetched_at""",
        [(a["law_name"], a["law_id"], a["article_no"], a["article_title"],
          a["body"], a["enforce_date"], a["source_url"], now) for a in articles],
    )
    integrity.log("law_loaded", law=law_name, articles=len(articles))
    return len(articles)


def load_precedents(conn, query: str, limit: int = 8) -> int:
    """검색어로 판례를 찾아 본문까지 받아 저장한다."""
    found = client.search_precedents(query, limit=limit)
    now = datetime.now().isoformat(timespec="seconds")
    saved = 0
    for p in found:
        exists = conn.execute("SELECT id FROM precedents WHERE case_no = ?",
                              (p["case_no"],)).fetchone()
        if exists:
            continue
        detail = client.fetch_precedent(prec_id=p["prec_id"], case_no=p["case_no"])
        if not detail:
            continue
        db.write(conn,
                 """INSERT OR IGNORE INTO precedents
                    (case_no, court, decided_on, case_name, holding, summary,
                     body, source_url, fetched_at)
                    VALUES (?,?,?,?,?,?,?,?,?)""",
                 (detail["case_no"], detail["court"], detail["decided_on"],
                  detail["case_name"], detail["holding"], detail["summary"],
                  detail["body"], detail["source_url"], now))
        saved += 1
    integrity.log("precedents_loaded", query=query, saved=saved, found=len(found))
    return saved


def build_index(conn, progress=None) -> dict:
    """
    적재한 조문·판례를 검색 가능하게 만든다.
    키워드(FTS5)는 항상, 의미 검색(임베딩)은 모델이 있을 때만.
    """
    db.write(conn, "DELETE FROM law_fts")

    rows = []
    for a in conn.execute(
            "SELECT id, law_name, article_no, article_title, body FROM law_articles"):
        head = f"{a['law_name']} {a['article_no']}"
        if a["article_title"]:
            head += f" ({a['article_title']})"
        rows.append((f"{head}\n{a['body']}", "article", a["id"]))
    for p in conn.execute(
            "SELECT id, case_no, case_name, holding, summary FROM precedents"):
        text = "\n".join(filter(None, [
            f"{p['case_no']} {p['case_name'] or ''}", p["holding"], p["summary"]]))
        rows.append((text, "precedent", p["id"]))

    if rows:
        db.write_many(conn,
                      "INSERT INTO law_fts(body, ref_type, ref_id) VALUES (?,?,?)",
                      rows)

    embedded = 0
    try:
        from ..search import embed
        if embed.embedder_ready() and db.vec_available(conn):
            vecs = embed.embed_texts([r[0][:2000] for r in rows], progress=progress)
            if vecs:
                fts_ids = [r[0] for r in conn.execute(
                    "SELECT rowid FROM law_fts ORDER BY rowid").fetchall()]
                db.write_many(
                    conn,
                    "INSERT OR REPLACE INTO vec_law(rowid, embedding) VALUES (?,?)",
                    [(rid, embed.serialize(v)) for rid, v in zip(fts_ids, vecs)])
                embedded = len(vecs)
    except Exception:
        pass

    return {"indexed": len(rows), "embedded": embedded}


def sync(conn, progress=None) -> dict:
    """law_scope.yaml에 적힌 것을 전부 받아 색인까지 만든다."""
    scope = load_scope()
    result = {"laws": {}, "precedents": {}, "errors": []}

    total = len(scope["laws"]) + len(scope["queries"])
    step = 0

    for law in scope["laws"]:
        step += 1
        if progress:
            progress(step, total, f"법령 · {law}")
        try:
            result["laws"][law] = load_law(conn, law)
        except Exception as e:
            result["errors"].append(f"{law}: {e}")

    for q in scope["queries"]:
        step += 1
        if progress:
            progress(step, total, f"판례 · {q}")
        try:
            result["precedents"][q] = load_precedents(conn, q)
        except Exception as e:
            result["errors"].append(f"{q}: {e}")

    result["index"] = build_index(conn)
    return result


def stats(conn) -> dict:
    def one(sql):
        return conn.execute(sql).fetchone()[0]
    return {
        "articles": one("SELECT count(*) FROM law_articles"),
        "laws": one("SELECT count(DISTINCT law_name) FROM law_articles"),
        "precedents": one("SELECT count(*) FROM precedents"),
        "indexed": one("SELECT count(*) FROM law_fts"),
    }
