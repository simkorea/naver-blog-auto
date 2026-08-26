# -*- coding: utf-8 -*-
"""
윈도우 콘솔에서 한글·기호를 안전하게 출력하기 위한 준비.

왜 필요한가
  한국어 윈도우의 명령 프롬프트는 기본 인코딩이 cp949다.
  거기에 `✓` `✗` `═` 같은 기호를 출력하면 UnicodeEncodeError가 나면서
  **프로그램이 그 자리에서 죽는다.** 설치 진단이 첫 줄에서 멈추는 것이다.

  실제로 확인했다: ✓ ✗ ═ ⬜ 📁 는 cp949에 없다.

무엇을 하는가
  표준 출력을 UTF-8로 바꾸고, 그래도 못 쓰는 글자는 예외 대신
  대체 문자로 흘려보낸다. 화면이 조금 깨질지언정 프로그램이 멈추지는 않는다.

  `chcp 65001`을 실행한 콘솔에서는 그대로 예쁘게 나온다.
"""
import sys


def setup() -> None:
    """CLI 진입점 맨 앞에서 한 번 부른다."""
    for stream in (sys.stdout, sys.stderr):
        try:
            # 파이썬 3.7+
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            # 리다이렉트된 경우 등 — 조용히 넘어간다
            pass


# 화면 기호. 콘솔이 못 그리는 환경이면 ASCII로 대체된다.
def marks() -> dict:
    """
    쓸 수 있는 기호를 돌려준다.
    출력이 파일로 리다이렉트되었거나 인코딩이 좁으면 ASCII로 낮춘다.
    """
    enc = (getattr(sys.stdout, "encoding", "") or "").lower()
    rich = "utf" in enc
    if rich:
        return {"ok": "✓", "no": "✗", "dot": "·",
                "line": "─", "dline": "═", "star": "★"}
    return {"ok": "[O]", "no": "[X]", "dot": "-",
            "line": "-", "dline": "=", "star": "*"}
