# -*- coding: utf-8 -*-
"""
백업과 복원 — 소송 자료를 잃지 않기 위한 장치.

여기 쌓이는 것은 다시 만들기 어렵다. 몇 시간 걸린 전사 결과,
일일이 들어가며 확인한 청취 기록, 손으로 고친 화자 지정,
정리한 발췌 목록. 디스크가 고장 나거나 실수로 지우면 그게 전부 사라진다.

백업하는 것
  · evidence.db          전사·태그·확인 기록·발췌 목록 전부
  · ingest_log.jsonl     처리 이력 (무결성 증명의 일부)
  · keywords.yaml 등     사건 설정

백업하지 않는 것
  · 원본 파일 — 용량이 크고, 원본은 원래 자리에 그대로 있다.
    다만 어떤 원본이 어디 있었는지 목록과 해시는 함께 저장한다.
"""
import json
import os
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from . import config, db, integrity


def _safe_copy_db(dst: Path) -> None:
    """
    SQLite를 안전하게 복사한다.

    파일을 그냥 복사하면 쓰는 중인 내용이 잘려 깨진 DB가 나올 수 있다.
    SQLite의 backup API는 잠금을 제대로 다뤄 일관된 사본을 만든다.
    """
    src = sqlite3.connect(config.DB_PATH)
    out = sqlite3.connect(dst)
    try:
        src.backup(out)
    finally:
        out.close()
        src.close()


def _unique_path(out_dir: Path, stem: str, suffix: str) -> Path:
    """
    이미 있는 파일은 절대 덮어쓰지 않는다.

    파일명이 초 단위 시각뿐이면 같은 초에 두 번 만들 때 겹친다.
    백업을 덮어쓰는 것은 백업이 없는 것보다 나쁘다 — 있다고 믿고
    원본 정리를 해버릴 수 있기 때문이다.
    """
    candidate = out_dir / f"{stem}{suffix}"
    n = 2
    while candidate.exists():
        candidate = out_dir / f"{stem}_{n}{suffix}"
        n += 1
    return candidate


def create(out_dir=None, note: str = "") -> Path:
    """백업 파일 하나(zip)를 만든다."""
    out_dir = Path(out_dir or (config.WORK_DIR / "backups"))
    out_dir.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_path = _unique_path(out_dir, f"증거파인더_백업_{stamp}", ".zip")

    # 임시 DB도 고유하게. 두 백업이 동시에 돌면 서로의 임시 파일을 밟는다.
    fd, tmp_name = tempfile.mkstemp(prefix=".tmp_backup_", suffix=".db",
                                    dir=str(out_dir))
    os.close(fd)
    tmp_db = Path(tmp_name)
    tmp_db.unlink()          # sqlite backup API가 새로 만들게 비워둔다
    manifest = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "note": note,
        "db_path": str(config.DB_PATH),
        "sources": [],
    }

    try:
        if config.DB_PATH.exists():
            _safe_copy_db(tmp_db)
            conn = sqlite3.connect(tmp_db)
            conn.row_factory = sqlite3.Row
            try:
                for r in conn.execute(
                        "SELECT id, path, sha256, kind, bytes FROM sources"):
                    manifest["sources"].append(dict(r))
                manifest["stats"] = db.stats(conn)
            finally:
                conn.close()

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
            if tmp_db.exists():
                z.write(tmp_db, "evidence.db")
            if config.INGEST_LOG.exists():
                z.write(config.INGEST_LOG, "ingest_log.jsonl")
            for cfg in (config.KEYWORDS_YAML, config.CASE_TERMS_YAML,
                        config.LAW_SCOPE_YAML):
                if cfg.exists():
                    z.write(cfg, f"config/{cfg.name}")
            z.writestr("manifest.json",
                       json.dumps(manifest, ensure_ascii=False, indent=2))
            z.writestr("복원방법.txt", RESTORE_GUIDE)
    finally:
        if tmp_db.exists():
            tmp_db.unlink()

    integrity.log("backup_created", path=str(zip_path),
                  sources=len(manifest["sources"]), note=note)
    return zip_path


