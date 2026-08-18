"""
menu.py - 바탕화면 실행기

'네이버 블로그 자동화.bat' 이 이 파일을 실행하고, 바탕화면 바로가기가 그 bat 을 가리킵니다.
할 일을 번호로 고르는 단순 메뉴입니다.
"""
import subprocess
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE = Path(__file__).resolve().parent


def _python() -> str:
    venv_py = BASE / "venv" / "Scripts" / "python.exe"
    return str(venv_py) if venv_py.exists() else sys.executable


def _run(*args: str) -> None:
    """프로젝트 폴더에서 파이썬 스크립트를 실행하고 끝날 때까지 기다립니다."""
    try:
        subprocess.run([_python(), *args], cwd=str(BASE))
    except KeyboardInterrupt:
        print("\n중단했습니다.")


def _banner() -> None:
    print("=" * 52)
    print("            네이버 블로그 자동화")
    print("=" * 52)
    print()
    print("  1. 대시보드 열기        (원고 작성·이미지·CTA 관리)")
    print("  2. 한 건 발행           (목록에서 골라 업로드)")
    print("  3. 여러 건 발행         (간격을 두고 순차 업로드)")
    print("  4. 발행 가능 목록만 보기")
    print()
    print("  0. 종료")
    print()


def main() -> None:
    while True:
        _banner()
        try:
            choice = input("번호를 고르세요: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return

        print()
        if choice == "1":
            _run("launcher.py")
        elif choice == "2":
            _run("publish.py")
        elif choice == "3":
            _run("publish.py", "--list")
            print("\n예시)  1 3 5 --gap 10        ->  1·3·5번을 10분 간격으로")
            print("      1 3 --gap 5-15        ->  5~15분 무작위 간격")
            print("      --all-new --gap 10    ->  아직 발행 안 한 글 전부")
            try:
                raw = input("\n번호와 옵션 입력 (취소는 Enter): ").strip()
            except (EOFError, KeyboardInterrupt):
                raw = ""
            if raw:
                _run("batch_publish.py", *raw.split())
        elif choice == "4":
            _run("publish.py", "--list")
        elif choice == "0":
            print("종료합니다.")
            return
        else:
            print("1 ~ 4 또는 0 을 입력해주세요.")

        print()
        try:
            input("계속하려면 Enter를 누르세요...")
        except (EOFError, KeyboardInterrupt):
            return
        print("\n" * 2)


if __name__ == "__main__":
    main()
