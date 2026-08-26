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


def setup(quiet_warnings: bool = True) -> None:
    """CLI 진입점 맨 앞에서 한 번 부른다."""
    if quiet_warnings:
        quiet_known_warnings()
    for stream in (sys.stdout, sys.stderr):
        try:
            # 파이썬 3.7+
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            # 리다이렉트된 경우 등 — 조용히 넘어간다
            pass


# ─────────────────────────────────────────────────────────
# 경고 소음 정리
# ─────────────────────────────────────────────────────────
# 오류가 아닌데 화면 한복판에 길게 뜨는 것들. 사용자는 이걸 오류로 읽는다.
#
# 여기 적은 것만 숨긴다. 목록에 없는 경고는 그대로 둔다 —
# 진짜 문제를 숨기는 것이 소음보다 훨씬 나쁘다.
_HARMLESS = [
    # torchaudio 가 TorchCodec 으로 넘어가며 내는 폐기 예고.
    # 우리는 이 때문에 torchaudio 2.8 로 고정했다. 예고일 뿐 지금은 정상 동작한다.
    ("torchaudio._backend", None),
    ("has been deprecated", "torchaudio"),
    ("TorchCodec", "torchaudio"),
    # GPU 커널 최적화 도구가 없다는 알림. 없어도 동작한다.
    ("triton not found", None),
    # 모델 파일 형식 관련 안내
    ("TypedStorage is deprecated", None),
    ("torch.load", "weights_only"),
    # 윈도우에서 개발자 모드가 꺼져 있으면 huggingface_hub 이 캐시에 심볼릭 링크
    # 대신 파일을 복사한다는 안내를 길게 출력한다. 디스크를 조금 더 쓸 뿐,
    # 모델은 정상적으로 받아지고 정상적으로 읽힌다.
    ("cache-system uses symlinks", None),
    ("does not support symlinks", None),
]


def quiet_known_warnings() -> None:
    """알려진 무해한 경고만 숨긴다."""
    import warnings

    for text, module in _HARMLESS:
        try:
            warnings.filterwarnings(
                "ignore",
                message=f".*{text}.*",
                module=f".*{module}.*" if module else "",
            )
        except Exception:
            continue

    # 로깅으로 나오는 것도 있다 (경고 필터로는 안 잡힌다)
    try:
        import logging
        logging.getLogger("torio").setLevel(logging.ERROR)
        logging.getLogger("torchaudio").setLevel(logging.ERROR)
    except Exception:
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
