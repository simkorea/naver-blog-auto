# -*- coding: utf-8 -*-
"""
③ 화자 지정 — '화자1'을 '나'와 '고객'으로 바꾸는 화면.

여기가 끝나야 "상대방이 한 말만" 골라볼 수 있다.
소송에서 필요한 것은 대부분 상대방의 발언이므로, 이 단계가
프로그램의 실질적인 완성 지점이다.
"""
from pathlib import Path

import streamlit as st

from evidence.ingest import diarize, voiceprint
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

    groups = voiceprint.groups(conn)
    if groups:
        _group_view(conn, groups)
    else:
        _needs_voiceprint(conn)

    st.divider()
    _correction_list(conn)


def _needs_voiceprint(conn):
    """
    목소리 묶기를 아직 안 했을 때. **이름을 붙이면 안 되는 상태다.**

    화자 분리는 파일 하나씩 돌아가므로 'SPEAKER_00' 은 그 파일에서 먼저
    말한 사람일 뿐이다. 통화마다 누가 먼저 말하는지 다르니, 한꺼번에
    이름을 붙이면 상당수 통화에서 '나'와 '상대방'이 뒤바뀐다.
    """
    n_files = conn.execute(
        "SELECT count(DISTINCT source_id) FROM segments WHERE speaker IS NOT NULL"
    ).fetchone()[0]

    if n_files <= 1:
        # 파일이 하나뿐이면 뒤바뀔 일이 없다. 예전 방식 그대로 쓴다.
        st.caption("각 화자의 대표 발화를 들어보고 누구인지 지정하세요.")
        for sp in diarize.speaker_list(conn):
            _speaker_card(conn, sp)
        return

    st.error(
        f"**아직 이름을 붙이면 안 됩니다.** 녹음 {n_files}건의 화자가 "
        "서로 짝지어지지 않았습니다.\n\n"
        "화자 자동 분리는 **녹음 하나씩** 돌아갑니다. 그래서 '화자1'은 "
        "**그 통화에서 먼저 말한 사람**일 뿐입니다. 어떤 통화는 사장님이 "
        "먼저 \"여보세요\" 하고, 어떤 통화는 상대가 먼저 합니다.\n\n"
        "지금 이름을 붙이면 **상당수 통화에서 '나'와 '상대방'이 뒤바뀝니다.** "
        "법정에 내는 문서에서 이건 치명적입니다."
    )
    st.info(
        "먼저 목소리로 같은 사람끼리 묶어야 합니다. 명령창에서:\n\n"
        "`python evidence/transcribe.py --voiceprint`\n\n"
        "화자 분리에 쓰는 모델과 같은 것이라 새로 받지 않습니다. "
        "끝나면 이 화면이 사람 단위로 바뀝니다."
    )


def _group_view(conn, groups):
    """목소리로 묶은 사람 단위로 이름을 붙인다."""
    me = voiceprint.suggest_me(conn)
    st.caption(
        f"목소리로 묶으니 **{len(groups)}명**입니다. 대표 발화를 들어보고 "
        "누구인지 지정하세요. 한 번 지정하면 그 사람이 나오는 **모든 통화**에 "
        "정확히 붙습니다."
    )
    for w in voiceprint.problems(conn):
        st.warning(w)

    for g in groups:
        _group_card(conn, g, is_me_guess=(g["group_no"] == me))


def _group_card(conn, g, is_me_guess=False):
    mins = int((g["talk_sec"] or 0) // 60)
    name = g["label"] or f"목소리 {g['group_no'] + 1}"

    with st.container(border=True):
        head = (f"**{name}**　·　통화 {g['file_count']}건　·　"
                f"구간 {g['segments']:,}개　·　말한 시간 {mins}분")
        st.markdown(head)
        if is_me_guess and not g["label"]:
            st.info(
                "이 목소리가 **사장님**으로 보입니다 — 통화 "
                f"{g['file_count']}건 전부에 나옵니다. 상대방은 통화마다 "
                "다르니까요. 그래도 아래 발화를 들어보고 확인하세요."
            )

        st.caption("대표 발화 — 들어보고 누구인지 판단하세요")
        for smp in g["samples"]:
            tc = hybrid.timecode(smp["start_sec"])
            st.markdown(f"　`{tc}`　{smp['text'][:120]}")
            if Path(smp["path"]).exists():
                try:
                    st.audio(smp["path"],
                             start_time=int(max(0, (smp["start_sec"] or 0) - 2)))
                except Exception:
                    pass

        with st.expander(f"이 목소리가 나오는 통화 {g['file_count']}건"):
            for m in g["members"]:
                st.caption(f"· {m['file']}　({m['speaker']})")

        c1, c2 = st.columns([2, 1])
        preset = c1.radio(
            "이 사람은 누구인가요?", PRESETS + ["직접 입력"],
            horizontal=True, key=f"gpreset_{g['group_no']}",
            index=PRESETS.index(g["label"]) if g["label"] in PRESETS else 3,
        )
        custom = c1.text_input(
            "이름", g["label"] or "", key=f"gcustom_{g['group_no']}",
            placeholder="예) 고객 홍길동",
            disabled=(preset != "직접 입력"),
        )
        if c2.button("이 이름으로 지정", key=f"gset_{g['group_no']}",
                     type="primary"):
            label = custom.strip() if preset == "직접 입력" else preset
            if not label:
                st.error("이름을 입력하세요.")
            else:
                n = voiceprint.set_group_label(conn, g["group_no"], label)
                st.success(f"통화 {g['file_count']}건, {n}개 구간을 "
                           f"'{label}'로 지정했습니다.")
                st.rerun()


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
