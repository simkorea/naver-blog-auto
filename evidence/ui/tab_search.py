# -*- coding: utf-8 -*-
"""
④ 검색 — 이 프로그램의 중심 화면.

여기서 하는 일
  · 단어와 문장으로 찾기
  · 상대방 발언만 걸러 보기
  · 결과를 클릭해 원본 그 지점부터 듣기 (맥락을 위해 5초 앞에서 시작)
  · 들어보고 '귀로 확인함' 체크 — 확인 전에는 산출물에 "미검증"이 박힌다
  · 구간을 다듬어 발췌 장바구니에 담기
"""
from datetime import datetime
from pathlib import Path

import streamlit as st

from evidence import basket, db
from evidence.search import hybrid

PAD_BEFORE = 5.0        # 재생 시작을 이만큼 앞당긴다 (맥락 확보)


def render(conn):
    st.subheader("검색")

    s = db.stats(conn)
    if not s["segments"]:
        st.info("아직 검색할 내용이 없습니다. [분석 실행] 탭에서 자료를 처리하세요.")
        return

    with st.form("search_form"):
        # placeholder 에 슬래시로 예시를 여러 개 늘어놓았더니, 사용자가
        # "슬래시로 여러 개를 넣으라"는 뜻으로 읽고 일곱 단어를 한 번에 넣어
        # 0건이 나왔다. 예시는 **하나만** 둔다.
        q = st.text_input(
            "무엇을 찾으시나요?",
            placeholder="예)  환불",
            help=(
                "**한 번에 하나씩** 넣으시는 것이 가장 정확합니다.\n\n"
                "여러 단어를 넣으면 그것을 **전부 포함한** 구간을 찾습니다. "
                "그런 구간이 없으면 '하나라도 포함'으로 다시 찾아 알려드립니다.\n\n"
                "**찾을 수 있는 것** — 실제로 입에서 나온 말 "
                "(`대출`, `포기`, `환불해 달라`)\n\n"
                "**찾을 수 없는 것** — 목소리 톤·울음·화난 기색. "
                "전사에는 말의 내용만 남고 감정은 글자로 남지 않습니다."
            ),
        )
        # 여러 단어를 어떻게 볼 것인지. 숨겨두면 사용자는 알 수 없다 —
        # 실제로 관련된 말을 열두 개 늘어놓고 "이 중 아무거나"를 기대했는데
        # 프로그램은 "전부 다 든 구간"을 찾아 0건이 나왔다.
        match_mode = st.radio(
            "단어를 여러 개 넣으면",
            ["모두 든 구간만", "하나라도 든 구간 전부"],
            index=1, horizontal=True,
            help=(
                "**모두 든 구간만** — 정확히 좁힐 때. `대출 안 된다` 처럼.\n\n"
                "**하나라도 든 구간 전부** — 넓게 훑을 때. "
                "`환불 전매 도와줘 살려줘` 처럼 비슷한 말을 늘어놓고 "
                "그 중 아무거나 나온 곳을 다 보고 싶을 때."
            ),
        )
        c1, c2, c3, c4 = st.columns(4)
        speaker = c1.selectbox("화자", ["전체"] + hybrid.speakers(conn))
        kind = c2.selectbox(
            "자료 종류", ["전체", "audio", "kakao", "document", "image", "email"],
            format_func=lambda k: {"전체": "전체", "audio": "녹음", "kakao": "카톡",
                                   "document": "문서", "image": "이미지",
                                   "email": "메일"}.get(k, k))
        only_low = c3.checkbox("확인 필요 구간만", value=False,
                               help="전사가 의심스러운 구간만 봅니다. 여기부터 들으세요.")
        use_sem = c4.checkbox("의미 검색 함께", value=True,
                              help="표현이 달라도 비슷한 상황을 찾습니다.")
        go = st.form_submit_button("검색", type="primary")

    # 체크는 되어 있는데 색인이 없으면 아무 일도 하지 않는다. 실제로 명령창으로
    # 밤새 전사한 뒤 색인이 하나도 없는 채로 검색해 0건이 나온 일이 있었다.
    # 켜져 있는 것처럼 보이면서 안 도는 것이 가장 나쁘다.
    missing = _semantic_gap(conn, s["segments"])
    if use_sem and missing:
        st.info(
            f"**의미 검색 색인이 {missing:,}구간 비어 있습니다.** "
            "지금은 정확히 그 단어만 찾습니다.\n\n"
            "만들려면 명령창에서 — 몇 분 걸립니다:\n\n"
            "`python evidence/transcribe.py --index`"
        )

    if go and q.strip():
        st.session_state["last_query"] = q.strip()
        st.session_state["last_filters"] = {
            "speaker": None if speaker == "전체" else speaker,
            "kind": None if kind == "전체" else kind,
            "only_low_confidence": only_low,
            "exclude_illegal": True,
        }
        st.session_state["use_semantic"] = use_sem
        st.session_state["match_any"] = match_mode.startswith("하나라도")

    q = st.session_state.get("last_query")
    if not q:
        _quick_links(conn)
        return

    hits = hybrid.search(conn, q, limit=60,
                         filters=st.session_state.get("last_filters", {}),
                         use_semantic=st.session_state.get("use_semantic", True),
                         match_any=st.session_state.get("match_any", True))
    if not hits:
        st.warning("찾은 내용이 없습니다. 다른 표현으로 검색해 보세요.")
        return

    st.markdown(f"**{len(hits)}건** 찾음 — `{q}`")
    if hits and hits[0].get("search_mode") == "하나라도" \
            and hits[0].get("term_count", 0) > 1:
        n = hits[0]["term_count"]
        if st.session_state.get("match_any", True):
            st.caption(f"{n}개 단어 중 **하나라도** 든 구간을 모았습니다.")
        else:
            st.warning(
                f"넣으신 **{n}개 단어를 모두** 든 구간은 없어서, "
                "**하나라도** 든 구간을 찾았습니다."
            )
    for h in hits:
        _result_card(conn, h, q)


