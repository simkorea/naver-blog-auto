# -*- coding: utf-8 -*-
"""
② 분석 실행 — 등록한 자료를 실제로 텍스트로 만든다.

텍스트 자료(카톡·문서·이미지)는 빠르니 먼저 돌리고,
음성은 시간이 걸리니 나눠서 돌릴 수 있게 했다.
중단해도 다음에 남은 것부터 이어서 처리한다.
"""
import time
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

    st.caption(
        "처음 전사할 때 음성 인식 모델을 내려받습니다(약 1.5GB, 몇 분). "
        "미리 받아두려면 명령 프롬프트에서 "
        "`python evidence/setup_check.py --models` 를 실행하세요."
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

    prep = st.selectbox(
        "음성 전처리",
        ["auto", "light", "standard", "strong", "none"],
        format_func=lambda k: {
            "auto": "자동 (음질을 보고 알아서 — 권장)",
            "light": "약하게 (음질이 좋은 녹음)",
            "standard": "보통",
            "strong": "세게 (잡음이 심한 통화)",
            "none": "안 함 (원본 그대로 전사)",
        }[k],
        help="전사하기 전에 잡음을 줄이고 음량을 고르게 맞춥니다. "
             "통화 녹음은 음질이 나빠 이걸 거치면 인식률이 눈에 띄게 오릅니다. "
             "원본은 건드리지 않고 임시 사본을 만들어 씁니다.",
    )

    _terms_editor()

    if st.button("녹음 전사 시작", type="primary", disabled=not pend_audio):
        _run(conn, kinds=(config.KIND_AUDIO,), cross_verify=cross, diarize=diar,
             preprocess_level=(None if prep == "auto" else prep))

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


def _fmt_dur(sec: float) -> str:
    """초를 사람이 읽는 시간으로."""
    sec = max(int(sec or 0), 0)
    h, rest = divmod(sec, 3600)
    m, s = divmod(rest, 60)
    if h:
        return f"{h}시간 {m}분"
    if m:
        return f"{m}분 {s}초"
    return f"{s}초"


def _run(conn, kinds, **kwargs):
    rows = pipeline.pending(conn, kinds=kinds)
    if not rows:
        st.info("처리할 자료가 없습니다.")
        return

    # 시작하자마자 "무엇을 건너뛰는지"를 말해준다.
    # 이걸 안 보여줘서, 남은 27건 중 1번째인 [1/27] 을 사용자가
    # "처음부터 다시 하는 것"으로 읽었다.
    skipping = pipeline.already_done(conn, kinds)
    interrupted = [r for r in rows if r["status"] == "extracting"]
    head = f"남은 {len(rows)}건을 처리합니다."
    if skipping:
        head = (f"이미 끝난 **{skipping}건은 건너뜁니다.** "
                f"남은 **{len(rows)}건**을 처리합니다.")
    if interrupted:
        head += (f" (그중 {len(interrupted)}건은 지난번에 중간에 멈춘 것이라 "
                 "그 파일만 처음부터 다시 합니다)")
    st.info(head)

    # 남은 시간 예상에 쓸 전체 길이. 길이를 모르는 파일은 빼고 센다.
    total_sec = sum(r["duration_sec"] or 0 for r in rows)
    done_sec = 0.0
    started = time.time()

    bar_all = st.progress(0.0, text=f"전체 0 / {len(rows)}건")
    bar_one = st.progress(0.0, text="준비 중...")
    eta_box = st.empty()
    log = st.empty()
    lines = []

    def _eta(processed_sec: float) -> str:
        """지금까지의 실제 속도로 남은 시간을 낸다."""
        if not total_sec or processed_sec <= 0:
            return ""
        elapsed = time.time() - started
        speed = processed_sec / max(elapsed, 0.1)      # 오디오 초 / 실제 초
        left = (total_sec - processed_sec) / max(speed, 1e-6)
        return f"남은 시간 약 {_fmt_dur(left)}"

    def on_file(i, total, name, frac):
        cur = rows[i - 1]["duration_sec"] or 0
        pos = f"{_fmt_dur(cur * frac)} / {_fmt_dur(cur)}" if cur else f"{frac * 100:.0f}%"
        bar_one.progress(min(max(frac, 0.0), 1.0), text=f"지금 · {name}　{pos}")
        eta = _eta(done_sec + cur * frac)
        if eta:
            eta_box.caption(eta)

    def on_progress(i, total, name, msg):
        nonlocal done_sec
        bar_all.progress((i - 1) / max(total, 1),
                         text=f"전체 {i - 1} / {total}건" +
                              (f"　·　이미 끝난 {skipping}건은 건너뜀" if skipping else ""))
        if msg == "처리 중...":
            bar_one.progress(0.0, text=f"지금 · {name}")
            return
        done_sec += rows[i - 1]["duration_sec"] or 0
        bar_all.progress(i / max(total, 1), text=f"전체 {i} / {total}건")
        lines.append(f"{'✅' if '실패' not in msg else '❌'} {name} — {msg}")
        log.markdown("\n\n".join(f"　{l}" for l in lines[-12:]))

    result = pipeline.run(conn, kinds=kinds, progress=on_progress,
                          file_progress=on_file, **kwargs)
    bar_all.empty()
    bar_one.empty()
    eta_box.empty()

    if result["failed"]:
        st.warning(f"완료 {result['done']}건 · 실패 {result['failed']}건 · "
                   f"구간 {result['segments']:,}개")
    else:
        st.success(f"완료 {result['done']}건 · 구간 {result['segments']:,}개 생성")
    st.caption(
        "여기서 창을 닫아도 끝난 것은 그대로 남습니다. "
        "다시 시작하면 남은 것부터 이어서 합니다."
    )

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

    # 'extracting' 은 아무것도 안 도는 상태에서도 남는다 — 처리 중에 창을
    # 닫거나 프로그램이 끊기면 그대로 굳는다. '처리중'으로 보여주면
    # 사용자는 지금 돌고 있는 줄 안다. 무엇을 다시 하게 되는지 밝힌다.
    icon = {"registered": "⬜ 대기", "extracting": "⏸ 중단됨 — 다시 하면 이 파일만 처음부터",
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
