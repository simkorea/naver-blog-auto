# -*- coding: utf-8 -*-
"""
② 분석 실행 — 등록한 자료를 실제로 텍스트로 만든다.

텍스트 자료(카톡·문서·이미지)는 빠르니 먼저 돌리고,
음성은 시간이 걸리니 나눠서 돌릴 수 있게 했다.
중단해도 다음에 남은 것부터 이어서 처리한다.
"""
from pathlib import Path

import streamlit as st

from evidence import config, db
from evidence.ingest import pipeline


def render(conn):
    st.subheader("분석 실행")

    s = db.stats(conn)
    if not s["sources"]:
        st.info("먼저 [자료 등록] 탭에서 증거 폴더를 지정하세요.")
        return

    pend_text = pipeline.pending(conn, kinds=pipeline.TEXT_KINDS)
    pend_audio = pipeline.pending(conn, kinds=(config.KIND_AUDIO,))

    c1, c2, c3 = st.columns(3)
    c1.metric("텍스트 자료 대기", len(pend_text))
    c2.metric("녹음 대기", len(pend_audio))
    c3.metric("만들어진 구간", f"{s['segments']:,}")

    st.divider()

    # ── 1단계: 텍스트 ─────────────────────────────
    st.markdown("#### 1단계 · 텍스트 자료")
    st.caption("카톡·문서·이미지를 텍스트로 바꿉니다. 빠르게 끝나고 바로 검색할 수 있습니다.")
    if st.button("텍스트 자료 처리", type="primary", disabled=not pend_text):
        _run(conn, kinds=pipeline.TEXT_KINDS)

    st.divider()

    # ── 2단계: 음성 ───────────────────────────────
    st.markdown("#### 2단계 · 녹음 전사")
    hw = config.hardware()
    if hw["device"] == "cuda":
        st.caption(f"{hw['gpu_name']} 사용 — 1시간 녹음에 대략 3~5분이 걸립니다.")
    else:
        st.warning(
            "GPU가 감지되지 않아 CPU로 처리합니다. 1시간 녹음에 20~40분이 걸릴 수 있습니다."
        )

    c1, c2 = st.columns(2)
    cross = c1.checkbox(
        "이중 모델 교차 검증", value=config.CROSS_VERIFY,
        help="두 모델로 각각 전사해 결과가 갈리는 구간을 '확인 필요'로 표시합니다. "
             "시간은 두 배로 들지만, 어디를 믿으면 안 되는지 알 수 있습니다.",
    )
    diar = c2.checkbox(
        "화자 자동 분리", value=bool(config.HF_TOKEN),
        help="누가 말했는지 나눕니다. HuggingFace 토큰이 필요합니다.",
        disabled=not config.HF_TOKEN,
    )
    if not config.HF_TOKEN:
        st.caption(
            "화자 분리를 쓰려면 `.env`에 `HF_TOKEN`이 필요합니다. "
            "huggingface.co에서 무료로 발급받은 뒤 "
            "`pyannote/speaker-diarization-3.1` 모델 페이지에서 이용 약관에 동의하세요."
        )

    _terms_editor()

    if st.button("녹음 전사 시작", type="primary", disabled=not pend_audio):
        _run(conn, kinds=(config.KIND_AUDIO,), cross_verify=cross, diarize=diar)

    st.divider()
    _status_table(conn)


def _terms_editor():
    """
    사건 고유명사 사전.

    Whisper 한국어 인식률은 영어보다 확연히 낮아 인명·상호·단지명이
    자주 틀린다. 미리 알려주면 그 단어를 맞게 적을 확률이 크게 오른다.
    """
    with st.expander("사건 고유명사 사전 (인식률이 눈에 띄게 좋아집니다)"):
        st.caption(
            "녹음에 나오는 사람 이름, 상호, 단지명, 계약 용어를 적어주세요. "
            "Whisper가 이 단어들을 우선해서 인식합니다. 쉼표 또는 줄바꿈으로 구분."
        )
        current = ""
        if config.CASE_TERMS_YAML.exists():
            try:
                import yaml
                data = yaml.safe_load(config.CASE_TERMS_YAML.read_text(encoding="utf-8"))
                current = ", ".join(data.get("고유명사", []) or [])
            except Exception:
                pass

        text = st.text_area(
            "고유명사", current, height=100,
            placeholder="홍길동, 김대표, 래미안원베일리, 확인설명서, 계약금, 중도금",
        )
        if st.button("사전 저장"):
            import yaml
            terms = [t.strip() for t in text.replace("\n", ",").split(",") if t.strip()]
            config.CASE_TERMS_YAML.write_text(
                yaml.safe_dump({"고유명사": terms}, allow_unicode=True),
                encoding="utf-8")
            st.success(f"{len(terms)}개 저장했습니다. 다음 전사부터 반영됩니다.")


def _run(conn, kinds, **kwargs):
    rows = pipeline.pending(conn, kinds=kinds)
    if not rows:
        st.info("처리할 자료가 없습니다.")
        return

    bar = st.progress(0.0)
    log = st.empty()
    lines = []

    def on_progress(i, total, name, msg):
        bar.progress(i / max(total, 1), text=f"[{i}/{total}] {name}")
        if msg != "처리 중...":
            lines.append(f"{'✅' if '실패' not in msg else '❌'} {name} — {msg}")
            log.markdown("\n\n".join(f"　{l}" for l in lines[-12:]))

    result = pipeline.run(conn, kinds=kinds, progress=on_progress, **kwargs)
    bar.empty()

    if result["failed"]:
        st.warning(f"완료 {result['done']}건 · 실패 {result['failed']}건 · "
                   f"구간 {result['segments']:,}개")
    else:
        st.success(f"완료 {result['done']}건 · 구간 {result['segments']:,}개 생성")

    # 의미 검색 인덱스 갱신
    with st.spinner("의미 검색 인덱스를 만드는 중..."):
        try:
            from evidence.search import embed
            n = embed.build_index(conn)
            if n:
                st.caption(f"의미 검색 인덱스 {n:,}건 추가")
        except Exception:
            pass


def _status_table(conn):
    st.markdown("#### 처리 상태")
    rows = conn.execute(
        "SELECT * FROM sources ORDER BY CASE status "
        "WHEN 'failed' THEN 0 WHEN 'registered' THEN 1 ELSE 2 END, id"
    ).fetchall()
    if not rows:
        return

    icon = {"registered": "⬜ 대기", "extracting": "🔄 처리중",
            "extracted": "✅ 완료", "verified": "✅ 완료", "failed": "❌ 실패"}
    for r in rows:
        name = Path(r["path"]).name
        line = f"{icon.get(r['status'], r['status'])}　**{name}**"
        if r["status_detail"]:
            line += f"　— {r['status_detail']}"
        if r["status"] == "failed":
            st.error(line)
        else:
            st.caption(line)
