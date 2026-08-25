# -*- coding: utf-8 -*-
"""
③ 화자 지정 — '화자1'을 '나'와 '고객'으로 바꾸는 화면.

여기가 끝나야 "상대방이 한 말만" 골라볼 수 있다.
소송에서 필요한 것은 대부분 상대방의 발언이므로, 이 단계가
프로그램의 실질적인 완성 지점이다.
"""
from pathlib import Path

import streamlit as st

from evidence.ingest import diarize
from evidence.search import hybrid

PRESETS = ["나", "상대방", "제3자"]


def render(conn):
    st.subheader("화자 지정")

    ok, why = diarize.available()
    if not ok:
        st.info(f"화자 자동 분리를 쓸 수 없습니다 — {why}")
        st.caption(
            "화자 분리 없이도 검색·발췌는 모두 동작합니다. "
            "다만 '상대방 발언만 보기'는 쓸 수 없습니다."
        )

    speakers = diarize.speaker_list(conn)
    if not speakers:
        st.info(
            "아직 분리된 화자가 없습니다. [분석 실행] 탭에서 "
            "'화자 자동 분리'를 켜고 녹음을 전사하세요."
        )
        _manual_fallback(conn)
        return

    st.caption(
        "각 화자의 대표 발화를 들어보고 누구인지 지정하세요. "
        "지정한 이름이 검색 필터와 모든 산출물에 쓰입니다."
    )

    for sp in speakers:
        _speaker_card(conn, sp)

    st.divider()
    _correction_list(conn)


def _speaker_card(conn, sp):
    mins = int(sp["talk_sec"] // 60)
    secs = int(sp["talk_sec"] % 60)
    title = f"**{sp['label'] or sp['speaker']}**　·　{sp['count']}개 구간　·　말한 시간 {mins}분 {secs}초"

    with st.container(border=True):
        st.markdown(title)

        st.caption("대표 발화 — 들어보고 누구인지 판단하세요")
        for s in sp["samples"]:
            tc = hybrid.timecode(s["start_sec"])
            st.markdown(f"　`{tc}`　{s['text'][:120]}")
            src = conn.execute("SELECT path FROM sources WHERE id = ?",
                               (s["source_id"],)).fetchone()
            if src and Path(src["path"]).exists():
                try:
                    st.audio(src["path"], start_time=int(max(0, s["start_sec"] - 2)))
                except Exception:
                    pass

        c1, c2 = st.columns([2, 1])
        preset = c1.radio(
            "이 사람은 누구인가요?", PRESETS + ["직접 입력"],
            horizontal=True, key=f"preset_{sp['speaker']}",
            index=PRESETS.index(sp["label"]) if sp["label"] in PRESETS else 3,
        )
        custom = c1.text_input(
            "이름", sp["label"] or "", key=f"custom_{sp['speaker']}",
            placeholder="예) 고객 홍길동",
            disabled=(preset != "직접 입력"),
        )
        if c2.button("이 이름으로 지정", key=f"set_{sp['speaker']}",
                     type="primary"):
            label = custom.strip() if preset == "직접 입력" else preset
            if not label:
                st.error("이름을 입력하세요.")
            else:
                n = diarize.set_label(conn, sp["speaker"], label)
                st.success(f"{n}개 구간을 '{label}'로 지정했습니다.")
                st.rerun()


def _correction_list(conn):
    """자동 분리가 헷갈려한 구간 — 사람이 확인해야 한다."""
    rows = conn.execute(
        """SELECT s.id, s.text, s.start_sec, s.speaker, s.speaker_label,
                  src.path
           FROM segments s JOIN sources src ON src.id = s.source_id
           WHERE s.speaker_uncertain = 1
           ORDER BY s.source_id, s.seq LIMIT 40"""
    ).fetchall()
    if not rows:
        return

    st.markdown(f"#### 말이 겹쳐 화자가 불확실한 구간 ({len(rows)}건)")
    st.caption(
        "두 사람이 동시에 말한 구간입니다. 누구 말인지 확실하지 않으니 "
        "들어보고 고쳐주세요. 잘못된 화자로 제출하면 신뢰를 잃습니다."
    )
    labels = PRESETS + [l for l in hybrid.speakers(conn) if l not in PRESETS]

    for r in rows:
        with st.container(border=True):
            st.markdown(f"`{hybrid.timecode(r['start_sec'])}`　"
                        f"현재: **{r['speaker_label'] or r['speaker']}**")
            st.markdown(r["text"])
            if Path(r["path"]).exists():
                try:
                    st.audio(r["path"], start_time=int(max(0, (r["start_sec"] or 0) - 3)))
                except Exception:
                    pass
            c1, c2 = st.columns([2, 1])
            pick = c1.selectbox("실제 화자", labels, key=f"fix_{r['id']}",
                                index=labels.index(r["speaker_label"])
                                if r["speaker_label"] in labels else 0)
            if c2.button("고치기", key=f"fixbtn_{r['id']}"):
                diarize.set_segment_speaker(conn, r["id"], pick)
                conn.execute("UPDATE segments SET speaker_uncertain = 0 WHERE id = ?",
                             (r["id"],))
                conn.commit()
                st.rerun()


def _manual_fallback(conn):
    """
    화자 분리를 못 쓰는 경우의 대안.
    카톡은 발신자가 이미 확실하므로 그것만이라도 정리해 준다.
    """
    rows = conn.execute(
        "SELECT DISTINCT speaker_label FROM segments "
        "WHERE speaker_label IS NOT NULL ORDER BY speaker_label"
    ).fetchall()
    if not rows:
        return

    st.markdown("#### 카톡·문자에서 확인된 발신자")
    st.caption("이 이름들은 검색의 '화자' 필터에서 바로 쓸 수 있습니다.")
    for r in rows:
        n = conn.execute(
            "SELECT count(*) FROM segments WHERE speaker_label = ?", (r[0],)
        ).fetchone()[0]
        st.markdown(f"· **{r[0]}** — {n}건")
