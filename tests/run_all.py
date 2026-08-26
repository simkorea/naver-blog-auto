# -*- coding: utf-8 -*-
"""
전체 검증 실행기.

    python tests/run_all.py

모델을 내려받지 않고도 돌아간다. Whisper·화자분리·임베딩·법령 API는
실제 모델이 내놓는 것과 같은 모양의 가짜를 끼워 넣어, **우리 코드**가
그것을 제대로 다루는지 본다. 모델 자체의 정확도는 우리 검증 대상이 아니다.
"""
import importlib
import sys
import tempfile
import time
import traceback
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent))

from evidence.console import marks, setup as _console_setup

_console_setup()
M = marks()

SUITES = [
    ("음성 파이프라인", "test_audio_pipeline",
     "전사 처리 · 신뢰도 · 환청 탐지 · 교차 검증 · 화자 매칭"),
    ("검색 · 법률", "test_search_and_law",
     "한국어 검색 · RRF 융합 · 인용 위조 차단"),
    ("법제처 파싱", "test_law_parsing",
     "조문·판례 원문 추출 · 깨진 응답 대응"),
    ("견고성", "test_robustness",
     "손상 파일 · 인코딩 · 극단 입력 · 원본 변조 감지"),
    ("제출 패키지 · 백업", "test_package_and_backup",
     "발췌 정확도 · 해시 사슬 · 백업 왕복 · 동시성"),
]


def main() -> int:
    print(M["dline"] * 70)
    print("  증거파인더 전체 검증")
    print(M["dline"] * 70)

    results = []
    started = time.time()

    for title, module_name, desc in SUITES:
        print(f"\n▶ {title} — {desc}")
        try:
            mod = importlib.import_module(module_name)
            importlib.reload(mod)
            with tempfile.TemporaryDirectory() as d:
                ok = mod.run(Path(d))
            results.append((title, ok, None))
        except Exception as e:
            results.append((title, False, f"{type(e).__name__}: {e}"))
            print(f"\n{M['no']} {title} - 실행 중 오류")
            traceback.print_exc(limit=4)

    elapsed = time.time() - started
    passed = [t for t, ok, _ in results if ok]
    failed = [(t, err) for t, ok, err in results if not ok]

    print("\n" + M["dline"] * 70)
    for title, ok, err in results:
        print(f"  {M['ok'] if ok else M['no']} {title}" + (f"  ({err})" if err else ""))
    print(M["line"] * 70)
    print(f"  묶음 {len(passed)}/{len(results)} 통과  {M['dot']}  {elapsed:.1f}초")

    if failed:
        print("\n  실패한 묶음을 따로 돌려 자세히 보세요:")
        for title, _ in failed:
            name = next(m for t, m, _ in SUITES if t == title)
            print(f"      python tests/{name}.py")
    else:
        print("\n  모든 검증을 통과했습니다.")
        print("\n  다만 아래는 이 방식으로 확인할 수 없습니다 (실제 모델·실제 API 필요):")
        print("    · Whisper 한국어 인식 품질        · pyannote 화자 분리 정확도")
        print("    · BGE-M3 의미 검색 품질           · 법제처 실제 응답 형태")
        print("    · 윈도우 경로·인코딩·.bat 동작")
    print(M["dline"] * 70)
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
