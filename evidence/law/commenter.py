# -*- coding: utf-8 -*-
"""
법률 참고 코멘트 생성.

이 모듈의 설계 원칙은 하나다: **AI가 법 조문이나 판례 문구를 쓰지 못하게 한다.**

연구 결과 LLM은 관련 문서를 찾는 데는 쓸 만하지만 정확한 근거 구간을
짚는 데는 취약하다. 그래서 AI에게는 "이 발언이 어느 근거와 닿아 있는가"의
판단만 시키고, 출력 형식에서 **인용문 필드를 아예 없앤다.**
AI는 근거의 번호(ref_id)만 돌려주고, 실제 조문·판례 문구는 우리가
DB에 받아둔 원문을 그대로 렌더링한다. 지어낼 경로 자체가 없다.

두 가지 방식으로 동작한다.
  근거 연결 방식 (기본, 오프라인)
      쟁점과 발언으로 관련 조문·판례를 검색해 연결만 한다.
      AI를 쓰지 않으므로 지어낼 여지가 0이고, 인터넷도 필요 없다.
  AI 판단 추가 (선택, OFFLINE_ONLY=false 일 때)
      위에서 찾은 근거 안에서만 유불리 판단과 한 줄 설명을 붙인다.
      그 뒤 인용 검증 게이트를 반드시 통과해야 화면에 뜬다.
"""
import json
import re
from datetime import datetime

from .. import config, db, integrity
from . import retrieve

DISCLAIMER = (
    "본 코멘트는 관련 법령·판례를 찾아주는 조사 보조 자료이며 법률 자문이 아닙니다. "
    "법리 판단과 대응 전략은 반드시 변호사와 상의하시기 바랍니다."
)

# AI에게 주는 지시. 인용문을 쓰지 못하게 하는 것이 전부다.
PROMPT = """\
당신은 소송 자료 정리를 돕는 보조자입니다. 아래 [발언]이 [참고 근거] 중
어느 것과 관련되는지 판단하세요.

반드시 지킬 것:
- 법 조문이나 판례의 문구를 직접 쓰지 마십시오. 근거는 번호로만 지목합니다.
- [참고 근거]에 없는 법령·판례를 언급하지 마십시오. 기억에 있는 법을
  꺼내 쓰면 안 됩니다.
- 사건번호, 조문 번호를 문장 안에 적지 마십시오.
- 판단이 어려우면 stance를 "중립"으로 두고 citations를 비우십시오.

[쟁점]
{issue}

[발언]
{text}

[참고 근거]
{refs}

아래 JSON 형식으로만 답하십시오. 다른 말은 붙이지 마십시오.
{{"stance": "유리|불리|중립",
  "reasoning": "이 발언이 어떤 요건과 닿아 있는지 두 문장 이내. 법령명·조문번호·사건번호 금지.",
  "citations": [1, 2]}}
"""


def available_ai() -> tuple[bool, str]:
    if config.OFFLINE_ONLY:
        return False, "오프라인 모드입니다 (.env에서 OFFLINE_ONLY=false 로 바꾸면 사용 가능)"
    if not config.GEMINI_API_KEY:
        return False, ".env에 GEMINI_API_KEY가 없습니다"
    try:
        import google.generativeai      # noqa: F401
    except BaseException:
        return False, "google-generativeai 미설치"
    return True, ""


def _strip_citations(text: str) -> str:
    """
    모델이 그래도 조문·사건번호를 적었다면 지운다.
    검증 게이트가 잡아내지만, 애초에 새어 나가지 않게 한 겹 더 막는다.
    """
    from .verify_citation import LAW_CITE_RE, PREC_CITE_RE
    t = LAW_CITE_RE.sub("[해당 조문]", text or "")
    t = PREC_CITE_RE.sub("[해당 판례]", t)
    return t.strip()


def _ask_ai(issue: str, text: str, refs: list[dict]) -> dict | None:
    ok, _ = available_ai()
    if not ok:
        return None
    import google.generativeai as genai

    genai.configure(api_key=config.GEMINI_API_KEY)
    listing = "\n".join(
        f"{i+1}. {r['label']}\n{r['body'][:600]}" for i, r in enumerate(refs))
    prompt = PROMPT.format(issue=issue, text=text[:1500], refs=listing)

    try:
        model = genai.GenerativeModel(
            "gemini-2.5-flash-lite",
            generation_config={"temperature": 0.2, "max_output_tokens": 600},
        )
        raw = (model.generate_content(prompt).text or "").strip()
    except Exception:
        return None

    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None

    picked = []
    for n in (data.get("citations") or []):
        try:
            idx = int(n) - 1
        except (TypeError, ValueError):
            continue
        if 0 <= idx < len(refs):
            picked.append(refs[idx])

    return {
        "stance": data.get("stance") if data.get("stance") in ("유리", "불리", "중립") else "중립",
        # 인용문 필드가 없다. 설명만 받고, 혹시 섞인 인용은 지운다.
        "reasoning": _strip_citations(str(data.get("reasoning") or ""))[:500],
        "refs": picked,
    }