def _quick_links(conn):
    """자주 쓰는 진입점. 무엇을 검색해야 할지 막막할 때."""
    st.markdown("#### 어디서부터 볼까요")
    c1, c2 = st.columns(2)

    low = conn.execute(
        "SELECT count(*) FROM segments WHERE alt_mismatch = 1 "
        "OR hallucination_risk = 1 OR (confidence IS NOT NULL AND confidence < 0.6)"
    ).fetchone()[0]
    if low:
        c1.warning(f"**확인 필요 구간 {low}건**\n\n전사가 의심스러운 곳입니다. "
                   "여기부터 들어보세요.")

    tags = conn.execute(
        "SELECT tag, count(*) n FROM tags WHERE category='쟁점' "
        "GROUP BY tag ORDER BY n DESC LIMIT 8"
    ).fetchall()
    if tags:
        c2.markdown("**쟁점별 구간**")
        for t in tags:
            c2.caption(f"· {t['tag']} — {t['n']}건")


def _semantic_gap(conn, total_segments: int) -> int:
    """의미 검색 색인이 몇 구간이나 비어 있는지. 못 세면 0(= 조용히)."""
    if not total_segments or not db.vec_available(conn):
        return 0
    try:
        have = conn.execute("SELECT count(*) FROM vec_segments").fetchone()[0]
    except Exception:
        return 0
    return max(total_segments - (have or 0), 0)


def _result_card(conn, h, query):
    """검색 결과 한 건."""
    name = Path(h["path"]).name
    is_audio = h["kind"] == "audio"

    # 위치 표기 — 증거에서 가장 중요한 정보
    if is_audio and h["start_sec"] is not None:
        where = f"{hybrid.timecode(h['start_sec'])} ~ {hybrid.timecode(h['end_sec'])}"
    elif h["page_no"]:
        where = f"{h['page_no']}쪽"
    else:
        where = (h["occurred_at"] or h["src_occurred_at"] or "")[:16].replace("T", " ")

    who = h.get("speaker_label") or h.get("speaker") or ""
    badges = []
    if h.get("verified_by_ear"):
        badges.append("✅ 청취확인")
    elif is_audio:
        badges.append("⬜ 미검증")
    if h.get("alt_mismatch"):
        badges.append("⚠ 전사 불일치")
    if h.get("hallucination_risk"):
        badges.append("⚠ 환청 의심")
    if h.get("in_basket"):
        badges.append("📎 발췌 담김")

    header = f"**{name}** · `{where}`" + (f" · **{who}**" if who else "")
    with st.container(border=True):
        st.markdown(header + ("　" + " ".join(badges) if badges else ""))
        st.markdown(hybrid.highlight(h["text"], query))

        if h.get("alt_mismatch") and h.get("alt_text"):
            st.caption(f"2차 모델은 이렇게 들었습니다: 「{h['alt_text']}」 "
                       "— 둘 중 무엇이 맞는지 원본을 들어 확인하세요.")

        c1, c2, c3 = st.columns([1, 1, 1])
        key = h["id"]

        if c1.button("맥락 보기", key=f"ctx_{key}"):
            st.session_state[f"show_ctx_{key}"] = not st.session_state.get(f"show_ctx_{key}")
        if is_audio and c2.button("🔊 이 지점 듣기", key=f"play_{key}"):
            st.session_state[f"show_play_{key}"] = True
        if c3.button("📎 발췌 담기" if not h.get("in_basket") else "📎 담김 (해제)",
                     key=f"bsk_{key}"):
            if h.get("in_basket"):
                basket.remove(conn, key)
            else:
                basket.add(conn, key)
            st.rerun()

        if st.session_state.get(f"show_ctx_{key}"):
            _context_view(conn, h)
        if st.session_state.get(f"show_play_{key}"):
            _player(conn, h)


