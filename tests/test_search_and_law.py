# -*- coding: utf-8 -*-
"""
검색·법률 계층 검증.

여기서 확인하는 것
  · 한국어 검색이 조사·띄어쓰기·길이에 관계없이 걸리는가
  · 의미 검색과 키워드 검색이 RRF로 제대로 합쳐지는가
  · 제3자 녹음이 검색에서 정말 빠지는가
  · 인용 검증 게이트가 위조를 막는가 (온라인 조회를 가짜로 대체해 시험)
  · 법령 API 응답 파싱이 맞는가
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from conftest import Check, install_fake_embedder, use_temp_db


def run(tmp_path) -> bool:
    config = use_temp_db(tmp_path)
    from evidence import db, integrity
    from evidence.search import embed, hybrid

    c = Check("검색 · 법률")
    conn = db.init()

    # ── 자료 준비 ────────────────────────────
    def add(name, kind, legal="Y"):
        f = tmp_path / name
        f.write_text(name, encoding="utf-8")
        sid, _ = db.add_source(conn, integrity.fingerprint(f), kind,
                               is_my_conversation=legal)
        return sid

    mine = add("내통화.m4a", "audio", "Y")
    third = add("제3자통화.m4a", "audio", "N")

    db.add_segments(conn, mine, [
        {"seq": 1, "text": "계약금을 이미 입금했습니다", "start_sec": 0, "end_sec": 3,
         "speaker_label": "나"},
        {"seq": 2, "text": "네 그건 설명 들었어요", "start_sec": 3, "end_sec": 6,
         "speaker_label": "고객"},
        {"seq": 3, "text": "못들었는데요", "start_sec": 6, "end_sec": 9,
         "speaker_label": "고객"},
        {"seq": 4, "text": "환불 요청드립니다", "start_sec": 9, "end_sec": 12,
         "speaker_label": "고객"},
    ])
    db.add_segments(conn, third, [
        {"seq": 1, "text": "제3자 대화에 계약금 이야기가 나옴", "start_sec": 0, "end_sec": 3},
    ])

    # ── 한국어 검색 ──────────────────────────
    def n(q, **kw):
        return len(hybrid.search(conn, q, limit=50, use_semantic=False, **kw))

    c.ok(n("계약") >= 1, "조사가 붙어도 걸린다 ('계약금을' ← '계약')")
    c.ok(n("계약금") >= 1, "세 글자 이상은 FTS로 걸린다")
    c.ok(n("네") >= 1, "두 글자 이하도 걸린다 (LIKE 경로)")
    c.ok(n("못들었") >= 1, "띄어쓰기 없는 표기도 걸린다")
    c.eq(n("존재하지않는말"), 0, "없는 말은 0건")

    # 제3자 녹음 제외
    hits = hybrid.search(conn, "계약금", limit=50, use_semantic=False)
    c.ok(all("제3자" not in h["text"] for h in hits),
         "제3자 녹음은 검색에서 빠진다",
         f"{[h['text'][:20] for h in hits]}")
    with_illegal = hybrid.search(conn, "계약금", limit=50, use_semantic=False,
                                 filters={"exclude_illegal": False})
    c.ok(len(with_illegal) > len(hits), "필터를 끄면 다시 나온다")

    # 화자 필터
    cust = hybrid.search(conn, "설명", filters={"speaker": "고객"},
                         use_semantic=False)
    c.ok(cust and all(h["speaker_label"] == "고객" for h in cust),
         "상대방 발언만 골라낸다")

    # ── 의미 검색 · RRF 융합 ───────────────────
    install_fake_embedder(embed, config.EMBED_DIM)
    built = embed.build_index(conn)
    c.ok(built >= 5, "임베딩 색인이 만들어진다", f"{built}건")

    sem = hybrid.semantic_search(conn, "설명을 들었다는 취지", limit=20,
                                 filters={"exclude_illegal": True})
    c.ok(len(sem) > 0, "의미 검색이 결과를 낸다")
    c.ok(all(s["segment_id"] not in
             [r[0] for r in conn.execute(
                 "SELECT id FROM segments WHERE source_id = ?", (third,))]
             for s in sem),
         "의미 검색에도 제3자 제외가 적용된다")

    fused = hybrid.search(conn, "설명 들었", limit=20, use_semantic=True)
    c.ok(fused, "융합 검색이 결과를 낸다")
    c.ok(any("+" in f["matched_by"] or f["matched_by"] in ("키워드", "의미")
             for f in fused), "어느 쪽에서 걸렸는지 표시된다",
         f"{[f['matched_by'] for f in fused][:3]}")

    # 맥락
    target = next(h for h in hybrid.search(conn, "환불", use_semantic=False))
    ctx = hybrid.context(conn, target["id"], 2, 2)
    c.ok(len(ctx) >= 3, "앞뒤 맥락을 가져온다", f"{len(ctx)}개")
    c.ok(any(x["id"] == target["id"] for x in ctx), "맥락에 자기 자신이 들어있다")

    # ── 법령 API 파싱 ────────────────────────
    from evidence.law import client
    c.eq(client._norm_case("대법원 2011. 7. 14. 선고 2011다109357 판결"),
         "2011다109357", "사건번호에서 번호만 뽑는다")
    c.eq(client._clean("제25조(확인·설명)<br/>개업공인중개사는 &lt;대상물&gt;에"),
         "제25조(확인·설명)\n개업공인중개사는 <대상물>에", "조문 태그를 정리한다")

    # ── 인용 검증 게이트 ──────────────────────
    from datetime import datetime
    from evidence.law import verify_citation as V

    now = datetime.now().isoformat(timespec="seconds")
    db.write(conn, """INSERT INTO law_articles
        (law_name, law_id, article_no, article_title, body, enforce_date,
         source_url, fetched_at) VALUES (?,?,?,?,?,?,?,?)""",
             ("민법", "1", "제750조", "불법행위",
              "고의 또는 과실로 인한 위법행위로 타인에게 손해를 가한 자는 "
              "그 손해를 배상할 책임이 있다.", "1960-01-01", "u", now))
    art_id = conn.execute("SELECT id FROM law_articles").fetchone()[0]

    def make_comment(reasoning, cites):
        cur = db.write(conn, """INSERT INTO comments
            (segment_id, issue_name, stance, reasoning, citation_status,
             engine, created_at) VALUES (?,?,?,?, 'pending', 'test', ?)""",
                       (None, "테스트", "중립", reasoning, now))
        cid = cur.lastrowid
        for t, i in cites:
            db.write(conn, "INSERT INTO comment_citations"
                           "(comment_id, ref_type, ref_id) VALUES (?,?,?)",
                     (cid, t, i))
        return cid

    # 실존하는 근거 + 인용 없는 본문 → 통과해야 한다
    ok_id = make_comment("이 발언은 손해배상 요건과 닿아 있습니다.",
                         [("article", art_id)])
    r = V.verify_comment(conn, ok_id, online=False)
    c.eq(r["status"], "verified", "실존 근거만 있으면 통과한다")

    # 위조 시나리오
    cases = [
        ("없는 조문 id", "관련 있습니다.", [("article", 99999)]),
        ("없는 판례 id", "관련 있습니다.", [("precedent", 99999)]),
        ("근거 없음", "관련 있습니다.", []),
        ("본문에 가짜 사건번호", "대법원 2099다999999 판결 참조",
         [("article", art_id)]),
        ("본문에 없는 조문", "민법 제9999조에 따라",
         [("article", art_id)]),
        ("알 수 없는 근거 종류", "관련 있습니다.", [("책", art_id)]),
    ]
    for label, reasoning, cites in cases:
        cid = make_comment(reasoning, cites)
        r = V.verify_comment(conn, cid, online=False)
        c.eq(r["status"], "blocked", f"차단: {label}")

    # 차단된 것은 목록에 안 나와야 한다
    from evidence.law import commenter
    shown = commenter.list_comments(conn, status="verified")
    c.eq(len(shown), 1, "검증 통과분만 화면에 나온다")

    blocked = commenter.list_comments(conn, status="blocked")
    c.eq(len(blocked), len(cases), "차단된 것은 따로 볼 수 있다")
    c.ok(all(b["block_reason"] for b in blocked), "차단 사유가 남는다")

    # AI가 본문에 인용을 적어도 지운다
    stripped = commenter._strip_citations(
        "민법 제750조와 대법원 2011다109357에 따르면")
    c.ok("제750조" not in stripped and "2011다109357" not in stripped,
         "AI 본문에서 조문·사건번호를 제거한다", stripped)

    # ── 검색어를 여러 개 넣었을 때 ────────────────
    # 화면 예시가 `환불 / 설명 들었 / ...` 라서 사용자가 슬래시로 일곱 단어를
    # 한 번에 넣었고, 4,675구간이 있는데도 0건이 나왔다. 두 가지가 겹쳤다.
    #   (1) `대출/` 처럼 슬래시가 붙어 어떤 글에도 없는 단어가 됐다
    #   (2) 넣은 단어를 **모두** 포함하는 구간을 찾는데 그런 구간은 없었다
    ssid = add("검색어처리.m4a", "audio")
    db.add_segments(conn, ssid, [
        {"seq": 1, "text": "대출이 안 나온다고 하셔서 제가 알아봤습니다",
         "start_sec": 10, "end_sec": 15},
        {"seq": 2, "text": "이제 그만 포기하겠다고 말씀하셨죠",
         "start_sec": 30, "end_sec": 34},
        {"seq": 3, "text": "정말 죽겠다 싶을 만큼 힘들었습니다",
         "start_sec": 50, "end_sec": 55},
    ])

    # (1) 슬래시·쉼표가 붙어도 죽은 단어가 되지 않는다
    c.eq(hybrid._split_terms("대출/"), ["대출"], "단어에 붙은 슬래시를 떼어낸다")
    c.eq(hybrid._split_terms("대출, 환불"), ["대출", "환불"],
         "쉼표도 구분자로 본다")
    c.ok(len(hybrid.search(conn, "대출/", use_semantic=False)) == 1,
         "슬래시가 붙은 검색어로도 찾는다")

    # 따옴표로 묶으면 그 안의 슬래시는 구분자가 아니다
    c.eq(hybrid._split_terms('"1325호/1225호" 대출'), ["1325호/1225호", "대출"],
         "따옴표로 묶은 구절 안의 슬래시는 그대로 둔다")

    # (2) 사장님이 실제로 넣으신 그 질의
    real_q = "화내는 목소리 / 우는 상태/ 포기하겠다 / 죽겠다/ 대출/"
    hits = hybrid.search(conn, real_q, use_semantic=False)
    c.ok(len(hits) == 3, "모두 포함이 0건이면 하나라도 포함으로 찾는다",
         f"{len(hits)}건")
    c.ok(hits and hits[0].get("search_mode") == "하나라도",
         "어느 쪽으로 찾았는지 알려준다 — 화면이 사용자에게 설명해야 한다")
    c.ok(hits and hits[0].get("term_count") == 7, "나눈 단어 수도 알려준다")

    # (3) 평소 검색은 흐려지지 않는다 — '모두 포함'이 되면 그대로 쓴다
    both = hybrid.search(conn, "대출 알아봤습니다", use_semantic=False)
    c.eq(len(both), 1, "둘 다 든 구간이 있으면 그것만 찾는다")
    c.ok(both and both[0]["search_mode"] == "모두",
         "구제책이 평소 결과를 대신하지 않는다")
    c.eq(len(hybrid.search(conn, "어디에도없는말", use_semantic=False)), 0,
         "정말 없는 말은 0건 그대로다")

    # ── 밤샘 전사가 의미 검색 색인을 만드는가 ──────
    # 색인을 만드는 embed.build_index() 가 화면에만 있고 명령창 실행
    # (evidence/transcribe.py) 에는 빠져 있었다. 그래서 밤새 전사한 뒤
    # "의미 검색 함께"에 체크가 되어 있어도 아무 일도 하지 않았다.
    tsrc = (Path(__file__).resolve().parent.parent
            / "evidence" / "transcribe.py").read_text(encoding="utf-8")
    c.ok("build_index" in tsrc,
         "명령창 전사도 의미 검색 색인을 만든다")
    c.ok("--index" in tsrc,
         "전사 없이 색인만 만드는 길이 있다 (이미 전사가 끝난 경우)")

    import evidence.transcribe as _tr
    c.ok(callable(getattr(_tr, "build_search_index", None)),
         "색인 만들기를 함수로 부를 수 있다")
    c.ok(callable(getattr(_tr, "show_index_state", None)),
         "색인이 있는지 없는지 화면에 보여준다")

    # 화면도 색인이 비었을 때 알려준다
    from evidence.ui import tab_search as _ts
    c.ok(callable(getattr(_ts, "_semantic_gap", None)),
         "화면이 색인이 비었는지 확인한다")
    c.eq(_ts._semantic_gap(conn, 0), 0, "구간이 없으면 조용히 넘어간다")

    # 검색창 예시가 다시 슬래시로 돌아가지 않았는가
    ui_src = (Path(__file__).resolve().parent.parent
              / "evidence" / "ui" / "tab_search.py").read_text(encoding="utf-8")
    c.ok('placeholder="예)  환불"' in ui_src,
         "검색창 예시는 하나만 둔다 (슬래시로 여러 개를 넣게 만들지 않는다)")

    conn.close()
    return c.report()


if __name__ == "__main__":
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        sys.exit(0 if run(Path(d)) else 1)
