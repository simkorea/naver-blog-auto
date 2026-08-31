# -*- coding: utf-8 -*-
"""
설정 비교 — 같은 녹음을 여러 설정으로 전사해 나란히 놓는다.

왜 필요한가
  "정확도를 올리고 싶다"에 답하려면 **무엇이 실제로 나은지 재야 한다.**
  설정을 바꿔 53건을 밤새 다시 돌린 뒤 "느낌상 나아진 것 같다"로는
  판단할 수 없다. 더 나빠졌어도 알 방법이 없다.

  그래서 짧은 녹음 하나로 먼저 잰다. 몇 십 분이면 끝나고, 그 결과로
  정한 설정으로 전체를 돌린다.

    python evidence/tune.py                  가장 짧은 녹음으로 비교
    python evidence/tune.py --file 김애숙     이름에 그 글자가 든 녹음으로
    python evidence/tune.py --minutes 3      앞 3분만 (빠르게)

무엇을 견주나
  현재       지금 쓰는 설정 그대로 (비교의 기준)
  정밀       beam 10 · patience 2 — 느리지만 꼼꼼하게
  전처리약   잡음 제거를 약하게 (과하게 지우면 말도 같이 지워진다)
  전처리강   잡음 제거를 강하게 (통화 녹음처럼 음질이 나쁠 때)
  2차모델    large-v3-turbo — 다른 모델은 다르게 틀린다

읽는 법
  정답이 없으므로 "어느 것이 맞다"를 프로그램이 정해줄 수 없다.
  **사장님이 아는 사실**(사람 이름·단지명·금액)이 제대로 적힌 쪽이
  더 나은 설정이다. 그래서 서로 다른 곳만 뽑아 나란히 보여준다.
"""
import argparse
import difflib
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evidence.console import marks, setup as _console_setup

_console_setup()
M = marks()

# (이름, 설명, 바꿀 설정)
PRESETS = [
    ("현재", "지금 쓰는 설정 — 비교의 기준", {}),
    ("정밀", "beam 10 · patience 2 (느림)", {"beam": 10, "patience": 2}),
    ("전처리약", "잡음 제거 약하게", {"level": "light"}),
    ("전처리강", "잡음 제거 강하게", {"level": "strong"}),
    ("2차모델", "large-v3-turbo — 다르게 틀린다", {"model": "SECONDARY"}),
]


def pick_source(conn, want: str = None) -> dict:
    """비교에 쓸 녹음 하나. 짧을수록 빨리 끝난다."""
    sql = ("SELECT id, path, duration_sec FROM sources "
           "WHERE kind = 'audio' AND status IN ('extracted','verified')")
    args = []
    if want:
        sql += " AND path LIKE ?"
        args.append(f"%{want}%")
    sql += " ORDER BY COALESCE(duration_sec, 999999), id LIMIT 1"
    r = conn.execute(sql, args).fetchone()
    return dict(r) if r else None


def run_preset(path, opts: dict, minutes: float, terms) -> tuple:
    """설정 하나로 전사한다. 돌려주는 값: (구간 목록, 걸린 초)"""
    import os
    from evidence import config
    from evidence.ingest import audio

    # 손잡이는 config 의 값을 잠깐 바꿔 넣는다. 전사 경로는 손대지 않는다 —
    # 실제로 쓰이는 그 경로로 재야 의미가 있다.
    keep = (config.WHISPER_BEAM, config.WHISPER_PATIENCE)
    config.WHISPER_BEAM = opts.get("beam", keep[0])
    config.WHISPER_PATIENCE = opts.get("patience", keep[1])
    model = (config.WHISPER_SECONDARY if opts.get("model") == "SECONDARY"
             else config.WHISPER_PRIMARY)
    level = opts.get("level")

    started = time.time()
    try:
        rows = audio.transcribe(path, model, preprocess_level=level)
    finally:
        config.WHISPER_BEAM, config.WHISPER_PATIENCE = keep

    if minutes:
        cut = minutes * 60
        rows = [r for r in rows if (r.get("start_sec") or 0) < cut]
    return rows, time.time() - started


def text_of(rows) -> str:
    return " ".join((r.get("text") or "").strip() for r in rows)


def differences(base_rows, other_rows, limit: int = 12) -> list:
    """
    두 결과가 갈리는 곳만 뽑는다.

    글자 단위로 견주면 띄어쓰기 차이까지 잡혀 읽기 어렵다.
    그래서 낱말 단위로 견주고, 갈린 자리 앞뒤를 붙여 보여준다.
    """
    a, b = text_of(base_rows).split(), text_of(other_rows).split()
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    out = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        left = " ".join(a[max(0, i1 - 4):i1])
        out.append({
            "before": left,
            "base": " ".join(a[i1:i2]) or "(없음)",
            "other": " ".join(b[j1:j2]) or "(없음)",
        })
        if len(out) >= limit:
            break
    return out


def similarity(base_rows, other_rows) -> float:
    a, b = text_of(base_rows).split(), text_of(other_rows).split()
    if not a and not b:
        return 1.0
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()


