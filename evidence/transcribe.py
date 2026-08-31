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
    python evidence/transcribe.py --index    의미 검색 색인만 만들기
    python evidence/transcribe.py --voiceprint  목소리로 화자 묶기

의미 검색 색인이 왜 따로 있나
  검색창의 "의미 검색 함께"는 색인이 있어야 돈다. 색인이 없으면 체크가
  되어 있어도 **아무 일도 하지 않고** 정확히 그 단어만 찾는다.
  전사가 끝나면 이 스크립트가 색인까지 만든다. 다만 예전에 이 스크립트로
  전사만 해 둔 경우에는 색인이 없으므로 `--index` 로 따로 만든다.

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
    from evidence import version
    print(f"  코드            {version.label()}")
    print(M["line"] * 68)
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


def build_search_index(conn) -> int:
    """
    의미 검색 색인을 만든다. 돌려주는 값: 새로 넣은 구간 수.

    화면(`evidence/ui/tab_analyze.py`)이 전사 끝에 부르는 것과 **같은 함수**를
    쓴다. 여기에 그것이 빠져 있어서, 명령창으로 밤새 전사한 경우 검색창의
    "의미 검색 함께"가 켜져 있어도 아무 일도 하지 않았다.

    모델이 없거나 sqlite-vec 가 없으면 0을 돌려준다 — 키워드 검색은 그대로
    되므로 전사 결과를 못 쓰게 되는 일은 없다.
    """
    from evidence.search import embed

    state = {"last": 0.0}

    def on_progress(done, total):
        now = time.time()
        if now - state["last"] < 1.0 and done < total:
            return
        state["last"] = now
        pct = done / max(total, 1) * 100
        print(f"\r  의미 검색 색인  {done:,} / {total:,}  {pct:3.0f}%    ",
              end="", flush=True)

    n = embed.build_index(conn, progress=on_progress)
    print("\r" + " " * 60, end="\r")
    return n


def show_index_state(conn) -> None:
    """색인이 몇 건이나 있는지. 없으면 무엇을 뜻하는지 알려준다."""
    from evidence import db

    total = conn.execute("SELECT count(*) FROM segments").fetchone()[0]
    if not db.vec_available(conn):
        print(f"  {M['no']} 의미 검색을 쓸 수 없습니다 (sqlite-vec 없음). "
              "키워드 검색은 정상입니다.")
        return
    have = conn.execute("SELECT count(*) FROM vec_segments").fetchone()[0]
    if have >= total and total:
        print(f"  {M['ok']} 의미 검색 색인  {have:,} / {total:,}구간")
    else:
        print(f"  {M['no']} 의미 검색 색인  {have:,} / {total:,}구간 — "
              "지금은 정확히 그 단어만 찾습니다")
        print("      만들려면:  python evidence/transcribe.py --index")


def build_voiceprints(conn) -> dict:
    """
    목소리 지문을 만들고 파일을 가로질러 같은 사람끼리 묶는다.

    왜 필요한가 — `evidence/ingest/voiceprint.py` 맨 위에 적어 두었다.
    한 줄로: 화자 분리는 파일 하나씩 돌아가므로 'SPEAKER_00' 이 파일마다
    다른 사람이다. 그대로 이름을 붙이면 '나'와 '상대방'이 뒤바뀐다.
    """
    from evidence.ingest import voiceprint

    state = {"last": 0.0}

    def on_progress(i, total, name, speaker):
        now = time.time()
        if now - state["last"] < 0.5 and i < total:
            return
        state["last"] = now
        print(f"\r  목소리 지문  [{i}/{total}] {name[:38]} · {speaker}      ",
              end="", flush=True)

    made = voiceprint.build(conn, progress=on_progress)
    print("\r" + " " * 70, end="\r")
    n_groups = voiceprint.cluster(conn)
    made["groups"] = n_groups
    return made


def show_voiceprint_state(conn) -> None:
    """묶음이 몇 개인지, 사장님으로 보이는 묶음이 무엇인지."""
    from evidence.ingest import voiceprint

    gs = voiceprint.groups(conn)
    if not gs:
        n_spk = conn.execute(
            "SELECT count(DISTINCT source_id || '/' || speaker) FROM segments "
            "WHERE speaker IS NOT NULL").fetchone()[0]
        if n_spk:
            print(f"  {M['no']} 목소리 묶음 없음 — 화자 {n_spk}쌍이 아직 안 묶였습니다")
            print("      화자 이름을 붙이기 전에 반드시 만드세요:")
            print("        python evidence/transcribe.py --voiceprint")
        return

    print(f"  {M['ok']} 목소리 묶음  {len(gs)}명")
    me = voiceprint.suggest_me(conn)
    for g in gs[:6]:
        mark = "  ← 사장님으로 보임" if g["group_no"] == me else ""
        name = g["label"] or f"묶음 {g['group_no']}"
        print(f"      {name}  ·  통화 {g['file_count']}건  ·  "
              f"구간 {g['segments']:,}개{mark}")
    if len(gs) > 6:
        print(f"      … 그 밖 {len(gs) - 6}명")
    for w in voiceprint.problems(conn):
        print(f"      {M['no']} {w}")


