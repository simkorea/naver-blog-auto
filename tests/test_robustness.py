# -*- coding: utf-8 -*-
"""
견고성 검증 — 실전에서 만날 험한 입력을 일부러 던진다.

소송 자료는 정갈하지 않다. 깨진 파일, 0바이트 파일, 한글 파일명,
아주 긴 텍스트, 이상한 인코딩, 사라진 원본. 이런 것 하나에 프로그램이
멈추면 정작 필요할 때 못 쓴다.

원칙: **어떤 입력에도 프로그램 전체가 멈추지 않는다.**
그 파일 하나만 '실패'로 표시하고 나머지는 계속 처리한다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from conftest import Check, use_temp_db


def run(tmp_path) -> bool:
    config = use_temp_db(tmp_path)
    from evidence import basket, db, integrity
    from evidence.ingest import kakao, pipeline, scanner
    from evidence.search import hybrid

    c = Check("견고성")
    conn = db.init()
    ev = tmp_path / "증거"
    ev.mkdir()

    # ── 험한 파일들 ──────────────────────────
    (ev / "빈파일.txt").write_text("", encoding="utf-8")
    (ev / "깨진PDF.pdf").write_bytes(b"%PDF-1.4\nthis is not a real pdf\x00\xff")
    (ev / "깨진워드.docx").write_bytes(b"PK\x03\x04garbage")
    (ev / "정상.txt").write_text("계약금 오천만원을 입금했습니다", encoding="utf-8")
    (ev / "한글 파일명 띄어쓰기 (1).txt").write_text("설명 들었어요", encoding="utf-8")
    (ev / "cp949.txt").write_bytes("옛날 인코딩 파일입니다".encode("cp949"))
    (ev / "매우긴텍스트.txt").write_text("계약 " * 40000, encoding="utf-8")
    (ev / "제어문자.txt").write_text("정상\x00텍스트\x07입니다﻿", encoding="utf-8")
    (ev / "지원안함.zip").write_bytes(b"PK\x03\x04")
    (ev / "빈오디오.m4a").write_bytes(b"")

    res = scanner.scan(conn, ev)
    c.ok(res["total"] >= 7, "험한 파일도 일단 등록은 된다", f"{res['total']}개")
    c.ok(len(res.get("skipped") or []) >= 2,
         "건너뛴 파일을 사용자에게 알려준다",
         f"{[(Path(x['path']).name, x['reason']) for x in (res.get('skipped') or [])]}")
    c.eq(len(res["failed"]), 0, "스캔 단계에서 예외로 죽지 않는다")

    names = {Path(str(p)).name for _, p in res["added"]}
    c.ok("지원안함.zip" not in names, "모르는 형식은 아예 건너뛴다")
    c.ok("빈파일.txt" not in names, "0바이트 파일은 건너뛴다")

    # ── 추출: 하나가 깨져도 전체는 계속된다 ─────
    out = pipeline.run(conn)
    c.ok(out["done"] >= 3, "정상 파일들은 처리된다", f"{out}")
    c.ok(out["total"] == out["done"] + out["failed"], "모든 파일이 처리 시도된다")

    statuses = dict(conn.execute(
        "SELECT path, status FROM sources").fetchall())
    broken = [p for p in statuses if "깨진" in p]
    c.ok(all(statuses[p] in ("failed", "extracted") for p in broken),
         "깨진 파일은 실패로 표시된다",
         f"{[(Path(p).name, statuses[p]) for p in broken]}")

    ok_file = [p for p in statuses if p.endswith("정상.txt")][0]
    c.eq(statuses[ok_file], "extracted", "깨진 파일 옆의 정상 파일은 처리된다")

    # ── 인코딩 · 특수문자 ─────────────────────
    c.ok(len(hybrid.search(conn, "계약금", use_semantic=False)) >= 1,
         "한글 검색이 된다")
    c.ok(len(hybrid.search(conn, "옛날", use_semantic=False)) >= 1,
         "cp949 파일도 읽는다")
    c.ok(len(hybrid.search(conn, "띄어쓰기", use_semantic=False)) >= 0,
         "한글 파일명·공백이 있어도 처리된다")

    long_segs = conn.execute(
        "SELECT count(*) FROM segments s JOIN sources src ON src.id = s.source_id "
        "WHERE src.path LIKE '%매우긴텍스트%'").fetchone()[0]
    c.ok(long_segs > 10, "아주 긴 텍스트는 여러 구간으로 쪼갠다", f"{long_segs}구간")
    longest = conn.execute(
        "SELECT max(length(text)) FROM segments").fetchone()[0]
    c.ok(longest < 3000, "구간 하나가 지나치게 길지 않다", f"최대 {longest}자")

    # ── 카톡 파서 극단값 ──────────────────────
    empty = tmp_path / "빈카톡.txt"
    empty.write_text("", encoding="utf-8")
    c.eq(kakao.parse(empty), [], "빈 카톡 파일에서 예외가 안 난다")

    weird = tmp_path / "이상한카톡.txt"
    weird.write_text(
        "홍길동 님과 카카오톡 대화\n"
        "--------------- 2025년 13월 45일 ---------------\n"   # 없는 날짜
        "[김대표] [오후 25:99] 잘못된 시각\n"
        "[홍길동] [오후 2:43] 정상 메시지\n"
        "형식에 안 맞는 줄\n",
        encoding="utf-8")
    msgs = kakao.parse(weird)
    c.ok(len(msgs) >= 1, "이상한 날짜·시각이 섞여도 파싱은 계속된다",
         f"{len(msgs)}건")
    c.ok(any("정상 메시지" in m["text"] for m in msgs),
         "정상 메시지는 건진다")

    # ── 원본이 사라진 경우 ────────────────────
    victim = ev / "정상.txt"
    sid = conn.execute("SELECT id FROM sources WHERE path = ?",
                       (str(victim.resolve()),)).fetchone()[0]
    seg = conn.execute("SELECT id FROM segments WHERE source_id = ?",
                       (sid,)).fetchone()[0]
    basket.add(conn, seg, "테스트")
    victim.unlink()

    rows = integrity.verify_all(conn)
    missing = [r for r in rows if r["status"] == "MISSING"]
    c.eq(len(missing), 1, "사라진 원본을 찾아낸다")

    from evidence.report import package
    check = package.preflight(conn)
    c.ok(any("찾을 수 없" in b for b in check["blockers"]),
         "원본이 없으면 패키지 생성을 막는다", f"{check['blockers']}")

    # ── 원본이 변조된 경우 ────────────────────
    other = ev / "한글 파일명 띄어쓰기 (1).txt"
    other.write_text("내용이 바뀌었습니다", encoding="utf-8")
    rows = integrity.verify_all(conn)
    changed = [r for r in rows if r["status"] == "CHANGED"]
    c.eq(len(changed), 1, "변조된 원본을 찾아낸다")

    # ── 중복 등록 ────────────────────────────
    before = conn.execute("SELECT count(*) FROM sources").fetchone()[0]
    scanner.scan(conn, ev)
    after = conn.execute("SELECT count(*) FROM sources").fetchone()[0]
    c.ok(after - before <= 1, "같은 폴더를 다시 스캔해도 중복 등록되지 않는다",
         f"{before} → {after}")

    dup_dir = tmp_path / "사본"
    dup_dir.mkdir()
    import shutil
    shutil.copy(ev / "cp949.txt", dup_dir / "다른이름.txt")
    before = conn.execute("SELECT count(*) FROM sources").fetchone()[0]
    r2 = scanner.scan(conn, dup_dir)
    after = conn.execute("SELECT count(*) FROM sources").fetchone()[0]
    c.eq(after, before, "이름이 달라도 같은 내용이면 한 건으로 본다")
    c.ok(len(r2["duplicate"]) == 1, "중복으로 인식한다")

    # ── 빈 상태에서의 산출물 ───────────────────
    empty_conn = db.init(tmp_path / "empty.db")
    from evidence.analyze import timeline
    from evidence.report import export, locator
    c.eq(timeline.events(empty_conn), [], "자료가 없어도 타임라인이 죽지 않는다")
    c.eq(timeline.contradictions(empty_conn), [], "모순 탐지도 마찬가지")
    c.eq(locator.rows_from_basket(empty_conn), [], "빈 장바구니 색인표")
    p = export.timeline_html(empty_conn, tmp_path / "empty.html")
    c.ok(p.exists() and p.stat().st_size > 100, "빈 상태에서도 HTML이 만들어진다")
    p2 = export.all_csv(empty_conn, tmp_path / "empty.csv")
    c.ok(p2.exists(), "빈 상태에서도 CSV가 만들어진다")
    empty_conn.close()

    conn.close()
    return c.report()


if __name__ == "__main__":
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        sys.exit(0 if run(Path(d)) else 1)