RESTORE_GUIDE = """\
증거파인더 백업 복원 방법
========================================

  이 zip 파일에는 분석 결과가 들어 있습니다.
  (원본 녹음·문서 파일은 들어 있지 않습니다 — 원래 자리에 그대로 있습니다.)

  복원하려면 명령 프롬프트에서:

      python -m evidence.backup --restore "이_파일_경로.zip"

  복원하면 지금 있는 분석 결과를 덮어씁니다.
  덮어쓰기 전에 현재 상태를 자동으로 한 번 더 백업합니다.

  원본 파일 목록과 해시는 manifest.json 에 들어 있습니다.
  원본을 다른 폴더로 옮기셨다면, 복원 후 [자료 등록] 탭에서
  새 위치를 다시 스캔하시면 됩니다.
"""


def inspect(zip_path) -> dict:
    """백업 안에 무엇이 들었는지 본다. 복원 전에 확인용."""
    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()
        manifest = {}
        if "manifest.json" in names:
            manifest = json.loads(z.read("manifest.json").decode("utf-8"))
    return {
        "path": str(zip_path),
        "files": names,
        "created_at": manifest.get("created_at"),
        "note": manifest.get("note", ""),
        "stats": manifest.get("stats", {}),
        "sources": manifest.get("sources", []),
        "size_mb": round(Path(zip_path).stat().st_size / 1024 / 1024, 2),
    }


