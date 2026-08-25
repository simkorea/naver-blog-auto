"""
venv_guard.py - 항상 프로젝트 venv 파이썬으로 실행되도록 보장합니다.

왜 필요한가
-----------
실행기를 어떻게 띄우느냐에 따라(바탕화면 바로가기, .bat 더블클릭,
menu.py 직접 실행, 터미널에서 python menu.py ...) 시스템 파이썬이
선택될 수 있습니다. 그러면 venv 에만 설치된 playwright 같은 패키지를
찾지 못해 "playwright가 설치되지 않았습니다" 같은 오류가 납니다.

더 고약한 점은, 파이썬이 모듈을 한 번만 읽는다는 것입니다.
잘못된 파이썬으로 뜬 대시보드는 그 판정을 프로세스가 죽을 때까지
그대로 유지하므로, 나중에 패키지를 설치해도 계속 실패합니다.

그래서 진입점에서 스스로 venv 파이썬으로 다시 실행합니다.
"""
import os
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
VENV_PYTHON = BASE / "venv" / "Scripts" / "python.exe"

# 무한 재실행을 막는 표시
_GUARD_ENV = "NBA_VENV_GUARD"


def running_in_venv() -> bool:
    """지금 이 프로세스가 프로젝트 venv 파이썬으로 돌고 있는지."""
    if not VENV_PYTHON.exists():
        return True          # venv 자체가 없으면 확인할 방법이 없으니 통과
    try:
        return Path(sys.executable).resolve() == VENV_PYTHON.resolve()
    except Exception:
        return False


def ensure_venv() -> None:
    """venv 파이썬이 아니면, 같은 인자로 venv 파이썬에서 다시 실행합니다.

    재실행에 성공하면 이 함수는 돌아오지 않습니다(현재 프로세스 종료).
    """
    if running_in_venv() or os.environ.get(_GUARD_ENV):
        return

    if not VENV_PYTHON.exists():
        print("[안내] venv 를 찾지 못했습니다. 현재 파이썬으로 계속합니다.")
        print(f"       필요하면 다음으로 만드세요:  python -m venv venv")
        return

    print(f"[안내] venv 파이썬으로 다시 실행합니다.\n"
          f"       (현재: {sys.executable})")

    env = dict(os.environ, **{_GUARD_ENV: "1"})
    try:
        import subprocess
        rc = subprocess.run([str(VENV_PYTHON), *sys.argv], cwd=str(BASE), env=env).returncode
    except Exception as e:
        print(f"[경고] venv 재실행 실패({e}). 현재 파이썬으로 계속합니다.")
        return
    sys.exit(rc)