# ─────────────────────────────────────────────────────────
# 코멘트 생성
# ─────────────────────────────────────────────────────────
def comment_segment(conn, segment_id: int, use_ai: bool = False) -> int | None:
    """구간 하나에 대한 법률 참고 코멘트를 만든다."""
    seg = conn.execute(
        """SELECT s.id, s.text, s.speaker_label,
                  (SELECT tag FROM tags WHERE segment_id = s.id
                     AND category = '쟁점' LIMIT 1) AS issue,
                  (SELECT tag FROM tags WHERE segment_id = s.id
                     AND category = '유불리' LIMIT 1) AS stance
           FROM segments s WHERE s.id = ?""", (segment_id,)).fetchone()
    if not seg:
        return None

    issue = seg["issue"] or "일반"
    refs = retrieve.for_issue(conn, issue, [seg["text"]], limit=5)
    if not refs:
        return None

    stance = seg["stance"] or "중립"
    reasoning = (f"'{issue}' 쟁점과 관련된 발언입니다. "
                 f"아래 조문·판례가 이 쟁점의 판단 기준을 담고 있습니다.")
    engine = "retrieval"

    if use_ai:
        judged = _ask_ai(issue, seg["text"], refs)
        if judged:
            stance = judged["stance"]
            reasoning = judged["reasoning"] or reasoning
            refs = judged["refs"] or refs
            engine = "gemini"

    now = datetime.now().isoformat(timespec="seconds")
    db.write(conn, "DELETE FROM comments WHERE segment_id = ?", (segment_id,))
    cur = db.write(conn,
                   """INSERT INTO comments
                      (segment_id, issue_name, stance, reasoning,
                       citation_status, engine, created_at)
                      VALUES (?,?,?,?,'pending',?,?)""",
                   (segment_id, issue, stance, reasoning, engine, now))
    comment_id = cur.lastrowid

    db.write_many(conn,
                  """INSERT INTO comment_citations
                     (comment_id, ref_type, ref_id, source_url) VALUES (?,?,?,?)""",
                  [(comment_id, r["ref_type"], r["ref_id"], r.get("url"))
                   for r in refs])
    return comment_id


def run(conn, only_tagged: bool = True, use_ai: bool = False,
        verify_online: bool = True, progress=None) -> dict:
    """
    쟁점이 걸린 구간에 코멘트를 만들고, 전부 인용 검증을 통과시킨다.
    검증에 실패한 코멘트는 화면에 뜨지 않는다.
    """
    from . import verify_citation

    sql = "SELECT s.id FROM segments s JOIN sources src ON src.id = s.source_id " \
          "WHERE src.is_my_conversation != 'N'"
    if only_tagged:
        sql += " AND EXISTS (SELECT 1 FROM tags t WHERE t.segment_id = s.id " \
               "AND t.category = '쟁점')"
    rows = conn.execute(sql).fetchall()

    made = 0
    for i, r in enumerate(rows, 1):
        if progress:
            progress(i, len(rows), "코멘트 작성")
        if comment_segment(conn, r["id"], use_ai=use_ai):
            made += 1

    if progress:
        progress(len(rows), len(rows), "인용 검증")
    res = verify_citation.verify_all(conn, online=verify_online)

    integrity.log("legal_comments", made=made, verified=res["verified"],
                  blocked=res["blocked"], engine="gemini" if use_ai else "retrieval")
    return {"made": made, **res}


def list_comments(conn, status: str = "verified") -> list[dict]:
    """화면에 뿌릴 코멘트. 기본은 검증을 통과한 것만."""
    sql = """SELECT c.*, s.text, s.speaker_label, s.start_sec, s.page_no,
                    src.path, src.kind,
                    COALESCE(s.occurred_at, src.occurred_at) AS at
             FROM comments c
             JOIN segments s ON s.id = c.segment_id
             JOIN sources src ON src.id = s.source_id"""
    args = []
    if status:
        sql += " WHERE c.citation_status = ?"
        args.append(status)
    sql += " ORDER BY c.issue_name, COALESCE(at, '')"

    out = []
    for r in conn.execute(sql, args).fetchall():
        row = dict(r)
        row["citations"] = []
        for cite in conn.execute(
                "SELECT * FROM comment_citations WHERE comment_id = ? "
                "ORDER BY id", (r["id"],)).fetchall():
            ref = retrieve.fetch(conn, cite["ref_type"], cite["ref_id"])
            if ref:
                ref["verified_ok"] = bool(cite["verified_ok"])
                row["citations"].append(ref)
        out.append(row)
    return out
