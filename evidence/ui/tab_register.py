# -*- coding: utf-8 -*-
"""
① 자료 등록 — 증거를 프로그램에 들여오는 화면.

여기서 반드시 받아야 하는 값이 하나 있다: 녹음의 적법성이다.
본인이 대화 당사자인 녹음은 적법하게 증거로 쓸 수 있지만,
제3자 간 대화를 몰래 녹음한 것은 통신비밀보호법 위반으로
증거능력이 부정되고 처벌 대상이 된다. 잘못 제출하면 역풍을 맞으므로
등록 단계에서 갈라 두고, '아니오'는 산출물에서 자동 제외한다.
"""
from pathlib import Path

import streamlit as st

from evidence import config, db, integrity
from evidence.ingest import scanner

LEGAL_OPTIONS = {
    "Y": "예 — 내가 대화에 참여했음",
    "N": "아니오 — 제3자 간 대화",
    "UNKNOWN": "아직 확인 안 함",
    "NA": "해당 없음 (녹음 아님)",
}


def render(conn):
    st.subheader("자료 등록")
    st.caption(
        "증거 폴더를 지정하면 파일을 훑어 종류를 나누고, 각 파일의 SHA-256 해시를 "
        "기록합니다. 원본은 읽기만 하며 수정·이동하지 않습니다."
    )

    with st.form("scan_form"):
        c1, c2 = st.columns([3, 1])
        folder = c1.text_input(
            "증거 폴더 경로",
            placeholder=r"예)  C:\Users\사용자\Desktop\소송자료",
            help="폴더 안의 하위 폴더까지 모두 훑습니다.",
        )
        counterparty = c2.text_input("상대방 이름", placeholder="예) 홍길동")
        submitted = st.form_submit_button("스캔 시작", type="primary")

    if submitted:
        if not folder.strip():
            st.error("폴더 경로를 입력하세요.")
        elif not Path(folder.strip()).exists():
            st.error(f"폴더를 찾을 수 없습니다: {folder}")
        else:
            _do_scan(conn, folder.strip(), counterparty.strip() or None)

    st.divider()
    _source_table(conn)


def _do_scan(conn, folder, counterparty):
    bar = st.progress(0.0, text="파일 목록을 읽는 중...")
    status = st.empty()

    def on_progress(i, total, name):
        bar.progress(i / max(total, 1), text=f"[{i}/{total}] {name}")

    defaults = {"counterparty": counterparty} if counterparty else {}
    try:
        result = scanner.scan(conn, folder, progress=on_progress, defaults=defaults)
    except Exception as e:
        bar.empty()
        st.error(f"스캔 실패: {e}")
        return

    bar.empty()
    status.success(
        f"전체 {result['total']}개 · 신규 등록 {len(result['added'])}개 · "
        f"이미 등록됨 {len(result['duplicate'])}개 · 실패 {len(result['failed'])}개"
    )
    if result["duplicate"]:
        st.caption(
            "같은 내용의 파일(해시 동일)은 한 건으로 묶었습니다. "
            "여러 폴더에 복사해 둔 같은 녹음은 중복 등록되지 않습니다."
        )
    if result["failed"]:
        with st.expander(f"읽지 못한 파일 {len(result['failed'])}개"):
            for p, err in result["failed"]:
                st.text(f"{Path(p).name} — {err}")

    skipped = result.get("skipped") or []
    if skipped:
        # 무엇이 빠졌는지 반드시 보여준다.
        # 정작 필요한 증거가 조용히 누락되면 알 방법이 없다.
        with st.expander(f"건너뛴 파일 {len(skipped)}개 — 확인해 보세요"):
            st.caption(
                "아래 파일들은 등록되지 않았습니다. 이 중 증거로 쓸 것이 있다면 "
                "형식을 바꿔서(예: 한글 → PDF) 다시 넣으세요."
            )
            for item in skipped[:200]:
                st.text(f"{Path(item['path']).name} — {item['reason']}")


