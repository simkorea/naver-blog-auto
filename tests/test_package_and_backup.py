# -*- coding: utf-8 -*-
"""
제출 패키지 · 발췌본 · 백업 검증.

여기서 확인하는 것
  · 원본 없이 패키지를 만들려는 시도가 정말 막히는가
  · 발췌본이 원본의 지정한 구간과 정확히 일치하는가
  · 해시가 원본 ↔ 사본 ↔ 목록 사이에서 어긋나지 않는가
  · 백업하고 복원했을 때 내용이 그대로인가
  · 원본을 실수로 덮어쓰려는 시도가 막히는가
  · 여러 스레드가 동시에 써도 깨지지 않는가
"""
import subprocess
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from conftest import Check, use_temp_db


def make_audio(path, seconds=30, marker_at=None):
    """검증용 오디오. marker_at 초 지점에 고음 표시를 넣는다."""
    from evidence import config
    exe = config.ffmpeg_path()
    if not exe:
        return False
    if marker_at is None:
        cmd = [exe, "-y", "-f", "lavfi", "-i",
               f"sine=frequency=300:duration={seconds}",
               "-c:a", "aac", "-b:a", "96k", str(path)]
    else:
        cmd = [exe, "-y",
               "-f", "lavfi", "-i", f"sine=frequency=200:duration={seconds}",
               "-f", "lavfi", "-i", "sine=frequency=3000:duration=0.1",
               "-filter_complex",
               f"[1]adelay={int(marker_at*1000)}|{int(marker_at*1000)}[m];"
               f"[0][m]amix=inputs=2:duration=first",
               "-c:a", "aac", "-b:a", "96k", str(path)]
    r = subprocess.run(cmd, capture_output=True, timeout=180)
    return r.returncode == 0 and path.exists()


