# -*- coding: utf-8 -*-
"""
증거 무결성 — 이 프로그램에서 가장 양보할 수 없는 부분.

디지털 포렌식에서는 증거를 수집하는 즉시 해시를 기록해 둔다("디지털 봉인").
나중에 제출한 파일의 해시를 다시 계산해 그때와 같으면, 그 사이 1비트도
바뀌지 않았음이 증명된다. 반대로 해시가 다르면 그 증거는 신뢰를 잃는다.

여기서 제공하는 것
  sha256_file()   원본을 읽기 전용으로만 열어 해시 계산
  seal()          최초 등록 시 봉인 (해시 + 시각 기록)
  verify_all()    등록 당시 해시 ↔ 현재 해시 전수 대조
  log()           처리 이력을 append-only 로 남김

원본 파일은 이 모듈을 포함해 프로그램 어디서도 쓰기 모드로 열지 않는다.
"""
import hashlib
import json
import os
import sqlite3
import time
from datetime import datetime
from pathlib import Path

from . import config

_CHUNK = 1024 * 1024      # 1MB씩 읽어 큰 녹음 파일도 메모리 부담 없이 처리


# ─────────────────────────────────────────────────────────
# 해시
# ─────────────────────────────────────────────────────────
def sha256_file(path, progress=None) -> str:
    """
    파일의 SHA-256을 계산한다.

    progress: 콜백(읽은바이트, 전체바이트). 큰 파일 진행률 표시용.
    """
    p = Path(path)
    total = p.stat().st_size
    done = 0
    h = hashlib.sha256()
    # 'rb' — 읽기 전용. 원본을 건드리지 않는다.
    with p.open("rb") as f:
        while True:
            block = f.read(_CHUNK)
            if not block:
                break
            h.update(block)
            done += len(block)
            if progress:
                progress(done, total)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fingerprint(path) -> dict:
    """등록에 필요한 파일 지문 일체."""
    p = Path(path)
    st = p.stat()
    return {
        "path": str(p.resolve()),
        "sha256": sha256_file(p),
        "bytes": st.st_size,
        "mtime": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
    }


# ─────────────────────────────────────────────────────────
# 처리 이력 (append-only)
# ─────────────────────────────────────────────────────────
def log(event: str, **fields) -> None:
    """
    언제 무엇을 어떤 설정으로 처리했는지 기록한다.
    한 줄에 JSON 하나(JSONL). 절대 수정·삭제하지 않는다.
    """
    record = {"at": datetime.now().isoformat(timespec="seconds"), "event": event}
    record.update(fields)
    config.INGEST_LOG.parent.mkdir(parents=True, exist_ok=True)
    with config.INGEST_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def read_log(limit: int = 200) -> list[dict]:
    if not config.INGEST_LOG.exists():
        return []
    lines = config.INGEST_LOG.read_text(encoding="utf-8").splitlines()
    out = []
    for line in lines[-limit:]:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


# ─────────────────────────────────────────────────────────
# 읽기 전용 가드
# ─────────────────────────────────────────────────────────
class ReadOnlyViolation(RuntimeError):
    """원본을 수정하려는 시도. 프로그램 버그이므로 즉시 중단시킨다."""


def open_readonly(path):
    """원본 파일을 여는 유일한 통로. 쓰기 모드를 원천 봉쇄한다."""
    return Path(path).open("rb")


def guard_not_original(target, conn=None) -> None:
    """
    쓰기 대상이 등록된 원본과 같은 경로인지 확인한다.
    산출물 저장 직전에 호출해 실수로 원본을 덮어쓰는 사고를 막는다.
    """
    target = str(Path(target).resolve())
    if conn is None:
        if not config.DB_PATH.exists():
            return
        conn = sqlite3.connect(config.DB_PATH)
        close_after = True
    else:
        close_after = False
    try:
        row = conn.execute(
            "SELECT id FROM sources WHERE path = ?", (target,)
        ).fetchone()
        if row:
            raise ReadOnlyViolation(
                f"원본 파일에 쓰려고 했습니다: {target}\n"
                f"원본은 어떤 경우에도 수정하지 않습니다."
            )
    except sqlite3.OperationalError:
        pass          # 아직 테이블이 없는 경우
    finally:
        if close_after:
            conn.close()


