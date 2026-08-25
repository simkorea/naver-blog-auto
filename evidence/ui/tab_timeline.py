# -*- coding: utf-8 -*-
"""
⑤ 타임라인 — 흩어진 자료를 시간순으로 늘어놓는 화면.

여기서 가장 값진 것은 '진술 모순' 목록이다.
상대방이 처음에는 인정했다가 나중에 부인한 정황은, 시간순으로
늘어놓아야만 보인다. 그리고 그것이 이 사건에서 가장 강력한 증거가 된다.
"""
from pathlib import Path

import streamlit as st

from evidence import basket
from evidence.analyze import keywords, timeline
from evidence.search import hybrid

STANCE_ICON = {"유리": "🟢", "불리": "🔴", "중립": "⚪"}


def render(conn):
    st.subheader("타임라인")

    s = timeline.summary(conn)
    if not s["events"]:
        st.info("아직 정리할 자료가 없습니다.")
        return

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("사건 수", s["events"])
    c2.metric("기간", f"{(s['first'] or '')[:10]} ~")
    c3.metric("시각 추정", s["estimated"],
              help="파일 수정 시각으로 추정한 항목입니다. 정확한 일시를 아신다면 "
                   "[자료 등록] 탭에서 고쳐주세요.")
    c4.metric("진술 모순", s["contradictions"])

    _contradictions(conn)
    st.divider()
    _issue_summary(conn)
    st.divider()
    _timeline(conn)


def _contradictions(conn):
    """상대방이 말을 바꾼 정황 — 이 프로그램이 찾아내는 가장 값진 것."""
    rows = timeline.contradictions(conn)
    if not rows:
        return

    st.markdown("#### ★ 진술이 바뀐 정황")
    st.caption(
        "상대방이 먼저 인정했다가 나중에 부인한 것으로 보이는 대목입니다. "
        "제출 전 각 발언의 원본을 반드시 확인하세요."
    )

    for i, c in enumerate(rows[:10]):
        with st.container(border=True):
            st.markdown(f"**{c['person']}** — {c['days']}일 간격으로 말이 달라졌습니다")

            e, l = c["earlier"], c["later"]
            col1, col2 = st.columns(2)
            with col1:
                st.markdown(f"🟢 **{(e['at'] or '')[:10]}** · {Path(e['path']).name}")
                if e.get("start_sec") is not None:
                    st.caption(f"위치 {hybrid.timecode(e['start_sec'])}")
                st.markdown(f"> {e['text'][:200]}")
                if st.button("📎 발췌 담기", key=f"cont_e_{i}"):
                    basket.add(conn, e["id"], f"{c['person']} 인정 발언 ({c['issue']})")
                    st.rerun()
            with col2:
                st.markdown(f"🔴 **{(l['at'] or '')[:10]}** · {Path(l['path']).name}")
                if l.get("start_sec") is not None:
                    st.caption(f"위치 {hybrid.timecode(l['start_sec'])}")
                st.markdown(f"> {l['text'][:200]}")
                if st.button("📎 발췌 담기", key=f"cont_l_{i}"):
                    basket.add(conn, l["id"], f"{c['person']} 번복 발언 ({c['issue']})")
                    st.rerun()


def _issue_summary(conn):
    st.markdown("#### 쟁점별 정리")
    try:
        rows = keywords.by_issue(conn)
    except Exception as e:
        st.error(f"쟁점 사전을 읽지 못했습니다: {e}")
        return

    if not rows:
        st.caption("아직 쟁점이 분류되지 않았습니다. 아래 버튼을 눌러 분류하세요.")
    if st.button("쟁점 다시 분류"):
        with st.spinner("쟁점 사전과 대조하는 중..."):
            r = keywords.scan(conn)
        st.success(f"쟁점 {r['issues']}개 · 태그 {r['tags']}개")
        st.rerun()

    if rows:
        cols = st.columns(min(len(rows), 4))
        for i, r in enumerate(rows):
            with cols[i % len(cols)]:
                st.metric(r["issue"], f"{r['n']}건")
                if r["good"] or r["bad"]:
                    st.caption(f"🟢 {r['good']}　🔴 {r['bad']}")

    st.caption(
        f"쟁점 사전 파일: `{keywords.ensure_yaml()}` — 메모장으로 열어 "
        "직접 고칠 수 있습니다. 사건에 맞게 표현을 추가하세요."
    )


def _timeline(conn):
    st.markdown("#### 전체 시간순 정리")

    c1, c2, c3 = st.columns(3)
    issues = ["전체"] + [r["issue"] for r in keywords.by_issue(conn)]
    issue = c1.selectbox("쟁점", issues)
    speaker = c2.selectbox("화자", ["전체"] + hybrid.speakers(conn))
    tagged_only = c3.checkbox("쟁점 걸린 것만", value=True)

    rows = timeline.events(
        conn,
        issue=None if issue == "전체" else issue,
        speaker=None if speaker == "전체" else speaker,
        only_tagged=tagged_only,
    )
    if not rows:
        st.caption("조건에 맞는 항목이 없습니다.")
        return

    for day, events in timeline.by_day(rows):
        st.markdown(f"**{day}**")
        for e in events:
            icon = STANCE_ICON.get(e["stance"], "·")
            loc = (hybrid.timecode(e["start_sec"])
                   if e["start_sec"] is not None
                   else (f"{e['page_no']}쪽" if e["page_no"] else ""))
            who = e["speaker_label"] or e["speaker"] or ""

            flags = []
            if e["occurred_at_est"]:
                flags.append("시각 추정")
            if e["alt_mismatch"]:
                flags.append(e["mismatch_kind"] or "전사 불일치")
            if e["speaker_uncertain"]:
                flags.append("화자 불확실")
            if e["in_basket"]:
                flags.append("발췌 담김")

            head = f"{icon}　`{loc}`　**{who}**" if who else f"{icon}　`{loc}`"
            if e["issue"]:
                head += f"　*{e['issue']}*"
            if flags:
                head += f"　<span style='color:#c00'>({' · '.join(flags)})</span>"

            st.markdown(head, unsafe_allow_html=True)
            st.markdown(f"　　{(e['corrected_text'] or e['text'])[:260]}")
        st.markdown("")
