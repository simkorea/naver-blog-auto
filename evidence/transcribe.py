# -*- coding: utf-8 -*-
"""
전사 실행 — 명령창에서 돌린다. 밤새 걸어둘 때 쓴다.

왜 화면(Streamlit)이 아니라 명령창인가
  Streamlit 은 브라우저와 연결이 끊기면 실행이 중단될 수 있다.
  브라우저를 실수로 닫거나, 절전으로 들어가거나, 새로고침만 해도 그렇다.
  몇 시간짜리 전사를 그렇게 돌리는 것은 위험하다.

  이 스크립트는 검은 창 하나로 돌아간다. 브라우저와 무관하다.

    python evidence/transcribe.py            남은 것 전부 전사
    python evidence/transcribe.py --status   지금 상태만 보기
    python evidence/transcribe.py --text     텍스트 자료만 (빠름)

이미 끝난 것은 건너뛴다
  `pipeline.pending()` 이 끝난 것(`extracted`)을 애초에 목록에서 뺀다.
  중간에 멈춰도 다시 실행하면 남은 것부터 이어서 한다.
  다만 **그때 처리 중이던 파일 하나는 처음부터 다시** 한다.
  그래서 Ctrl+C 를 누르면 지금 파일까지는 마치고 멈춘다.
"""
import argparse
import signal
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evidence.console import marks, setup as _console_setup

_console_setup()
M = marks()


def _dur(sec: float) -> str:
    sec = max(int(sec or 0), 0)
    h, rest = divmod(sec, 3600)
    m, s = divmod(rest, 60)
    if h:
        return f"{h}시간 {m}분"
    if m:
        return f"{m}분 {s}초"
    return f"{s}초"


def show_status(conn, pipeline, config) -> None:
    """지금 무엇이 남았는지. 화면과 같은 숫자가 나와야 한다."""
    from evidence import db

    s = db.stats(conn)
    pend_audio = pipeline.pending(conn, kinds=(config.KIND_AUDIO,))
    pend_text = pipeline.pending(conn, kinds=pipeline.TEXT_KINDS)
    stuck = [r for r in pend_audio if r["status"] == "extracting"]
    left_sec = sum(r["duration_sec"] or 0 for r in pend_audio)

    print()
    print(M["dline"] * 68)
    print("  증거파인더 · 처리 상태")
    print(M["dline"] * 68)
    print(f"  등록 자료      {s['sources']:,}건 (녹음 {s['audio']:,})")
    print(f"  처리 완료      {s['extracted']:,}건")
    print(f"  만들어진 구간  {s['segments']:,}개")
    print(f"  확인 필요      {s['needs_check']:,}구간")
    print(M["line"] * 68)
    print(f"  텍스트 대기    {len(pend_text):,}건")
    print(f"  녹음 대기      {len(pend_audio):,}건", end="")
    print(f"  (총 길이 {_dur(left_sec)})" if left_sec else "")
    if stuck:
        print(f"  {M['no']} 중간에 멈춘 것 {len(stuck)}건 — 그 파일만 처음부터 다시 합니다")
    print(M["dline"] * 68 + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description="증거파인더 전사 실행")
    ap.add_argument("--status", action="store_true", help="지금 상태만 보기")
    ap.add_argument("--text", action="store_true", help="텍스트 자료만 처리")
    ap.add_argument("--no-cross", action="store_true",
                    help="이중 모델 교차 검증 끄기 (약 2배 빠름)")
    ap.add_argument("--no-diarize", action="store_true", help="화자 분리 끄기")
    args = ap.parse_args()

    from evidence import config, db
    from evidence.ingest import pipeline

    conn = db.init()
    show_status(conn, pipeline, config)
    if args.status:
        return 0

    kinds = pipeline.TEXT_KINDS if args.text else (config.KIND_AUDIO,)
    rows = pipeline.pending(conn, kinds=kinds)
    if not rows:
        print("  처리할 것이 없습니다.\n")
        return 0

    skipping = pipeline.already_done(conn, kinds)
    if skipping:
        print(f"  이미 끝난 {skipping}건은 건너뜁니다. "
              f"남은 {len(rows)}건을 처리합니다.\n")

    # Ctrl+C 를 눌러도 지금 파일까지는 마친다.
    # 중간에 끊으면 그 파일을 처음부터 다시 해야 하기 때문이다.
    asked_stop = {"v": False}

    def _on_sigint(signum, frame):
        if asked_stop["v"]:
            print("\n  바로 멈춥니다 (지금 파일은 다음에 처음부터 다시 합니다).")
            raise KeyboardInterrupt
        asked_stop["v"] = True
        print("\n  멈추라는 신호를 받았습니다. "
              "지금 파일까지 마치고 멈춥니다 (한 번 더 누르면 바로 멈춤).")

    try:
        signal.signal(signal.SIGINT, _on_sigint)
    except (ValueError, OSError, AttributeError):
        pass          # 신호를 못 다는 환경이면 그냥 진행한다

    total_sec = sum(r["duration_sec"] or 0 for r in rows)
    state = {"done_sec": 0.0, "started": time.time(), "last": 0.0}

    def on_file(i, total, name, frac):
        # 너무 자주 찍으면 화면이 지저분하다. 1초에 한 번만.
        now = time.time()
        if now - state["last"] < 1.0 and frac < 1.0:
            return
        state["last"] = now
        cur = rows[i - 1]["duration_sec"] or 0
        processed = state["done_sec"] + cur * frac
        eta = ""
        if total_sec and processed > 0:
            speed = processed / max(now - state["started"], 0.1)
            eta = f"  남은 시간 약 {_dur((total_sec - processed) / max(speed, 1e-6))}"
        print(f"\r  [{i}/{total}] {name[:44]}  {frac * 100:3.0f}%{eta}    ",
              end="", flush=True)

    def on_progress(i, total, name, msg):
        if msg == "처리 중...":
            print(f"\r  [{i}/{total}] {name[:44]}  시작...    ", end="", flush=True)
            return
        state["done_sec"] += rows[i - 1]["duration_sec"] or 0
        mark = M["ok"] if "실패" not in msg else M["no"]
        print(f"\r  {mark} [{i}/{total}] {name[:44]} — {msg}" + " " * 20)

    kwargs = {}
    if args.no_cross:
        kwargs["cross_verify"] = False
    if args.no_diarize:
        kwargs["diarize"] = False

    try:
        result = pipeline.run(conn, kinds=kinds, progress=on_progress,
                              file_progress=on_file,
                              stop=lambda: asked_stop["v"], **kwargs)
    except KeyboardInterrupt:
        print("\n  멈췄습니다. 다시 실행하면 남은 것부터 이어서 합니다.\n")
        return 130

    print()
    print(M["line"] * 68)
    if result["stopped"]:
        print(f"  중간에 멈췄습니다 — 완료 {result['done']}건 · "
              f"구간 {result['segments']:,}개")
        print("  다시 실행하면 남은 것부터 이어서 합니다.")
    elif result["failed"]:
        print(f"  {M['no']} 완료 {result['done']}건 · 실패 {result['failed']}건 · "
              f"구간 {result['segments']:,}개")
    else:
        print(f"  {M['ok']} 완료 {result['done']}건 · "
              f"구간 {result['segments']:,}개 만들었습니다")
    print(M["line"] * 68)

    show_status(conn, pipeline, config)
    print("  이제 화면에서 검색하시면 됩니다.")
    print("      python -m streamlit run evidence/app.py --server.port 8532\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