# ─────────────────────────────────────────────────────────
# 전수 대조
# ─────────────────────────────────────────────────────────
def verify_all(conn=None, progress=None) -> list[dict]:
    """
    등록된 모든 원본의 해시를 다시 계산해 등록 당시 값과 대조한다.

    돌려주는 각 항목의 status
      ok        일치 — 원본이 그대로임
      CHANGED   불일치 — 원본이 변경됨 (증거 가치 손상, 즉시 확인 필요)
      MISSING   파일이 사라짐
    """
    close_after = conn is None
    if conn is None:
        conn = sqlite3.connect(config.DB_PATH)
    results = []
    try:
        rows = conn.execute(
            "SELECT id, path, sha256, bytes FROM sources ORDER BY id"
        ).fetchall()
        for i, (sid, path, expected, size) in enumerate(rows, 1):
            if progress:
                progress(i, len(rows), path)
            p = Path(path)
            if not p.exists():
                results.append({"id": sid, "path": path, "status": "MISSING",
                                "expected": expected, "actual": None})
                continue
            actual = sha256_file(p)
            results.append({
                "id": sid, "path": path,
                "status": "ok" if actual == expected else "CHANGED",
                "expected": expected, "actual": actual,
            })
    finally:
        if close_after:
            conn.close()

    bad = [r for r in results if r["status"] != "ok"]
    log("verify_all", total=len(results), failed=len(bad))
    return results


def format_hash_manifest(rows: list[dict]) -> str:
    """제출 패키지에 넣을 해시 목록 텍스트."""
    now = datetime.now().strftime("%Y년 %m월 %d일 %H:%M")
    lines = [
        "═" * 72,
        "  증거 파일 해시 목록 (SHA-256)",
        "═" * 72,
        "",
        f"  작성 일시 : {now}",
        "",
        "  이 목록은 각 파일의 SHA-256 해시값입니다.",
        "  해시값은 파일의 '디지털 지문'으로, 파일 내용이 1비트라도 달라지면",
        "  전혀 다른 값이 나옵니다. 제출된 파일의 해시를 다시 계산해 아래 값과",
        "  같다면, 수집 시점 이후 파일이 변경되지 않았음을 확인할 수 있습니다.",
        "",
        "  ※ 확인 방법 (윈도우 명령 프롬프트):",
        "       certutil -hashfile \"파일경로\" SHA256",
        "",
        "─" * 72,
        "",
    ]
    for r in rows:
        lines.append(f"  파일   : {r.get('name') or Path(r['path']).name}")
        lines.append(f"  구분   : {r.get('role', '원본')}")
        lines.append(f"  크기   : {r.get('bytes', 0):,} 바이트")
        lines.append(f"  등록시 : {r.get('expected', '')}")
        if r.get("actual") and r.get("actual") != r.get("expected"):
            lines.append(f"  현재   : {r['actual']}   ⚠ 불일치")
        else:
            lines.append(f"  현재   : {r.get('actual') or r.get('expected', '')}   (일치)")
        if r.get("orig_path"):
            lines.append(f"  원본대응: {Path(r['orig_path']).name} "
                         f"{r.get('orig_range', '')}")
        lines.append("")
    lines.append("─" * 72)
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────
# CLI:  python -m evidence.integrity --verify
# ─────────────────────────────────────────────────────────
def _main():
    import argparse

    from .console import marks, setup as console_setup
    console_setup()
    m = marks()

    ap = argparse.ArgumentParser(description="증거 원본 무결성 검사")
    ap.add_argument("--verify", action="store_true", help="등록된 원본 전수 대조")
    args = ap.parse_args()

    if not args.verify:
        ap.print_help()
        return

    if not config.DB_PATH.exists():
        print("등록된 자료가 없습니다. 먼저 프로그램에서 자료를 등록하세요.")
        return

    print("원본 무결성 검사 중...\n")

    def show(i, total, path):
        print(f"  [{i}/{total}] {Path(path).name}", end="\r")

    rows = verify_all(progress=show)
    print(" " * 70, end="\r")

    ok = [r for r in rows if r["status"] == "ok"]
    bad = [r for r in rows if r["status"] != "ok"]

    print(m["line"] * 60)
    print(f"  정상 {len(ok)}건 / 전체 {len(rows)}건")
    if bad:
        print(f"\n  [!] 문제 {len(bad)}건 - 확인이 필요합니다\n")
        for r in bad:
            print(f"    [{r['status']}] {r['path']}")
            if r["status"] == "CHANGED":
                print(f"        등록시 {r['expected']}")
                print(f"        현재   {r['actual']}")
        print("\n  원본이 변경되었거나 사라졌습니다.")
        print("  변경된 파일은 증거로서의 신뢰를 잃을 수 있으니 백업본을 확인하세요.")
    else:
        print(f"\n  {m['ok']} 모든 원본이 등록 당시와 동일합니다.")
    print(m["line"] * 60)


if __name__ == "__main__":
    _main()