def marker_offset(path):
    """클립 안에서 고음 표시가 몇 초 지점에 있는지."""
    import struct
    import wave

    from evidence import config
    exe = config.ffmpeg_path()
    probe = str(path) + ".probe.wav"
    subprocess.run([exe, "-y", "-i", str(path), "-ac", "1", "-ar", "16000",
                    "-c:a", "pcm_s16le", probe], capture_output=True, timeout=120)
    with wave.open(probe) as w:
        n = w.getnframes()
        data = struct.unpack(f"{n}h", w.readframes(n))
    win, best, best_e = 800, None, 0
    for i in range(0, max(0, len(data) - win), win // 2):
        seg = data[i:i + win]
        e = sum(abs(seg[j + 1] - seg[j]) for j in range(len(seg) - 1)) / len(seg)
        if e > best_e:
            best_e, best = e, i / 16000
    Path(probe).unlink(missing_ok=True)
    return best


def run(tmp_path) -> bool:
    config = use_temp_db(tmp_path)
    from evidence import backup, basket, db, integrity
    from evidence.report import clip, package

    c = Check("제출 패키지 · 백업")
    conn = db.init()
    ev = tmp_path / "증거"
    ev.mkdir()

    audio = ev / "20250314_143022_통화.m4a"
    has_audio = make_audio(audio, seconds=30, marker_at=13.0)
    if not has_audio:
        print("  (ffmpeg 없음 — 오디오 관련 검증 건너뜀)")

    (ev / "메모.txt").write_text("계약금 오천만원 입금 확인", encoding="utf-8")

    from evidence.ingest import pipeline, scanner
    scanner.scan(conn, ev, defaults={"counterparty": "홍길동"})
    pipeline.run(conn, kinds=pipeline.TEXT_KINDS)

    # ── 원본 해시 봉인 ────────────────────────
    src_row = conn.execute("SELECT * FROM sources WHERE kind='audio'").fetchone()
    if has_audio:
        db.write(conn, "UPDATE sources SET is_my_conversation='Y', "
                       "status='extracted' WHERE id=?", (src_row["id"],))
        db.add_segments(conn, src_row["id"], [
            {"seq": 1, "text": "설명드렸습니다", "start_sec": 12.0,
             "end_sec": 14.0, "speaker_label": "나", "confidence": 0.9},
        ])
        seg_id = conn.execute(
            "SELECT id FROM segments WHERE source_id=?",
            (src_row["id"],)).fetchone()[0]
        basket.add(conn, seg_id, "설명의무 이행 발언")

        # 담을 때 앞뒤 여유가 붙는지
        b = basket.get(conn, seg_id)
        c.ok(b["clip_start_sec"] < 12.0 and b["clip_end_sec"] > 14.0,
             "발췌 담을 때 앞뒤 여유가 붙는다",
             f"{b['clip_start_sec']}~{b['clip_end_sec']}")

        # 정확한 구간으로 조정
        basket.update(conn, seg_id, clip_start_sec=12.5, clip_end_sec=15.0)

    # ── 원본 없는 패키지 시도 ─────────────────
    check = package.preflight(conn, include_originals=False)
    c.ok(any("원본을 빼고는" in b for b in check["blockers"]),
         "원본 없이 만들려는 시도를 막는다")

    if not has_audio:
        conn.close()
        return c.report()

    # ── 패키지 생성 ──────────────────────────
    out = package.build(conn, tmp_path / "out", target="경찰서",
                        case_name="검증 사건")
    root = out["root"]

    for name in ("00_증거목록.xlsx", "01_재생안내서.docx", "02_녹취록발췌.docx",
                 "03_해시목록.txt", "README_먼저읽어주세요.txt"):
        c.ok((root / name).exists(), f"{name} 생성")
    c.ok((root / "원본").is_dir() and any((root / "원본").iterdir()),
         "원본 폴더에 파일이 들어간다")
    c.ok((root / "발췌본").is_dir(), "발췌본 폴더 생성")

    # ── 발췌본 정확도 ────────────────────────
    clips = [x for x in out["clips"] if x.get("ok")]
    c.eq(len(clips), 1, "발췌본 1개 생성")
    if clips:
        cl = clips[0]
        offset = marker_offset(cl["path"])
        # 12.5초부터 잘랐으니 13.0초 표시는 클립 내 0.5초 지점
        c.ok(abs(offset - 0.5) < 0.15,
             "발췌본이 지정한 구간과 일치한다",
             f"표시 위치 {offset:.3f}초 (기대 0.500초)")
        c.ok("00-00-12" in cl["name"] and "00-00-15" in cl["name"],
             "파일명에 원본 내 위치가 새겨진다", cl["name"])
        c.eq(cl["orig_sha256"], src_row["sha256"], "원본 해시가 함께 기록된다")

        # 클립 해시가 실제 파일과 맞는지
        actual = integrity.sha256_file(cl["path"])
        c.eq(actual, cl["sha256"], "발췌본 해시가 실제 파일과 일치한다")

    # ── 원본 사본 무결성 ──────────────────────
    for o in out["originals"]:
        c.eq(o["actual"], o["expected"],
             f"원본 사본 해시 일치 ({Path(o['dst']).name})")

    manifest = (root / "03_해시목록.txt").read_text(encoding="utf-8")
    c.ok(src_row["sha256"] in manifest, "해시목록에 원본 해시가 적힌다")
    if clips:
        c.ok(clips[0]["sha256"] in manifest, "해시목록에 발췌본 해시가 적힌다")
        c.ok("원본 내 위치" in manifest, "발췌본이 원본 어디서 나왔는지 적힌다")

    # ── 원본은 그대로인가 ─────────────────────
    rows = integrity.verify_all(conn)
    c.ok(all(r["status"] == "ok" for r in rows),
         "패키지를 만들어도 원본은 그대로다",
         f"{[(Path(r['path']).name, r['status']) for r in rows if r['status'] != 'ok']}")

    # ── 원본 덮어쓰기 시도 ────────────────────
    try:
        clip.extract(audio, 0, 1, audio, clip.MODE_PCM)
        c.ok(False, "원본 덮어쓰기를 막는다", "막지 못함")
    except integrity.ReadOnlyViolation:
        c.ok(True, "원본 덮어쓰기를 막는다")
    except Exception as e:
        c.ok(False, "원본 덮어쓰기를 막는다", f"다른 예외: {type(e).__name__}")

    # ── 백업 왕복 ────────────────────────────
    before = db.stats(conn)
    bp = backup.create(tmp_path / "bk", note="검증")
    info = backup.inspect(bp)
    c.ok(info["size_mb"] > 0, "백업 파일이 만들어진다")
    c.eq(len(info["sources"]), before["sources"], "백업에 자료 목록이 담긴다")

    # 자료를 지운 뒤 복원
    db.write(conn, "DELETE FROM segments")
    db.write(conn, "DELETE FROM basket")
    c.eq(db.stats(conn)["segments"], 0, "지운 상태 확인")
    conn.close()

    res = backup.restore(bp)
    conn = db.connect()
    after = db.stats(conn)
    c.eq(after["segments"], before["segments"], "복원하면 구간이 돌아온다")
    c.eq(after["basket"], before["basket"], "복원하면 발췌 목록도 돌아온다")

    # 복원이 백업 자체를 파괴하지 않는가 (실제로 그런 결함이 있었다)
    c.ok(bp.exists(), "복원해도 원래 백업 파일이 남아 있다")
    c.ok(Path(res["safety_backup"]).resolve() != bp.resolve(),
         "안전 백업이 복원 대상과 다른 파일이다",
         f"{Path(res['safety_backup']).name} vs {bp.name}")
    c.eq(backup.inspect(bp)["stats"]["segments"], before["segments"],
         "원래 백업의 내용이 그대로다")

    saved = backup.list_backups(tmp_path / "bk")
    c.ok(len(saved) >= 2, "복원 전 상태가 자동 백업된다", f"{len(saved)}개")

    # 복원 후 검색이 되는가 (FTS 인덱스가 함께 살아났는가)
    from evidence.search import hybrid
    c.ok(len(hybrid.search(conn, "계약금", use_semantic=False)) >= 1,
         "복원 후 검색이 정상 동작한다")

    # 같은 초에 여러 번 백업해도 덮어쓰지 않는가
    b1 = backup.create(tmp_path / "bk3")
    b2 = backup.create(tmp_path / "bk3")
    b3 = backup.create(tmp_path / "bk3")
    c.eq(len({b1.name, b2.name, b3.name}), 3,
         "같은 초에 백업해도 파일명이 겹치지 않는다")
    c.ok(all(x.exists() for x in (b1, b2, b3)), "세 백업이 모두 남는다")

    # 손상된 백업은 복원을 막는다
    import zipfile
    bad = tmp_path / "손상.zip"
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("manifest.json", "{}")
    try:
        backup.restore(bad)
        c.ok(False, "손상된 백업 복원을 막는다", "막지 못함")
    except (ValueError, RuntimeError):
        c.ok(True, "손상된 백업 복원을 막는다")

    # ── 동시 쓰기 ────────────────────────────
    errors = []

    seg_row = conn.execute("SELECT id FROM segments LIMIT 1").fetchone()
    c.ok(seg_row is not None, "동시성 검증을 위한 구간이 있다")
    any_seg = seg_row[0] if seg_row else None

    def worker(n):
        if any_seg is None:
            return
        try:
            for i in range(20):
                db.write(conn,
                         "INSERT INTO tags(segment_id, category, tag, engine) "
                         "VALUES (?, ?, ?, 'test')", (any_seg, f"t{n}", f"tag{i}"))
        except Exception as e:
            errors.append(f"{type(e).__name__}: {e}")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    c.eq(errors, [], "여러 스레드가 동시에 써도 깨지지 않는다")
    if any_seg is not None:
        c.eq(conn.execute(
            "SELECT count(*) FROM tags WHERE engine='test'").fetchone()[0],
            100, "동시 쓰기 결과가 모두 남는다")

    conn.close()
    return c.report()


if __name__ == "__main__":
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        sys.exit(0 if run(Path(d)) else 1)
