"""
test_dashboard.py - 대시보드가 실제로 실행되는지 확인하는 스모크 테스트

Streamlit 공식 테스트 도구(AppTest)로 앱을 헤드리스 실행합니다.
브라우저 없이 돌기 때문에 CI 나 커밋 전 점검에 쓸 수 있습니다.

느립니다(앱 전체를 실행). 빠른 점검만 원하면:
    python -m pytest tests/test_regressions.py -q
"""
import sys
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

APP = str(BASE / "web_dashboard.py")


def _run_app(authenticated: bool = True):
    """로그인 게이트를 통과한 상태로 앱을 실행합니다."""
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(APP, default_timeout=300)
    if authenticated:
        at.session_state["authenticated"] = True
    at.run()
    return at


def _no_exception(at) -> None:
    if at.exception:
        msgs = "\n".join(str(e.value) for e in at.exception)
        pytest.fail(f"앱 실행 중 예외 발생:\n{msgs}")


@pytest.mark.slow
def test_대시보드가_예외없이_실행된다():
    at = _run_app()
    _no_exception(at)


@pytest.mark.slow
def test_탭이_다섯개_모두_있다():
    at = _run_app()
    _no_exception(at)
    # 홈 / 원고 에디터 / 이미지 생성 / 포스트 관리 / 시스템 상태
    assert len(at.tabs) >= 5, f"탭이 {len(at.tabs)}개뿐입니다"


@pytest.mark.slow
def test_트렌드_버튼을_눌러도_예외가_없다():
    """예전 버그: 위젯 생성 후 위젯 키를 직접 수정해서 StreamlitAPIException 발생.

    지금은 _pending_* 에 예약해두고 다음 실행 시작 지점에서 반영합니다.
    """
    at = _run_app()
    _no_exception(at)

    trend = [b for b in at.button if b.key and b.key.startswith("trend_btn_")]
    if not trend:
        pytest.skip("트렌드 뉴스를 불러오지 못해 버튼이 없습니다 (네트워크 문제)")

    trend[0].click().run()
    _no_exception(at)

    # 클릭하면 '키워드 검색 뉴스' 모드로 바뀌고 검색어가 채워져야 합니다.
    assert at.session_state["mode_radio"] == "키워드 검색 뉴스"
    assert at.session_state["kw_input"], "검색 키워드가 채워지지 않았습니다"
    # 예약 키는 소진돼야 합니다.
    leftover = [k for k in at.session_state.filtered_state if k.startswith("_pending")]
    assert not leftover, f"예약 키가 남아 있습니다: {leftover}"


@pytest.mark.slow
def test_로그인_게이트가_동작한다():
    """비로그인 상태에서는 본문 탭이 보이면 안 됩니다."""
    at = _run_app(authenticated=False)
    _no_exception(at)
    assert len(at.tabs) == 0, "로그인 전에 탭이 노출되고 있습니다"
