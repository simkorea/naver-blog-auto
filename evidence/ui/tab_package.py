# -*- coding: utf-8 -*-
"""
⑦ 제출 패키지 — 경찰서·변호사에게 넘길 폴더를 만드는 화면.

여기서 프로그램이 하는 가장 중요한 일은 **막는 것**이다.
원본 없이 발췌본만 내보내려는 시도를 거부하고, 청취 확인이 안 된
구간이 섞여 있으면 경고한다.
"""
from pathlib import Path

import streamlit as st

from evidence import basket, config, db
from evidence.report import clip, locator, package
from evidence.search import hybrid


def render(conn):
    st.subheader("제출 패키지")

    items = basket.items(conn)
    if not items:
        st.info(
            "발췌 장바구니가 비어 있습니다.\n\n"
            "[검색] 또는 [타임라인] 탭에서 제출할 구간을 **📎 발췌 담기**로 담으세요."
        )
        return

    _basket_view(conn, items)
    st.divider()
    _build_form(conn)


def _basket_view(conn, items):
    st.markdown(f"#### 발췌 목록 ({len(items)}건)")

    for i, it in enumerate(items, 1):
        name = Path(it["path"]).name
        if it["clip_start_sec"] is not None:
            loc = (f"{hybrid.timecode(it['clip_start_sec'])} ~ "
                   f"{hybrid.timecode(it['clip_end_sec'])}")
        elif it["page_no"]:
            loc = f"{it['page_no']}쪽"
        else:
            loc = (it["occurred_at"] or it["src_occurred_at"] or "")[:16].replace("T", " ")

        flags = []
        if it["kind"] == "audio" and not it["verified_by_ear"]:
            flags.append("⬜ 미검증")
        if it["alt_mismatch"]:
            flags.append("⚠ 전사 불일치")
        if it["is_my_conversation"] == "N":
            flags.append("🚫 제3자 녹음")

        with st.container(border=True):
            c1, c2 = st.columns([5, 1])
            with c1:
                st.markdown(f"**{i}. {name}**　`{loc}`"
                            + (f"　**{it['speaker_label']}**" if it["speaker_label"] else "")
                            + ("　" + " ".join(flags) if flags else ""))
                st.markdown(f"> {(it['corrected_text'] or it['text'])[:200]}")
                if it["reason"]:
                    st.caption(f"제출 사유: {it['reason']}")
                else:
                    st.caption("제출 사유가 비어 있습니다 — 적어두면 변호사가 바로 이해합니다.")
            if c2.button("빼기", key=f"rm_{it['segment_id']}"):
                basket.remove(conn, it["segment_id"])
                st.rerun()

    if st.button("장바구니 비우기"):
        basket.clear(conn)
        st.rerun()


def _build_form(conn):
    st.markdown("#### 패키지 만들기")

    check = package.preflight(conn)
    for w in check["warnings"]:
        st.warning(w)

    c1, c2 = st.columns(2)
    case_name = c1.text_input("사건 표시", placeholder="예) 홍길동 손해배상 청구 사건",
                              help="문서 제목에 들어갑니다.")
    target = c2.selectbox("제출 대상", ["경찰서", "변호사", "법원", "보관용"])

    out_root = st.text_input(
        "저장 위치", str(Path.home() / "Desktop"),
        help="이 폴더 안에 '제출_날짜_대상' 폴더가 만들어집니다.",
    )

    c1, c2 = st.columns(2)
    mode = c1.radio(
        "발췌본 추출 방식",
        [clip.MODE_PCM, clip.MODE_COPY],
        format_func=lambda m: ("정밀 추출 (WAV · 권장)" if m == clip.MODE_PCM
                               else "원본 코덱 복사 (파일 작음)"),
        help="정밀 추출은 어느 컴퓨터에서나 코덱 없이 열립니다. "
             "받는 쪽이 '재생이 안 된다'고 할 여지가 없습니다.",
    )
    include_memo = c2.checkbox(
        "법률검토메모 포함", value=(target == "변호사"),
        help="쟁점·근거 조문·판례를 정리한 내부 검토 자료입니다. "
             "수사기관 제출용에는 넣지 않는 것이 보통입니다.",
    )

    st.info(
        "**원본은 항상 함께 담깁니다.**　유리한 구간만 잘라 발췌본만 내면 "
        "'맥락을 잘라내 편집했다'는 반박을 받고 증거가치가 떨어집니다. "
        "원본과 세트로 내고 대응표를 붙이면, 발췌본은 편집물이 아니라 "
        "'여기를 들으세요'라는 안내가 됩니다."
    )

    if check["blockers"]:
        for b in check["blockers"]:
            st.error(b)
        return

    if st.button("제출 패키지 만들기", type="primary"):
        _run(conn, out_root, target, case_name, mode, include_memo)


def _run(conn, out_root, target, case_name, mode, include_memo):
    if not out_root.strip():
        st.error("저장 위치를 입력하세요.")
        return
    root = Path(out_root.strip())
    if not root.exists():
        try:
            root.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            st.error(f"저장 위치를 만들 수 없습니다: {e}")
            return

    bar = st.progress(0.0)

    def on(n, total, label):
        bar.progress(n / max(total, 1), text=label)

    try:
        with st.spinner("패키지를 만드는 중..."):
            res = package.build(conn, root, target=target, case_name=case_name,
                                extract_mode=mode, include_legal_memo=include_memo,
                                progress=on)
    except package.PackageError as e:
        bar.empty()
        st.error(str(e))
        return
    except Exception as e:
        bar.empty()
        st.error(f"패키지 생성 실패: {type(e).__name__} — {e}")
        return

    bar.empty()
    ok_clips = [c for c in res["clips"] if c.get("ok")]
    failed = [c for c in res["clips"] if not c.get("ok")]

    st.success(f"완성했습니다 — 원본 {len(res['originals'])}개 · "
               f"발췌본 {len(ok_clips)}개 · 문서 {len(res['files'])}개")
    st.code(str(res["root"]), language=None)
    st.caption("이 폴더를 통째로 USB에 담아 제출하시면 됩니다.")

    with st.expander("담긴 파일", expanded=True):
        for f in sorted(res["root"].iterdir()):
            st.markdown(f"　{'📁' if f.is_dir() else '📄'} {f.name}")

    # 해시 불일치는 원본 훼손을 뜻하므로 크게 알린다
    bad = [o for o in res["originals"] if o["actual"] != o["expected"]]
    if bad:
        st.error(
            f"⚠ 원본 {len(bad)}건의 해시가 등록 당시와 다릅니다. "
            "파일이 변경되었을 수 있으니 반드시 확인하세요:\n\n"
            + "\n".join(f"· {b['name']}" for b in bad)
        )
    if failed:
        st.warning(f"추출하지 못한 구간 {len(failed)}건")
        for f in failed:
            st.caption(f"· {f['name']} — {f['error']}")
    if res.get("errors"):
        for e in res["errors"]:
            st.warning(e)
