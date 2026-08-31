# -*- coding: utf-8 -*-
"""
⑧ 도구 — 백업·내보내기·정리.

여기 쌓이는 것은 다시 만들기 어렵다. 몇 시간 걸린 전사, 일일이 들어가며
확인한 청취 기록, 손으로 고친 화자 지정. 백업을 쉽게 만들어 두는 것이
프로그램이 해줄 수 있는 가장 실질적인 보험이다.
"""
from pathlib import Path

import streamlit as st

from evidence import backup, config, db
from evidence.ingest import preprocess
from evidence.report import export


def render(conn):
    st.subheader("도구")

    tabs = st.tabs(["백업", "내보내기", "정리", "처리 이력"])
    with tabs[0]:
        _backup(conn)
    with tabs[1]:
        _export(conn)
    with tabs[2]:
        _cleanup(conn)
    with tabs[3]:
        _log()


# ─────────────────────────────────────────────────────────
def _backup(conn):
    st.markdown("#### 백업")
    st.caption(
        "전사 결과·청취 확인 기록·화자 지정·발췌 목록을 하나의 파일로 저장합니다. "
        "원본 녹음은 들어가지 않습니다(원래 자리에 그대로 있으므로). "
        "**중요한 작업을 마칠 때마다 눌러두세요.**"
    )

    c1, c2 = st.columns([2, 1])
    note = c1.text_input("메모", placeholder="예) 화자 지정 완료 후")
    out = c1.text_input("저장 위치", str(config.WORK_DIR / "backups"))
    if c2.button("지금 백업", type="primary"):
        try:
            with st.spinner("백업하는 중..."):
                p = backup.create(out, note)
            info = backup.inspect(p)
            st.success(f"백업했습니다 — {info['size_mb']}MB")
            st.code(str(p), language=None)
        except Exception as e:
            st.error(f"백업 실패: {e}")

    st.divider()
    rows = backup.list_backups(out)
    if not rows:
        st.caption("아직 백업이 없습니다.")
        return

    st.markdown(f"**백업 {len(rows)}개**")
    for r in rows[:10]:
        s = r.get("stats") or {}
        with st.container(border=True):
            c1, c2 = st.columns([4, 1])
            c1.markdown(f"**{Path(r['path']).name}**")
            c1.caption(
                f"{r['created_at']}　·　{r['size_mb']}MB　·　"
                f"자료 {len(r['sources'])}건　·　구간 {s.get('segments', 0):,}개"
                + (f"　·　{r['note']}" if r["note"] else "")
            )
            if c2.button("복원", key=f"rs_{r['path']}"):
                st.session_state["restore_target"] = r["path"]

    target = st.session_state.get("restore_target")
    if target:
        st.warning(
            f"**{Path(target).name}** 로 되돌립니다.\n\n"
            "지금 분석 결과를 덮어씁니다. 덮어쓰기 전에 현재 상태를 "
            "자동으로 한 번 더 백업하므로 되돌릴 수 있습니다."
        )
        c1, c2 = st.columns(2)
        if c1.button("복원 실행", type="primary"):
            try:
                res = backup.restore(target)
                st.success("복원했습니다. 화면을 새로고침하세요.")
                if res["safety_backup"]:
                    st.caption(f"복원 전 상태: {res['safety_backup']}")
                st.session_state.pop("restore_target", None)
                st.cache_resource.clear()
            except Exception as e:
                st.error(f"복원 실패: {e}")
        if c2.button("취소"):
            st.session_state.pop("restore_target", None)
            st.rerun()


# ─────────────────────────────────────────────────────────
def _export(conn):
    st.markdown("#### 내보내기")
    st.caption("분석 결과를 파일로 빼냅니다. 변호사에게 통째로 넘기거나 인쇄할 때.")

    out_dir = st.text_input("저장 위치", str(Path.home() / "Desktop"),
                            key="exp_dir")
    case_name = st.text_input("사건 표시", key="exp_case",
                              placeholder="예) 홍길동 손해배상 청구 사건")

    st.markdown("**전체 전사본** — 녹음 하나를 처음부터 끝까지")
    sources = conn.execute(
        "SELECT id, path, kind FROM sources WHERE status IN "
        "('extracted','verified') ORDER BY COALESCE(occurred_at,''), id"
    ).fetchall()
    if sources:
        pick = st.selectbox(
            "자료", [r["id"] for r in sources],
            format_func=lambda i: Path(
                next(r["path"] for r in sources if r["id"] == i)).name,
        )
        c1, c2 = st.columns(2)
        if c1.button("워드로 저장"):
            _save(lambda p: export.full_transcript_docx(conn, pick, p),
                  Path(out_dir) / f"전사본_{Path(dict(sources[0])['path']).stem[:20]}.docx")
        if c2.button("텍스트로 저장"):
            try:
                p = Path(out_dir) / "전사본.txt"
                p.write_text(export.full_transcript_text(conn, pick),
                             encoding="utf-8")
                st.success(f"저장: {p}")
            except Exception as e:
                st.error(f"실패: {e}")
    else:
        st.caption("아직 처리된 자료가 없습니다.")

    st.divider()
    st.markdown("**전사본 전부 한 번에** — 처리된 자료를 통째로")
    st.caption(
        "한 건씩 누르지 않고 전부 뽑아 한 폴더에 넣습니다. "
        "파일 이름 앞에 번호와 날짜가 붙어 시간순으로 정렬됩니다."
    )
    have_names = conn.execute(
        "SELECT count(*) FROM segments WHERE speaker_label IS NOT NULL"
    ).fetchone()[0]
    if not have_names:
        st.info(
            "화자 이름을 아직 안 붙이셨습니다. 전사본에는 '화자1/화자2'로 "
            "나옵니다. [③ 화자 지정] 에서 '나'/'고객'을 정하면 그 이름으로 "
            "나옵니다."
        )
    c1, c2 = st.columns(2)
    if c1.button("전부 워드로 저장", key="exp_all_docx"):
        _save_all(conn, Path(out_dir) / "전사본_전체", as_docx=True)
    if c2.button("전부 텍스트로 저장", key="exp_all_txt"):
        _save_all(conn, Path(out_dir) / "전사본_전체", as_docx=False)

    st.divider()
    st.markdown("**전체 구간 표** — 모든 구간을 한 표로")
    c1, c2 = st.columns(2)
    if c1.button("엑셀로 저장"):
        _save(lambda p: export.all_xlsx(conn, p), Path(out_dir) / "전체구간.xlsx")
    if c2.button("CSV로 저장"):
        _save(lambda p: export.all_csv(conn, p), Path(out_dir) / "전체구간.csv")

    st.divider()
    st.markdown("**타임라인** — 브라우저로 보는 시간순 정리")
    if st.button("HTML로 저장"):
        _save(lambda p: export.timeline_html(conn, p, case_name),
              Path(out_dir) / "타임라인.html")