def restore(zip_path, keep_current: bool = True) -> dict:
    """
    백업에서 복원한다.

    순서가 중요하다.
      1. 복원할 내용을 **먼저 메모리로 읽는다**
      2. 그 다음 현재 상태를 안전 백업한다
      3. 마지막에 덮어쓴다

    이 순서를 지키지 않으면, 안전 백업을 만드는 사이에 복원 대상 파일이
    영향을 받을 수 있다. 실제로 그런 일이 있었다: 안전 백업 파일명이
    복원 대상과 겹쳐 대상을 현재(빈) 상태로 덮어썼고, 그 덮어써진 파일을
    읽어 복원해 자료가 통째로 사라졌다. 안전장치가 자료를 파괴한 것이다.
    """
    zip_path = Path(zip_path).resolve()
    if not zip_path.exists():
        raise FileNotFoundError(f"백업 파일을 찾을 수 없습니다: {zip_path}")

    info = inspect(zip_path)

    # ── 1. 복원할 내용을 먼저 다 읽어둔다 ──────────────
    payload = {}
    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()
        if "evidence.db" not in names:
            raise ValueError("백업에 분석 결과(evidence.db)가 없습니다")
        for name in names:
            if name == "evidence.db" or name == "ingest_log.jsonl" \
                    or name.startswith("config/"):
                payload[name] = z.read(name)

    if not payload.get("evidence.db"):
        raise ValueError("백업 안의 분석 결과가 비어 있습니다")

    # ── 2. 현재 상태를 안전 백업 ──────────────────────
    safety = None
    if keep_current and config.DB_PATH.exists():
        # 복원하려는 백업과 같은 폴더에 둔다 — 사용자가 찾기 쉽도록.
        # create()가 고유 이름을 보장하므로 대상을 덮어쓰지 않는다.
        safety = create(zip_path.parent, note="복원 직전 자동 백업")
        if Path(safety).resolve() == zip_path:
            # 여기 오면 안 되지만, 안전장치는 두 겹이어야 한다.
            raise RuntimeError(
                "안전 백업이 복원 대상 파일을 덮어쓰려 했습니다. 복원을 중단합니다.")

    # ── 3. 덮어쓴다 ─────────────────────────────────
    # WAL 파일이 남아 있으면 복원한 DB와 섞여 엉뚱한 상태가 된다
    for suffix in ("-wal", "-shm", "-journal"):
        side = Path(str(config.DB_PATH) + suffix)
        if side.exists():
            side.unlink()

    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    config.DB_PATH.write_bytes(payload["evidence.db"])

    if payload.get("ingest_log.jsonl"):
        config.INGEST_LOG.parent.mkdir(parents=True, exist_ok=True)
        config.INGEST_LOG.write_bytes(payload["ingest_log.jsonl"])

    for name, data in payload.items():
        if name.startswith("config/"):
            (config.BASE_DIR / Path(name).name).write_bytes(data)

    # ── 4. 정말 복원되었는지 확인한다 ──────────────────
    verified = {}
    try:
        conn = sqlite3.connect(config.DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            from . import db as _db
            verified = _db.stats(conn)
        finally:
            conn.close()
    except Exception as e:
        raise RuntimeError(f"복원한 파일을 열 수 없습니다: {e}") from e

    expected = (info.get("stats") or {}).get("segments")
    if expected is not None and verified.get("segments", 0) != expected:
        raise RuntimeError(
            f"복원 결과가 백업 내용과 다릅니다 "
            f"(기대 {expected}구간 / 실제 {verified.get('segments', 0)}구간). "
            f"백업 파일이 손상되었을 수 있습니다."
            + (f" 복원 직전 상태는 여기 있습니다: {safety}" if safety else "")
        )

    integrity.log("backup_restored", path=str(zip_path),
                  safety_backup=str(safety) if safety else None,
                  segments=verified.get("segments", 0))
    return {"restored": info, "safety_backup": safety, "verified": verified}


def list_backups(out_dir=None) -> list[dict]:
    out_dir = Path(out_dir or (config.WORK_DIR / "backups"))
    if not out_dir.exists():
        return []
    rows = []
    for f in sorted(out_dir.glob("증거파인더_백업_*.zip"), reverse=True):
        try:
            rows.append(inspect(f))
        except Exception:
            continue
    return rows


def prune(keep: int = 10, out_dir=None) -> int:
    """오래된 백업을 정리한다. 최근 것 몇 개만 남긴다."""
    out_dir = Path(out_dir or (config.WORK_DIR / "backups"))
    files = sorted(out_dir.glob("증거파인더_백업_*.zip"), reverse=True)
    removed = 0
    for f in files[keep:]:
        try:
            f.unlink()
            removed += 1
        except OSError:
            continue
    return removed


def _main():
    import argparse

    from .console import marks, setup as console_setup
    console_setup()
    m = marks()

    ap = argparse.ArgumentParser(description="증거파인더 백업·복원")
    ap.add_argument("--create", action="store_true", help="지금 백업")
    ap.add_argument("--list", action="store_true", help="백업 목록")
    ap.add_argument("--restore", metavar="ZIP", help="백업에서 복원")
    ap.add_argument("--note", default="", help="백업 메모")
    ap.add_argument("--out", help="저장 위치")
    args = ap.parse_args()

    if args.create:
        p = create(args.out, args.note)
        info = inspect(p)
        print(f"백업 완료: {p}")
        print(f"  크기 {info['size_mb']}MB · 자료 {len(info['sources'])}건")
        s = info.get("stats") or {}
        if s:
            print(f"  구간 {s.get('segments', 0):,}개 · 발췌 {s.get('basket', 0)}건")
    elif args.list:
        rows = list_backups(args.out)
        if not rows:
            print("백업이 없습니다.")
            return
        print(f"백업 {len(rows)}개\n" + m["line"] * 62)
        for r in rows:
            s = r.get("stats") or {}
            print(f"  {Path(r['path']).name}")
            print(f"      {r['created_at']} · {r['size_mb']}MB · "
                  f"자료 {len(r['sources'])}건 · 구간 {s.get('segments', 0):,}개")
            if r["note"]:
                print(f"      메모: {r['note']}")
    elif args.restore:
        info = inspect(args.restore)
        print(f"복원할 백업: {info['created_at']} · 자료 {len(info['sources'])}건")
        ans = input("지금 분석 결과를 덮어씁니다. 계속할까요? (y/N) ").strip().lower()
        if ans != "y":
            print("취소했습니다.")
            return
        res = restore(args.restore)
        print("복원 완료")
        if res["safety_backup"]:
            print(f"  복원 전 상태는 여기에 저장했습니다: {res['safety_backup']}")
    else:
        ap.print_help()


if __name__ == "__main__":
    _main()
