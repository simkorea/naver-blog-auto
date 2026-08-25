# -*- coding: utf-8 -*-
"""
쟁점 키워드 매칭 — 유리한 발언과 불리한 발언을 함께 찾는다.

불리한 것도 찾는 이유
  방어의 핵심은 상대가 꺼낼 카드를 먼저 아는 것이다.
  내게 유리한 말만 모으면, 상대가 들고 올 발언에 법정에서 처음 놀란다.
  그래서 사전에 '불리 가능' 항목을 함께 넣고 똑같이 표시한다.

사전은 사용자가 직접 편집한다(keywords.yaml). 사건마다 쟁점이 다르므로
프로그램이 정해줄 수 없고, 정해줘서도 안 된다.
"""
import re
from pathlib import Path

from .. import config, db, integrity

# 부동산 상담 관련 소송에서 통상 다투어지는 쟁점들.
# 사용자가 자기 사건에 맞게 고쳐 쓰는 출발점이다.
DEFAULT_YAML = """\
# ════════════════════════════════════════════════════════
#  쟁점 키워드 사전
#
#  · 이 파일을 고치면 다음 분석부터 바로 반영됩니다.
#  · 표현은 **어간**으로 짧게 적으세요. 한국어는 어미가 계속 바뀝니다.
#      "못 들었"  → "못 들은/못 들었다/못 들어서" 를 놓칩니다
#      "못 들"    → 위 전부를 잡습니다
#  · 띄어쓰기는 신경 쓰지 않아도 됩니다 ("못들"과 "못 들"은 같게 취급).
#  · '불리' 항목을 반드시 채우세요. 상대가 어떤 발언을 들고 올지
#    먼저 알아야 방어할 수 있습니다.
# ════════════════════════════════════════════════════════

쟁점:
  - 이름: 설명의무 이행
    설명: 내가 계약 내용을 제대로 설명했는가
    유리:
      [설명드렸, 설명해드렸, 안내드렸, 말씀드렸, 알려드렸, 보여드렸,
       확인하셨, 확인시켜, 설명서, 확인설명, 서명하셨, 읽어보셨,
       자료 드렸, 자료드렸, 고지드렸]
    상대방_인정:
      [들었어, 들었습니다, 알고 있었, 알고있었, 그렇게 알고, 설명해주셨,
       설명 들, 네 맞아, 확인했, 봤어, 이해했, 이해합니다, 인지하고]

  - 이름: 고객 동의·승낙
    설명: 상대방이 진행에 동의한 정황
    유리:
      [알겠습니다, 알겠어, 진행해주, 진행하겠, 그렇게 해주, 좋습니다,
       동의합니다, 동의해, 하겠습니다, 부탁드립니다, 계약할, 계약하겠]

  - 이름: 약속·확약
    설명: 내가 과도한 약속을 한 것으로 해석될 수 있는 표현 (불리 가능)
    불리:
      [보장, 무조건, 확실히, 틀림없, 책임지겠, 책임질, 손해 안,
       반드시 오, 무조건 오, 제가 책임, 원금 보장, 절대]

  - 이름: 설명 누락 주장
    설명: 상대방이 설명을 못 들었다고 주장하는 발언 (불리 가능)
    불리:
      [못 들, 안 들, 못들, 안들, 얘기 안, 말 안 했, 말씀 안,
       설명 안, 설명을 안, 설명 못, 몰랐, 처음 듣, 그런 말 없,
       들은 적 없, 알려주지 않, 안 알려]

  - 이름: 상대방 태도 변화
    설명: 언제부터 문제 삼기 시작했는지 — 그 시점이 중요하다
    중립:
      [취소, 환불, 해지, 못하겠, 안 하겠, 안하겠, 사기, 신고,
       소송, 변호사, 내용증명, 고소, 손해배상, 배상, 물어내]

  - 이름: 금전 거래
    설명: 계약금·중도금 흐름
    중립:
      [계약금, 중도금, 잔금, 입금, 송금, 이체, 영수증, 세금계산서,
       위약금, 수수료, 중개보수, 환불금, 반환]

  - 이름: 일정·기한
    설명: 약속한 날짜와 실제 이행 시점
    중립:
      [까지, 언제, 기한, 마감, 일정, 연기, 미루, 지연, 늦어]
"""


def _squeeze(text: str) -> str:
    """
    띄어쓰기를 지운다.

    한국어는 같은 말을 "못 들었"과 "못들었"으로 다 쓴다.
    사전에 둘 다 적게 하는 대신, 비교할 때 공백을 지워 맞춘다.
    """
    return re.sub(r"\s+", "", text or "")


def _contains(text: str, squeezed: str, term: str) -> bool:
    """원문 그대로 또는 공백을 지운 상태로 하나라도 걸리면 매칭."""
    return term in text or _squeeze(term) in squeezed


def ensure_yaml() -> Path:
    """사전이 없으면 기본값으로 만들어 준다."""
    if not config.KEYWORDS_YAML.exists():
        config.KEYWORDS_YAML.write_text(DEFAULT_YAML, encoding="utf-8")
    return config.KEYWORDS_YAML


