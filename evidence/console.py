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
#
# `module` 조건을 쓸 때 주의할 것 (실험으로 확인했다)
#   파이썬의 `module=` 은 경고를 **낸 라이브러리**가 아니라 **경고가 찍힌
#   자리의 모듈 이름**과 맞춰본다. torchaudio 의 폐기 예고 하나는
#   `pyannote/audio/core/io.py:85` 에서 찍히므로 모듈 이름이
#   `pyannote.audio.core.io` 다. 여기에 "torchaudio" 를 걸면 절대 안 맞는다.
#   그래서 torchaudio 폐기 예고들은 **문구로만** 잡는다.
#
#   다만 정직하게 적어 둔다 — 이 조건을 옛날로 되돌려도 검증은 통과한다.
#   지금 문구 안에 "TorchCodec" 이 들어 있어 다른 항목이 대신 잡아주기
#   때문이다. 즉 이건 결함을 고친 것이 아니라 **앞으로 문구가 바뀌어도
#   버티게 하는 대비**다. 실제로 막혀 있던 것은 (1) app.py 가 이 차단을
#   아예 안 켠 것, (2) 필터가 지워지는 경우였다.
_HARMLESS = [
    # torchaudio 가 TorchCodec 으로 넘어가며 내는 폐기 예고.
    # 우리는 이 때문에 torchaudio 2.8 로 고정했다. 예고일 뿐 지금은 정상 동작한다.
    # 화자 분리를 돌리면 오디오 조각마다 아래 셋이 반복해서 나온다.
    #   torchaudio/_backend/utils.py            load_with_torchcodec 예고
    #   pyannote/audio/core/io.py               ...utils.info has been deprecated
    #   torchaudio/_backend/soundfile_backend.py  AudioMetaData has been deprecated
    ("torchaudio._backend", None),
    ("has been deprecated", None),
    ("TorchCodec", None),
    ("load_with_torchcodec", None),
    ("AudioMetaData", None),
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
    # speechbrain 1.0 에서 모듈 이름이 바뀐 안내. pyannote 가 옛 이름으로
    # 부르지만 speechbrain 이 알아서 새 이름으로 넘겨준다. 동작에 문제 없다.
    ("was deprecated, redirecting to", None),
    ("speechbrain.pretrained", None),
]


def _harmless_patterns() -> list:
    """`_HARMLESS` 의 문구를 정규식으로 미리 컴파일해 둔다."""
    import re

    out = []
    for text, _module in _HARMLESS:
        try:
            out.append(re.compile(f".*{re.escape(text)}.*", re.S))
        except Exception:
            continue
    return out


def _install_showwarning_guard() -> None:
    """
    경고를 실제로 찍는 자리에 한 겹 덧댄다.

    왜 필터만으로는 부족한가 (실험으로 확인했다)
      라이브러리가 `warnings.catch_warnings()` 안에서
      `warnings.simplefilter("always")` 를 부르면 **우리가 걸어둔 차단 필터가
      그 안에서 통째로 지워진다.** 그러면 필터를 아무리 정확히 걸어도
      경고가 그대로 쏟아진다.

      `showwarning` 은 필터보다 뒤 단계라 `simplefilter` 로 지워지지 않는다.
      (`catch_warnings` 는 이것도 저장·복원하지만 **우리 것을** 복원한다)

    무엇을 거르나
      `_HARMLESS` 에 적은 문구만. 나머지는 원래 함수로 그대로 넘긴다 —
      모르는 경고를 숨기는 것이 소음보다 훨씬 나쁘다.
    """
    import warnings

    if getattr(warnings.showwarning, "_evidence_guard", False):
        return                      # 두 번 감싸지 않는다

    original = warnings.showwarning
    patterns = _harmless_patterns()

    def guarded(message, category, filename, lineno, file=None, line=None):
        try:
            text = str(message)
            if any(p.match(text) for p in patterns):
                return
        except Exception:
            pass                    # 판단이 안 되면 숨기지 않는다
        return original(message, category, filename, lineno, file, line)

    guarded._evidence_guard = True
    warnings.showwarning = guarded


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

    _install_showwarning_guard()

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