def _save_all(conn, out_dir: Path, as_docx: bool):
    bar = st.progress(0.0, text="준비 중...")
    try:
        def on(i, total, name):
            bar.progress(i / max(total, 1), text=f"[{i}/{total}] {name[:40]}")

        r = export.all_transcripts(conn, out_dir, as_docx=as_docx, progress=on)
    except Exception as e:
        bar.empty()
        st.error(f"실패: {e}")
        return
    bar.empty()
    if not r["total"]:
        st.warning("처리된 자료가 없습니다.")
        return
    st.success(f"**{len(r['made'])}건**을 저장했습니다 → `{r['dir']}`")
    if r["failed"]:
        st.error(f"{len(r['failed'])}건은 실패했습니다:")
        for name, why in r["failed"][:10]:
            st.caption(f"· {name} — {why}")


def _save(fn, path: Path):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        out = fn(path)
        st.success(f"저장했습니다 — {Path(out).name}")
        st.code(str(out), language=None)
    except Exception as e:
        st.error(f"저장 실패: {type(e).__name__} — {e}")


# ─────────────────────────────────────────────────────────
def _cleanup(conn):
    st.markdown("#### 정리")

    size = preprocess.cache_size_mb()
    st.markdown(f"**전처리 사본** — {size}MB")
    st.caption(
        "녹음을 전사하기 전에 잡음을 줄인 임시 사본입니다. "
        "지워도 다음 전사 때 다시 만들어지며, 원본과는 무관합니다."
    )
    c1, c2 = st.columns([1, 3])
    days = c2.slider("며칠 지난 것부터", 0, 30, 7, key="prep_days")
    if c1.button("정리"):
        n = preprocess.cleanup(days)
        st.success(f"{n}개 삭제")
        st.rerun()

    st.divider()
    st.markdown("**오래된 백업**")
    keep = st.number_input("최근 몇 개를 남길까요", 1, 50, 10)
    if st.button("오래된 백업 삭제"):
        n = backup.prune(int(keep))
        st.success(f"{n}개 삭제")

    st.divider()
    st.markdown("**원본 무결성 확인**")
    st.caption("등록 당시 해시와 지금 해시를 전부 대조합니다. "
               "원본이 바뀌었는지 확인할 수 있습니다.")
    if st.button("전수 대조 실행"):
        from evidence import integrity
        bar = st.progress(0.0)

        def on(i, total, path):
            bar.progress(i / max(total, 1), text=Path(path).name)

        with st.spinner("해시를 다시 계산하는 중..."):
            rows = integrity.verify_all(conn, progress=on)
        bar.empty()
        bad = [r for r in rows if r["status"] != "ok"]
        if bad:
            st.error(f"문제 {len(bad)}건 — 원본이 변경되었거나 사라졌습니다")
            for r in bad:
                st.markdown(f"　`[{r['status']}]` {r['path']}")
        else:
            st.success(f"모든 원본 {len(rows)}건이 등록 당시와 동일합니다.")


# ─────────────────────────────────────────────────────────
def _log():
    st.markdown("#### 처리 이력")
    st.caption(
        "언제 무엇을 어떤 설정으로 처리했는지 기록입니다. "
        "지워지지 않고 계속 쌓이며, 자료를 어떻게 다뤘는지 보여주는 근거가 됩니다."
    )
    from evidence import integrity
    rows = integrity.read_log(300)
    if not rows:
        st.caption("아직 기록이 없습니다.")
        return

    kinds = sorted({r.get("event", "") for r in rows})
    pick = st.multiselect("종류", kinds, default=[])
    shown = [r for r in reversed(rows) if not pick or r.get("event") in pick]

    for r in shown[:120]:
        detail = {k: v for k, v in r.items() if k not in ("at", "event")}
        st.markdown(f"`{r.get('at','')}`　**{r.get('event','')}**")
        if detail:
            st.caption("　" + "　·　".join(
                f"{k}={str(v)[:60]}" for k, v in list(detail.items())[:5]))