def load() -> list[dict]:
    """사전을 읽는다. 각 쟁점: {이름, 설명, 표현목록[(표현, 유불리)]}"""
    ensure_yaml()
    try:
        import yaml
        data = yaml.safe_load(config.KEYWORDS_YAML.read_text(encoding="utf-8")) or {}
    except Exception as e:
        raise RuntimeError(f"쟁점 사전을 읽지 못했습니다: {e}")

    issues = []
    for item in (data.get("쟁점") or []):
        terms = []
        for stance_key, stance in (("유리", "유리"), ("상대방_인정", "유리"),
                                   ("불리", "불리"), ("중립", "중립")):
            for t in (item.get(stance_key) or []):
                t = str(t).strip()
                if t:
                    terms.append((t, stance))
        if item.get("이름") and terms:
            issues.append({
                "name": str(item["이름"]).strip(),
                "description": str(item.get("설명") or "").strip(),
                "terms": terms,
            })
    return issues


def sync_issues(conn, issues: list[dict]) -> None:
    """쟁점 목록을 DB에 반영한다."""
    for it in issues:
        db.write(conn,
                 "INSERT INTO issues(name, description) VALUES (?, ?) "
                 "ON CONFLICT(name) DO UPDATE SET description = excluded.description",
                 (it["name"], it["description"]))


def scan(conn, progress=None) -> dict:
    """
    모든 구간을 쟁점 사전과 대조해 태그를 붙인다.

    이미 붙인 keyword 태그는 지우고 다시 만든다
    (사전을 고치면 결과가 바로 반영되어야 하므로).
    """
    issues = load()
    if not issues:
        return {"issues": 0, "tags": 0}
    sync_issues(conn, issues)

    db.write(conn, "DELETE FROM tags WHERE engine = 'keyword'")

    rows = conn.execute("SELECT id, text FROM segments").fetchall()
    found = []
    for i, r in enumerate(rows, 1):
        text = r["text"] or ""
        squeezed = _squeeze(text)
        for it in issues:
            hits = [(t, stance) for t, stance in it["terms"]
                    if _contains(text, squeezed, t)]
            if not hits:
                continue
            # 한 쟁점 안에서 유리/불리가 동시에 걸리면 불리를 우선한다.
            # 유리하다고 넘겼다가 법정에서 뒤집히는 것이 최악이다.
            stances = {s for _, s in hits}
            stance = "불리" if "불리" in stances else (
                "유리" if "유리" in stances else "중립")
            matched = ", ".join(t for t, _ in hits[:5])
            found.append((r["id"], "쟁점", it["name"], len(hits), "keyword", matched))
            found.append((r["id"], "유불리", stance, len(hits), "keyword", matched))
        if progress and i % 200 == 0:
            progress(i, len(rows))

    if found:
        db.write_many(
            conn,
            "INSERT OR IGNORE INTO tags(segment_id, category, tag, score, engine, matched) "
            "VALUES (?,?,?,?,?,?)",
            found,
        )
    integrity.log("keyword_scan", issues=len(issues), tags=len(found))
    return {"issues": len(issues), "tags": len(found)}


def by_issue(conn) -> list[dict]:
    """쟁점별 집계 — 어디에 증거가 몰려 있는지 한눈에."""
    rows = conn.execute(
        """SELECT t.tag AS issue, count(DISTINCT t.segment_id) AS n,
                  SUM(CASE WHEN u.tag = '유리' THEN 1 ELSE 0 END) AS good,
                  SUM(CASE WHEN u.tag = '불리' THEN 1 ELSE 0 END) AS bad
           FROM tags t
           LEFT JOIN tags u ON u.segment_id = t.segment_id AND u.category = '유불리'
           WHERE t.category = '쟁점'
           GROUP BY t.tag ORDER BY n DESC"""
    ).fetchall()
    return [dict(r) for r in rows]


def segments_for(conn, issue: str, stance: str = None, limit: int = 200) -> list[dict]:
    sql = """SELECT s.*, src.path, src.kind, src.occurred_at AS src_occurred_at,
                    t.matched, n.verified_by_ear, n.verdict,
                    (SELECT tag FROM tags WHERE segment_id = s.id
                       AND category = '유불리' LIMIT 1) AS stance
             FROM tags t
             JOIN segments s ON s.id = t.segment_id
             JOIN sources src ON src.id = s.source_id
             LEFT JOIN notes n ON n.segment_id = s.id
             WHERE t.category = '쟁점' AND t.tag = ?"""
    args = [issue]
    if stance:
        sql += (" AND EXISTS (SELECT 1 FROM tags u WHERE u.segment_id = s.id "
                "AND u.category = '유불리' AND u.tag = ?)")
        args.append(stance)
    sql += " ORDER BY COALESCE(src.occurred_at, ''), s.seq LIMIT ?"
    args.append(limit)
    return [dict(r) for r in conn.execute(sql, args).fetchall()]