def _source_table(conn):
    rows = scanner.list_sources(conn)
    if not rows:
        st.info("아직 등록된 자료가 없습니다. 위에서 증거 폴더를 지정하세요.")
        return

    st.markdown("#### 등록된 자료")

    audio_unknown = [r for r in rows
                     if r["kind"] == "audio" and r["is_my_conversation"] == "UNKNOWN"]
    if audio_unknown:
        st.warning(
            f"**녹음 {len(audio_unknown)}건의 적법성이 미확인 상태입니다.**\n\n"
            "본인이 참여한 대화의 녹음은 적법하게 증거로 쓸 수 있지만, "
            "제3자 간 대화를 몰래 녹음한 것은 통신비밀보호법 위반이 되어 "
            "증거능력이 부정되고 처벌 대상이 됩니다. "
            "아래에서 각 녹음을 확인해 지정하세요."
        )

    kinds = sorted({r["kind"] for r in rows})
    label = {"audio": "🎤 녹음", "kakao": "💬 카톡", "document": "📄 문서",
             "image": "🖼 이미지", "email": "✉ 메일"}

    pick = st.selectbox(
        "종류", ["전체"] + kinds,
        format_func=lambda k: "전체" if k == "전체" else label.get(k, k),
    )
    shown = [r for r in rows if pick == "전체" or r["kind"] == pick]

    for r in shown:
        name = Path(r["path"]).name
        icon = label.get(r["kind"], r["kind"]).split()[0]
        flag = ""
        if r["kind"] == "audio":
            if r["is_my_conversation"] == "UNKNOWN":
                flag = " ⚠ 적법성 미확인"
            elif r["is_my_conversation"] == "N":
                flag = " 🚫 제출 제외"

        when = (r["occurred_at"] or "")[:16].replace("T", " ")
        est = " (추정)" if r["occurred_at_est"] else ""
        head = f"{icon} **{name}** · {when}{est}{flag}"

        with st.expander(head):
            c1, c2 = st.columns([2, 3])
            with c1:
                st.caption("파일 정보")
                st.text(f"크기   {r['bytes']:,} 바이트")
                if r["duration_sec"]:
                    m, s = divmod(int(r["duration_sec"]), 60)
                    st.text(f"길이   {m}분 {s}초")
                st.text(f"상태   {r['status']}")
                if r["status_detail"]:
                    st.caption(r["status_detail"])
                st.caption("SHA-256 (등록 시 봉인)")
                st.code(r["sha256"], language=None)

            with c2:
                st.caption("증거 정보 — 정확할수록 타임라인이 정확해집니다")
                cur = r["is_my_conversation"] or "UNKNOWN"
                new_legal = st.selectbox(
                    "내가 참여한 대화인가?",
                    list(LEGAL_OPTIONS),
                    index=list(LEGAL_OPTIONS).index(cur) if cur in LEGAL_OPTIONS else 2,
                    format_func=lambda k: LEGAL_OPTIONS[k],
                    key=f"legal_{r['id']}",
                    disabled=(r["kind"] != "audio"),
                )
                new_party = st.text_input("상대방", r["counterparty"] or "",
                                          key=f"party_{r['id']}")
                new_when = st.text_input(
                    "발생 일시 (YYYY-MM-DD HH:MM)",
                    (r["occurred_at"] or "")[:16].replace("T", " "),
                    key=f"when_{r['id']}",
                    help="파일명에서 자동으로 읽었습니다. 다르면 고쳐주세요.",
                )
                new_memo = st.text_area("메모", r["memo"] or "", height=68,
                                        key=f"memo_{r['id']}")

                if st.button("저장", key=f"save_{r['id']}"):
                    when_iso = new_when.strip().replace(" ", "T") or None
                    scanner.update_source(
                        conn, r["id"],
                        is_my_conversation=new_legal,
                        counterparty=new_party.strip() or None,
                        occurred_at=when_iso,
                        occurred_at_est=0 if when_iso else 1,
                        memo=new_memo.strip() or None,
                    )
                    st.success("저장했습니다.")
                    st.rerun()

            if r["is_my_conversation"] == "N":
                st.error(
                    "제3자 간 대화로 표시되어 있습니다. 이 자료는 검색 결과와 "
                    "제출 패키지에서 자동으로 제외됩니다."
                )
