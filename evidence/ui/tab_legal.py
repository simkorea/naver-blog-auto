# -*- coding: utf-8 -*-
"""
⑥ 법률 코멘트 — 찾아낸 발언에 관련 조문·판례를 붙이는 화면.

이 화면의 규칙: **실존이 확인된 근거만 보여준다.**
AI가 판례를 지어내는 사고는 실제로 법정 제재로 이어졌다. 그래서
모든 조문·판례는 법제처에서 다시 조회해 실존을 확인하고, 통과하지
못한 것은 코멘트 대신 차단 사유가 표시된다.
"""
from pathlib import Path

import streamlit as st

from evidence import config
from evidence.law import client, commenter, corpus, verify_citation
from evidence.search import hybrid

STANCE_ICON = {"유리": "🟢", "불리": "🔴", "중립": "⚪"}


def render(conn):
    st.subheader("법률 코멘트")
    st.caption(
        "관련 법 조문과 판례를 **법제처에서 실제로 내려받아** 근거로 붙입니다. "
        "AI가 기억으로 지어낸 법은 쓰지 않습니다."
    )
    st.info(f"ℹ️ {commenter.DISCLAIMER}")

    ok, why = client.configured()
    if not ok:
        st.warning(f"법령 API를 쓸 수 없습니다 — {why}")
        with st.expander("인증키 발급 방법", expanded=True):
            st.markdown(
                "1. https://open.law.go.kr 접속 → 로그인\n"
                "2. **OPEN API → 활용신청** 에서 신청 (무료, 즉시 발급)\n"
                "3. 발급받은 인증키(OC)를 프로젝트 폴더의 `.env` 파일에 추가\n"
                "```\nLAW_OC=발급받은키\n```\n"
                "4. 프로그램을 다시 시작"
            )
        return

    st.divider()
    _corpus_section(conn)
    st.divider()
    _comment_section(conn)


def _corpus_section(conn):
    st.markdown("#### 1단계 · 참고할 법령 받아오기")

    s = corpus.stats(conn)
    c1, c2, c3 = st.columns(3)
    c1.metric("받아온 법령", f"{s['laws']}개")
    c2.metric("조문", f"{s['articles']:,}개")
    c3.metric("판례", f"{s['precedents']}건")

    scope_file = corpus.ensure_yaml()
    st.caption(
        f"받아올 법령 목록: `{scope_file}` — 메모장으로 열어 사건에 맞게 고치세요. "
        "**불리한 쪽 법령도 넣어야** 상대가 어느 조문으로 올지 미리 압니다."
    )
    try:
        scope = corpus.load_scope()
        st.markdown("　현재 목록: " + "、 ".join(scope["laws"]))
    except Exception as e:
        st.error(f"목록 파일을 읽지 못했습니다: {e}")
        return

    if st.button("법령·판례 받아오기", type="primary"):
        bar = st.progress(0.0)
        log = st.empty()

        def on(i, total, label):
            bar.progress(i / max(total, 1), text=label)
            log.caption(label)

        with st.spinner("법제처에서 원문을 받아오는 중..."):
            res = corpus.sync(conn, progress=on)
        bar.empty()

        got_laws = sum(res["laws"].values())
        got_prec = sum(res["precedents"].values())
        st.success(f"조문 {got_laws:,}개 · 판례 {got_prec}건 저장, "
                   f"검색 색인 {res['index']['indexed']:,}건 생성")
        if res["errors"]:
            with st.expander(f"받지 못한 항목 {len(res['errors'])}개"):
                for e in res["errors"]:
                    st.text(e)
        st.rerun()


def _comment_section(conn):
    st.markdown("#### 2단계 · 코멘트 만들기")

    s = corpus.stats(conn)
    if not s["articles"]:
        st.info("먼저 위에서 법령을 받아오세요.")
        return

    ai_ok, ai_why = commenter.available_ai()
    c1, c2 = st.columns([1, 2])
    use_ai = c1.checkbox(
        "AI 판단 추가", value=False, disabled=not ai_ok,
        help="찾아낸 근거 안에서만 유불리 판단과 설명을 붙입니다. "
             "AI는 근거 번호만 지목하고 조문 문구는 쓰지 못합니다.",
    )
    if not ai_ok:
        c2.caption(f"AI 판단 사용 불가 — {ai_why}")
    else:
        c2.caption("AI를 켜면 발언 내용이 외부 API로 전송됩니다. "
                   "근거 연결만으로도 충분한 경우가 많습니다.")

    if st.button("코멘트 만들기", type="primary"):
        bar = st.progress(0.0)

        def on(i, total, label):
            bar.progress(i / max(total, 1), text=f"{label} [{i}/{total}]")

        with st.spinner("관련 조문·판례를 연결하고 실존을 검증하는 중..."):
            res = commenter.run(conn, use_ai=use_ai, progress=on)
        bar.empty()
        st.success(f"코멘트 {res['made']}건 작성 · "
                   f"검증 통과 {res['verified']}건 · 차단 {res['blocked']}건")
        st.rerun()

    st.divider()
    _blocked(conn)
    _verified(conn)


def _blocked(conn):
    """차단된 코멘트를 숨기지 않고 드러낸다 — 무엇이 걸러졌는지 알아야 한다."""
    rows = commenter.list_comments(conn, status="blocked")
    if not rows:
        return
    with st.expander(f"⛔ 인용 검증에서 차단된 코멘트 {len(rows)}건", expanded=False):
        st.caption(
            "실존이 확인되지 않은 조문·판례가 포함되어 출력을 막았습니다. "
            "이런 인용을 그대로 제출하면 신뢰를 잃고 제재를 받을 수 있습니다."
        )
        for r in rows:
            st.markdown(f"**{r['issue_name']}** — {(r['text'] or '(구간 없음)')[:70]}")
            st.error(r["block_reason"] or "사유 불명")


def _verified(conn):
    rows = commenter.list_comments(conn, status="verified")
    if not rows:
        st.caption("아직 검증을 통과한 코멘트가 없습니다.")
        return

    st.markdown(f"#### 검증을 통과한 코멘트 ({len(rows)}건)")

    issues = sorted({r["issue_name"] for r in rows})
    pick = st.selectbox("쟁점", ["전체"] + issues)

    for r in rows:
        if pick != "전체" and r["issue_name"] != pick:
            continue
        _card(r)


def _card(r):
    icon = STANCE_ICON.get(r["stance"], "·")
    loc = (hybrid.timecode(r["start_sec"]) if r["start_sec"] is not None
           else (f"{r['page_no']}쪽" if r["page_no"] else (r["at"] or "")[:16].replace("T", " ")))
    # 가리키던 구간이 사라졌을 수 있다 (재분석 등). 그래도 코멘트는 보여준다.
    where = Path(r["path"]).name if r.get("path") else "출처 없음"

    with st.container(border=True):
        st.markdown(f"{icon} **{r['issue_name']}**　·　{where}"
                    + (f"　`{loc}`" if loc else ""))
        st.markdown(f"> {(r['text'] or '(구간을 찾을 수 없습니다)')[:300]}")
        st.caption(r["reasoning"])

        if r["citations"]:
            with st.expander(f"근거 원문 {len(r['citations'])}건 — 직접 확인하세요"):
                for c in r["citations"]:
                    mark = "✅" if c.get("verified_ok") else "⚠"
                    st.markdown(f"{mark} **{c['label']}**"
                                + (f"　_{c['extra']}_" if c.get("extra") else ""))
                    st.text(c["body"][:1200])
                    if c.get("url"):
                        st.markdown(f"[국가법령정보센터에서 보기]({c['url']})")
                    st.divider()