def _dur(sec) -> str:
    sec = int(sec or 0)
    return f"{sec // 60}분 {sec % 60}초" if sec >= 60 else f"{sec}초"


def main() -> int:
    ap = argparse.ArgumentParser(description="전사 설정 비교")
    ap.add_argument("--file", help="이름에 이 글자가 든 녹음으로 비교")
    ap.add_argument("--minutes", type=float, default=0,
                    help="앞 N분만 비교 (0이면 전체)")
    ap.add_argument("--only", help="쉼표로 고른 설정만 (예: 현재,정밀)")
    ap.add_argument("--out", help="결과를 저장할 폴더")
    args = ap.parse_args()

    from evidence import config, db
    from evidence.ingest import audio

    try:
        conn = db.init()
    except db.DatabaseBusy as e:
        print(f"\n  {M['no']} 시작하지 못했습니다\n")
        print("  " + str(e).replace("\n", "\n  ") + "\n")
        return 1

    src = pick_source(conn, args.file)
    if not src:
        print("\n  비교할 녹음이 없습니다. 먼저 전사를 끝내세요.\n")
        return 1

    path = Path(src["path"])
    if not path.exists():
        print(f"\n  {M['no']} 원본을 찾을 수 없습니다: {path}\n")
        return 1

    presets = PRESETS
    if args.only:
        want = {w.strip() for w in args.only.split(",") if w.strip()}
        presets = [p for p in PRESETS if p[0] in want] or PRESETS

    terms = audio.case_terms()
    print()
    print(M["dline"] * 74)
    print("  전사 설정 비교")
    print(M["dline"] * 74)
    print(f"  녹음        {path.name}")
    print(f"  길이        {_dur(src['duration_sec'])}"
          + (f"  (앞 {args.minutes:g}분만 비교)" if args.minutes else ""))
    print(f"  고유명사    {len(terms)}개"
          + ("   ← 비어 있습니다. 이것부터 채우는 것이 가장 큽니다."
             if len(terms) < 10 else ""))
    print(f"  견줄 설정   {len(presets)}가지")
    print(M["dline"] * 74)
    print()

    results = []
    for i, (name, why, opts) in enumerate(presets, 1):
        print(f"  [{i}/{len(presets)}] {name} — {why} … ", end="", flush=True)
        try:
            rows, took = run_preset(path, opts, args.minutes, terms)
        except BaseException as e:
            print(f"{M['no']} 실패 ({type(e).__name__}: {e})")
            continue
        print(f"{M['ok']} 구간 {len(rows)}개 · {_dur(took)}")
        results.append({"name": name, "why": why, "rows": rows, "took": took})

    if len(results) < 2:
        print("\n  견줄 것이 없습니다.\n")
        return 1

    base = results[0]
    print()
    print(M["line"] * 74)
    print("  기준(" + base["name"] + ") 과 얼마나 다른가")
    print(M["line"] * 74)
    for r in results[1:]:
        sim = similarity(base["rows"], r["rows"])
        speed = r["took"] / max(base["took"], 0.1)
        print(f"  {r['name']:<8} 같은 정도 {sim * 100:5.1f}%   "
              f"걸린 시간 {speed:4.1f}배   구간 {len(r['rows'])}개")
    print()
    print("  ※ 같은 정도가 낮다고 나쁜 것이 아닙니다. **다르다**는 뜻일 뿐입니다.")
    print("     아래에서 사장님이 아는 사실이 제대로 적힌 쪽을 고르세요.")

    lines = []
    for r in results[1:]:
        diffs = differences(base["rows"], r["rows"])
        lines.append("")
        lines.append(M["dline"] * 74)
        lines.append(f"  {base['name']}  vs  {r['name']}   — 갈리는 곳 {len(diffs)}군데")
        lines.append(M["dline"] * 74)
        if not diffs:
            lines.append("  다른 곳이 없습니다.")
            continue
        for d in diffs:
            if d["before"]:
                lines.append(f"    … {d['before']}")
            lines.append(f"      {base['name']:<8} {d['base']}")
            lines.append(f"      {r['name']:<8} {d['other']}")
            lines.append("")

    print("\n".join(lines))

    out_dir = Path(args.out) if args.out else (config.WORK_DIR / "설정비교")
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    report = out_dir / f"설정비교_{path.stem[:30]}_{stamp}.txt"
    body = [f"전사 설정 비교 — {path.name}", ""]
    for r in results:
        body += [M["dline"] * 74, f"[{r['name']}] {r['why']}  ({_dur(r['took'])})",
                 M["dline"] * 74, text_of(r["rows"]), ""]
    body += lines
    report.write_text("\n".join(body), encoding="utf-8")

    print(M["line"] * 74)
    print(f"  전문을 저장했습니다 — {report}")
    print()
    print("  마음에 드는 설정을 정하셨으면 .env 에 적고 전체를 다시 돌립니다:")
    print("      WHISPER_BEAM=10")
    print("      WHISPER_PATIENCE=2")
    print("      PREPROCESS_LEVEL=strong")
    print("      python evidence/transcribe.py --redo")
    print(M["line"] * 74 + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
