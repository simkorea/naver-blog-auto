"""
launcher.py - 대시보드를 더블클릭으로 실행하기 위한 런처

'블로그 대시보드.bat' 이 이 파일을 실행합니다.
이미 켜져 있으면 새로 띄우지 않고 브라우저만 엽니다.
"""
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

PORT = 8501
BASE = Path(__file__).resolve().parent
URL  = f"http://localhost:{PORT}"

sys.path.insert(0, str(BASE))

# 시스템 파이썬으로 뜨면 대시보드가 playwright 를 못 찾습니다.
# 게다가 파이썬은 모듈을 한 번만 읽으므로, 잘못 뜬 대시보드는 살아 있는 동안
# 계속 "playwright가 설치되지 않았습니다" 를 냅니다. 진입점에서 막습니다.
from venv_guard import ensure_venv  # noqa: E402

ensure_venv()


def _port_open(port: int) -> bool:
    """해당 포트에서 이미 무언가 응답하는지 확인합니다."""
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _python() -> str:
    """venv 파이썬을 우선 사용하고, 없으면 현재 파이썬으로 폴백합니다."""
    venv_py = BASE / "venv" / "Scripts" / "python.exe"
    return str(venv_py) if venv_py.exists() else sys.executable


def main() -> None:
    if _port_open(PORT):
        print("대시보드가 이미 실행 중입니다 - 브라우저만 엽니다.")
        webbrowser.open(URL)
        return

    print("대시보드를 시작합니다... (창을 닫으면 종료됩니다)")
    proc = subprocess.Popen(
        [
            _python(), "-m", "streamlit", "run", str(BASE / "web_dashboard.py"),
            "--server.port", str(PORT),
            "--server.headless", "true",
        ],
        cwd=str(BASE),
    )

    # 서버가 뜰 때까지 최대 30초 기다렸다가 브라우저를 엽니다.
    for _ in range(60):
        if _port_open(PORT):
            break
        time.sleep(0.5)
    else:
        print("[경고] 서버가 30초 안에 뜨지 않았습니다. 아래 오류 메시지를 확인하세요.")

    webbrowser.open(URL)
    print(f"\n주소: {URL}")
    print("종료하려면 이 창을 닫거나 Ctrl+C 를 누르세요.\n")

    try:
        proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        print("\n종료했습니다.")


if __name__ == "__main__":
    main()
