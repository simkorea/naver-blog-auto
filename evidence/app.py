# -*- coding: utf-8 -*-
"""
증거파인더 — 화면.

    streamlit run evidence/app.py            # http://localhost:8532

탭 구성
  1 자료 등록    폴더 스캔 · 해시 봉인 · 적법성 플래그
  2 분석 실행    텍스트 추출 → 음성 전사 → 교차 검증 → 화자 분리
  3 화자 지정    '화자1' → '나' / '고객 홍○○'
  4 검색         단어·문장 검색 → 청취 확인 → 발췌 담기
  5 타임라인     전 자료를 하나의 시간축에
  6 법률 코멘트  관련 조문·판례 (인용 검증 통과분만)
  7 제출 패키지  발췌본 추출 + 폴더 일괄 생성
  8 도구         백업·복원 · 내보내기 · 정리 · 처리 이력
"""
import sys
from pathlib import Path

# streamlit run 으로 실행하면 패키지 경로가 잡히지 않으므로 직접 넣어준다
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# 경고 소음 차단을 **torch·pyannote 를 불러오기 전에** 걸어야 한다.
# 화면에도 이것을 켜지 않아 화자 분리 중 torchaudio 폐기 예고문이
# 수백 줄씩 쏟아졌다 (명령창 쪽은 이미 켜져 있었다).
from evidence.console import setup as _console_setup       # noqa: E402
_console_setup()

import streamlit as st

from evidence import config, db, version
from evidence.ui import (tab_register, tab_analyze, tab_speakers, tab_search,
                         tab_timeline, tab_legal, tab_package, tab_tools)

st.set_page_config(page_title="증거파인더", page_icon="🔎", layout="wide")


# 증거파인더 전용 포트. `.streamlit/config.toml` 과 실행 스크립트가 같은 값을
# 쓴다 (tests/test_collector.py 가 어긋나면 잡아낸다).
#
# 왜 기본값 8501 을 안 쓰나
#   네이버 블로그 자동화의 대시보드도 Streamlit 이고, 둘 다 포트를 정하지
#   않으면 기본값 8501 로 겹친다. 증거파인더가 먼저 8501 을 차지하자 블로그
#   프로그램이 "대시보드가 이미 실행 중"으로 오판하고 브라우저만 열어
#   증거파인더 화면을 보여줬다. 먼저 쓰던 쪽(블로그)에 8501 을 돌려준다.
PORT = 8532


def app_url() -> str:
    """지금 이 화면의 주소. 실제로 뜬 포트를 우선 본다."""
    try:
        from streamlit.web.server.server import Server      # noqa: F401
    except BaseException:
        pass
    try:
        port = int(st.get_option("server.port") or PORT)
    except BaseException:
        port = PORT
    return f"http://localhost:{port}"


@st.cache_resource
def get_conn():
    return db.init()


def sidebar(conn):
    with st.sidebar:
        st.markdown("### 🔎 증거파인더")
        st.caption("녹음·문서·대화를 한곳에서 찾습니다")
        # 어느 주소에서 도는지 보여준다.
        # 네이버 블로그 대시보드도 Streamlit 이라 포트가 겹치면 서로를
        # 상대의 화면으로 착각한다. 실제로 그 일이 있었다.
        st.caption(f"이 화면 · {app_url()}")
        # 지금 도는 코드가 어느 버전인지. 이것이 없어서 "고쳤는데 왜 안 되냐"를
        # 되풀이했다 — 고친 코드가 안 돌고 있던 것이 원인이었는데 알 방법이
        # 없었다. git pull 을 했는데도 이 값이 안 바뀌면 **화면을 껐다 켜야 한다.**
        st.caption(f"코드 · {version.label()}")

        s = db.stats(conn)
        c1, c2 = st.columns(2)
        c1.metric("등록 자료", s["sources"])
        c2.metric("검색 구간", f"{s['segments']:,}")
        if s["pending"]:
            st.warning(f"미처리 {s['pending']}건 — [분석 실행] 탭에서 처리하세요")
        if s["needs_check"]:
            st.info(f"확인 필요 구간 {s['needs_check']:,}건")
        if s["basket"]:
            st.success(f"발췌 담긴 구간 {s['basket']}건")

        if s["unknown_legal"]:
            st.error(
                f"녹음 {s['unknown_legal']}건의 적법성이 미확인 상태입니다.\n\n"
                "[자료 등록] 탭에서 '내가 참여한 대화인가?'를 지정하세요."
            )

        st.divider()
        with st.expander("환경 점검"):
            try:
                for label, ok, msg in config.diagnose():
                    st.markdown(f"{'✅' if ok else '⬜'} **{label}** — {msg}")
            except BaseException as e:
                # 점검 자체가 실패해도 본 화면은 살아 있어야 한다
                st.caption(f"환경 점검을 실행하지 못했습니다 ({type(e).__name__})")

        st.divider()
        st.caption(
            "이 프로그램은 자료 정리·검색 도구이며 **법률 자문을 대체하지 않습니다.** "
            "증거 채택 여부와 제출 전략은 변호사와 상의하세요."
        )


def main():
    conn = get_conn()
    sidebar(conn)

    tabs = st.tabs([
        "① 자료 등록", "② 분석 실행", "③ 화자 지정", "④ 검색",
        "⑤ 타임라인", "⑥ 법률 코멘트", "⑦ 제출 패키지", "⑧ 도구",
    ])
    with tabs[0]:
        tab_register.render(conn)
    with tabs[1]:
        tab_analyze.render(conn)
    with tabs[2]:
        tab_speakers.render(conn)
    with tabs[3]:
        tab_search.render(conn)
    with tabs[4]:
        tab_timeline.render(conn)
    with tabs[5]:
        tab_legal.render(conn)
    with tabs[6]:
        tab_package.render(conn)
    with tabs[7]:
        tab_tools.render(conn)


if __name__ == "__main__":
    main()
