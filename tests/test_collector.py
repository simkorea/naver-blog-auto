# -*- coding: utf-8 -*-
"""
자료 모으기 검증 — 이름·전화번호로 찾아 복사하기.

여기서 틀리면 무슨 일이 생기나
  · 못 찾으면: 결정적인 녹음이 빠진 채로 분석이 끝난다. 사용자는 모른다.
  · 덮어쓰면: 같은 이름의 다른 녹음이 사라진다. 되돌릴 수 없다.
  · 원본을 건드리면: 증거로서의 값을 잃는다.

그래서 세 가지를 특히 본다: 빠짐없이 찾는가, 덮어쓰지 않는가, 원본이 그대로인가.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from conftest import Check, use_temp_db


def run(tmp_path) -> bool:
    config = use_temp_db(tmp_path)
    from evidence import integrity
    from evidence.ingest import collector

    c = Check("자료 모으기")

    # ── 전화번호 정규화 ───────────────────────────
    for raw in ("010-1234-5678", "010 1234 5678", "01012345678",
                "+82 10-1234-5678".replace("+82 ", "0")):
        c.eq(collector.normalize_phone(raw), "01012345678",
             f"번호를 같은 형태로 본다 ({raw})")

    # ── 검색어 매칭 ──────────────────────────────
    c.ok(collector.match_terms("010-1234-5678_20240320.m4a", ["01012345678"]),
         "하이픈이 있어도 번호로 찾는다")
    c.ok(collector.match_terms("녹음(01012345678).amr", ["010-1234-5678"]),
         "검색어에 하이픈이 있어도 찾는다")
    c.ok(collector.match_terms("통화 녹음 홍길동_240320.m4a", ["홍길동"]),
         "이름으로 찾는다")
    c.ok(collector.match_terms("통화녹음_홍 길 동.m4a", ["홍길동"]),
         "이름에 공백이 끼어 있어도 찾는다")
    c.ok(not collector.match_terms("김철수_통화.m4a", ["홍길동"]),
         "관계없는 파일은 걸리지 않는다")
    c.ok(not collector.match_terms("20240320_1430.m4a", ["01012345678"]),
         "번호가 없으면 걸리지 않는다")
    # 다른 사람의 비슷한 번호가 딸려오면 안 된다
    c.ok(not collector.match_terms("010-9999-0000.m4a", ["01012345678"]),
         "다른 번호는 걸리지 않는다")

    # ── 실제 폴더에서 찾기 ────────────────────────
    src = tmp_path / "흩어진자료"
    (src / "다운로드").mkdir(parents=True)
    (src / "홍길동 통화녹음").mkdir(parents=True)
    (src / "관계없음").mkdir(parents=True)

    files = {
        src / "다운로드" / "010-1234-5678_20240320_143022.m4a": "AAA녹음1".encode(),
        src / "다운로드" / "통화 녹음 홍길동_240321.m4a": "BBB녹음2".encode(),
        src / "다운로드" / "김철수_20240101.m4a": "CCC관계없음".encode(),
        src / "홍길동 통화녹음" / "20240322_0900.m4a": "DDD폴더로걸림".encode(),
        src / "관계없음" / "휴가사진.jpg": b"\xff\xd8\xff\xe0EEE",
        src / "다운로드" / "계약서_홍길동.pdf": b"%PDF-1.4 FFF",
    }
    for p, data in files.items():
        p.write_bytes(data)

    res = collector.find([src], ["홍길동", "010-1234-5678"])
    names = {h["name"] for h in res["hits"]}

    c.ok("010-1234-5678_20240320_143022.m4a" in names, "번호로 녹음을 찾는다")
    c.ok("통화 녹음 홍길동_240321.m4a" in names, "이름으로 녹음을 찾는다")
    c.ok("20240322_0900.m4a" in names, "폴더 이름에 걸린 것도 찾는다")
    c.ok("계약서_홍길동.pdf" in names, "녹음이 아닌 자료도 찾는다")
    c.ok("김철수_20240101.m4a" not in names, "관계없는 사람 파일은 안 가져온다")
    c.ok("휴가사진.jpg" not in names, "관계없는 사진은 안 가져온다")

    by_folder = {h["name"] for h in res["hits"] if h["by_folder"]}
    c.eq(by_folder, {"20240322_0900.m4a"},
         "폴더 이름에만 걸린 것은 따로 표시한다 (딸려 왔을 수 있으므로)")

    only_audio = collector.find([src], ["홍길동"], kinds=[config.KIND_AUDIO])
    c.ok(all(h["kind"] == config.KIND_AUDIO for h in only_audio["hits"]),
         "종류를 지정하면 그것만 찾는다")

    # ── 복사 ────────────────────────────────────
    dest = tmp_path / "증거폴더"
    before = {p: p.read_bytes() for p in files}

    out = collector.collect(res["hits"], dest)
    c.ok(not out["failed"], "복사 중 실패가 없다", f"{out['failed']}")
    c.eq(len(out["copied"]), len(res["hits"]), "찾은 것을 모두 복사한다")

    for p, data in before.items():
        c.ok(p.exists() and p.read_bytes() == data,
             f"원본을 건드리지 않는다 ({p.name})")

    for item in out["copied"]:
        saved = dest / item["saved_as"]
        c.ok(saved.exists(), f"복사본이 생겼다 ({item['saved_as']})")
        c.eq(integrity.sha256_file(saved), integrity.sha256_file(Path(item["path"])),
             f"복사본이 원본과 같다 ({item['saved_as']})")

    # ── 같은 내용을 두 번 담지 않는다 ───────────────
    again = collector.collect(res["hits"], dest)
    c.eq(len(again["copied"]), 0, "같은 파일을 다시 담지 않는다")
    c.eq(len(again["duplicate"]), len(res["hits"]), "중복으로 알려준다")

    # ── 이름은 같은데 내용이 다르면 덮어쓰지 않는다 ──
    other = tmp_path / "다른곳"
    other.mkdir()
    twin = other / "통화 녹음 홍길동_240321.m4a"
    twin.write_bytes("ZZZ완전히다른녹음".encode())

    kept = (dest / "통화 녹음 홍길동_240321.m4a").read_bytes()
    out2 = collector.collect(
        [{"path": str(twin), "size": twin.stat().st_size}], dest)
    c.eq(len(out2["copied"]), 1, "이름이 같아도 내용이 다르면 담는다")
    c.eq((dest / "통화 녹음 홍길동_240321.m4a").read_bytes(), kept,
         "먼저 있던 파일을 덮어쓰지 않는다")
    saved2 = dest / out2["copied"][0]["saved_as"]
    c.ok(saved2.exists() and saved2.read_bytes() == "ZZZ완전히다른녹음".encode(),
         "새 이름으로 나란히 저장한다", out2["copied"][0]["saved_as"])

    # ── 험한 입력 ───────────────────────────────
    c.eq(collector.find([src], [])["hits"], [], "검색어가 없으면 아무것도 안 찾는다")
    c.eq(collector.find([src], ["   "])["hits"], [], "공백만 있어도 마찬가지")
    missing = collector.find([tmp_path / "없는폴더"], ["홍길동"])
    c.ok(missing["errors"], "없는 폴더는 오류로 알려주고 죽지 않는다")

    unreadable = collector.collect(
        [{"path": str(tmp_path / "사라진파일.m4a"), "size": 1}], dest)
    c.eq(len(unreadable["failed"]), 1, "없는 파일은 실패로 알려주고 죽지 않는다")

    return c.report()


if __name__ == "__main__":
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        sys.exit(0 if run(Path(d)) else 1)