def main() -> int:
    ap = argparse.ArgumentParser(description="증거파인더 전사 실행")
    ap.add_argument("--status", action="store_true", help="지금 상태만 보기")
    ap.add_argument("--text", action="store_true", help="텍스트 자료만 처리")
    ap.add_argument("--index", action="store_true",
                    help="전사는 하지 않고 의미 검색 색인만 만들기")
    ap.add_argument("--voiceprint", action="store_true",
                    help="목소리 지문으로 파일을 가로질러 화자 묶기")
    ap.add_argument("--no-cross", action="store_true",
                    help="이중 모델 교차 검증 끄기 (약 2배 빠름)")
    ap.add_argument("--no-diarize", action="store_true", help="화자 분리 끄기")
    args = ap.parse_args()

    from evidence import config, db
    from evidence.ingest import pipeline

    conn = db.init()
    show_status(conn, pipeline, config)

    if args.status:
        show_index_state(conn)
        show_voiceprint_state(conn)
        return 0

    if args.voiceprint:
        print("  목소리 지문을 만듭니다. 화자 분리에 쓰는 모델과 같은 것이라")
        print("  새로 받지 않습니다.\n")
        try:
            r = build_voiceprints(conn)
        except BaseException as e:
            print(f"  {M['no']} 만들지 못했습니다: {type(e).__name__}: {e}\n")
            return 1
        print(f"  {M['ok']} 지문 {r['made']}개를 만들고 {r['groups']}명으로 묶었습니다.")
        if r["failed"]:
            print(f"  {M['no']} 건너뛴 것 {len(r['failed'])}개:")
            for name, spk, why in r["failed"][:8]:
                print(f"      {name[:40]} · {spk} — {why}")
            if len(r["failed"]) > 8:
                print(f"      … 그 밖 {len(r['failed']) - 8}개")
        print()
        show_voiceprint_state(conn)
        print()
        print("  이제 화면 [③ 화자 지정] 에서 대표 발화를 들어보고")
        print("  '나' / '고객 ○○○' 으로 지정하세요. 한 번 지정하면 그 사람이")
        print("  나오는 모든 통화에 정확히 붙습니다.\n")
        return 0

    if args.index:
        # 전사는 건드리지 않는다. 색인만 만든다.
        print("  의미 검색 색인을 만듭니다. 처음이면 모델을 받느라 오래 걸립니다.\n")
        try:
            n = build_search_index(conn)
        except BaseException as e:
            print(f"  {M['no']} 색인을 만들지 못했습니다: {type(e).__name__}: {e}")
            print("      키워드 검색은 그대로 됩니다.\n")
            return 1
        if n:
            print(f"  {M['ok']} 의미 검색 색인 {n:,}건을 만들었습니다.\n")
        else:
            print("  새로 만들 것이 없습니다.\n")
        show_index_state(conn)
        print()
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

    # 전사 결과를 의미 검색으로도 찾을 수 있게 한다.
    # 화면은 이것을 이미 하고 있었는데 여기에만 빠져 있었다.
    if not result["stopped"]:
        try:
            n = build_search_index(conn)
            if n:
                print(f"  {M['ok']} 의미 검색 색인 {n:,}건 추가")
        except BaseException as e:
            # 색인을 못 만들어도 전사 결과는 멀쩡하다. 키워드 검색은 된다.
            print(f"  {M['no']} 의미 검색 색인 실패 ({type(e).__name__}) — "
                  "키워드 검색은 그대로 됩니다")

    # 화자 이름을 파일마다 정확히 붙이려면 목소리 지문이 있어야 한다.
    if not result["stopped"]:
        try:
            r = build_voiceprints(conn)
            if r["made"]:
                print(f"  {M['ok']} 목소리 지문 {r['made']}개 · {r['groups']}명으로 묶음")
        except BaseException as e:
            print(f"  {M['no']} 목소리 묶기 실패 ({type(e).__name__}) — "
                  "나중에 --voiceprint 로 다시 하세요")

    show_status(conn, pipeline, config)
    show_index_state(conn)
    show_voiceprint_state(conn)
    print()
    print("  이제 화면에서 검색하시면 됩니다.")
    print("      python -m streamlit run evidence/app.py --server.port 8532\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