def _context_view(conn, h):
    st.caption("앞뒤 맥락 — 한 문장만 떼면 의미가 뒤집힐 수 있습니다")
    for c in hybrid.context(conn, h["id"], 3, 3):
        mark = "▶ " if c["id"] == h["id"] else "　"
        tc = hybrid.timecode(c["start_sec"]) if c["start_sec"] is not None else ""
        who = c.get("speaker_label") or c.get("speaker") or ""
        line = f"{mark}`{tc}` **{who}** {c['text']}" if who else f"{mark}`{tc}` {c['text']}"
        if c["id"] == h["id"]:
            st.markdown(f"**{line}**")
        else:
            st.caption(line)


def _player(conn, h):
    """
    원본을 해당 지점부터 재생한다.
    맥락을 놓치지 않게 5초 앞에서 시작한다.
    """
    path = Path(h["path"])
    if not path.exists():
        st.error(f"원본 파일을 찾을 수 없습니다: {path}")
        return

    start = max(0.0, (h["start_sec"] or 0) - PAD_BEFORE)
    st.caption(
        f"{hybrid.timecode(start)} 부터 재생합니다 "
        f"(맥락을 위해 {int(PAD_BEFORE)}초 앞에서 시작) — "
        f"실제 구간은 {hybrid.timecode(h['start_sec'])} ~ {hybrid.timecode(h['end_sec'])}"
    )
    try:
        st.audio(str(path), start_time=int(start))
    except Exception as e:
        st.error(f"재생할 수 없습니다: {e}")
        return

    st.markdown("**들어보신 뒤 확인해 주세요**")
    c1, c2 = st.columns([1, 2])
    heard = c1.checkbox("전사 내용이 실제 음성과 같음",
                        value=bool(h.get("verified_by_ear")),
                        key=f"ear_{h['id']}")
    corrected = c2.text_input(
        "다르면 실제 말한 내용을 적어주세요", h.get("corrected_text") or "",
        key=f"corr_{h['id']}",
        help="여기 적은 내용이 산출물에 반영됩니다.",
    )
    if st.button("확인 기록 저장", key=f"savear_{h['id']}"):
        _save_verification(conn, h["id"], heard, corrected.strip() or None)
        st.success("기록했습니다.")
        st.rerun()

    # 발췌 구간 미세 조정
    if h.get("in_basket"):
        _trim(conn, h)


def _save_verification(conn, segment_id, heard, corrected):
    db.write(conn,
             """INSERT INTO notes(segment_id, verified_by_ear, verified_at, corrected_text)
                VALUES (?,?,?,?)
                ON CONFLICT(segment_id) DO UPDATE SET
                  verified_by_ear = excluded.verified_by_ear,
                  verified_at = excluded.verified_at,
                  corrected_text = excluded.corrected_text""",
             (segment_id, 1 if heard else 0,
              datetime.now().isoformat(timespec="seconds"), corrected))
    from evidence import integrity
    integrity.log("ear_verified", segment_id=segment_id,
                  verified=bool(heard), corrected=bool(corrected))


def _trim(conn, h):
    """
    발췌 구간을 다듬는다.
    Whisper가 자른 구간은 말 중간에서 끊기는 경우가 많다.
    """
    st.markdown("**발췌 구간 다듬기**")
    b = basket.get(conn, h["id"])
    if not b:
        return
    dur = h.get("duration_sec") or (h["end_sec"] or 0) + 30

    c1, c2 = st.columns(2)
    start = c1.number_input("시작 (초)", 0.0, float(dur),
                            float(b["clip_start_sec"]), 0.5,
                            key=f"ts_{h['id']}")
    end = c2.number_input("종료 (초)", 0.0, float(dur),
                          float(b["clip_end_sec"]), 0.5,
                          key=f"te_{h['id']}")
    reason = st.text_input(
        "이 구간을 제출하는 이유", b["reason"] or "", key=f"tr_{h['id']}",
        help="예) 고객이 설명을 들었다고 직접 인정한 발언",
    )
    st.caption(f"현재 설정: `{hybrid.timecode(start)} ~ {hybrid.timecode(end)}` "
               f"({end - start:.1f}초)")
    if st.button("구간 저장", key=f"tsave_{h['id']}"):
        basket.update(conn, h["id"], clip_start_sec=start, clip_end_sec=end,
                      reason=reason.strip() or None)
        st.success("저장했습니다.")
        st.rerun()
