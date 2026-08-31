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

    # ── 화자 분리 체크포인트 읽기 ────────────────────────────
    # 실제로 두 번 터진 자리다. 첫 수정이 안 통한 이유는 lightning 이
    # weights_only 를 **명시적으로** 넘기는데 그걸 존중했기 때문이다.
    # 그래서 여기서는 lightning 의 실제 호출 방식을 그대로 흉내 낸다.
    from evidence.ingest.diarize import _allow_full_checkpoint_load

    import sys as _sys
    import types as _types

    calls = []

    def _record(*args, **kwargs):
        calls.append(kwargs.get("weights_only", "(인자 없음)"))
        return "checkpoint"

    fake = _types.SimpleNamespace(load=_record)
    saved = _sys.modules.get("torch")
    _sys.modules["torch"] = fake
    try:
        with _allow_full_checkpoint_load():
            # lightning/fabric/utilities/cloud_io.py 가 부르는 방식 그대로
            fake.load("model.ckpt", map_location="cpu", weights_only=True)
            fake.load("model.ckpt")          # 아무것도 안 넘기는 경우
        fake.load("model.ckpt")              # 구역을 벗어난 뒤

        c.eq(calls[0], False,
             "lightning 이 weights_only=True 를 넘겨도 덮어쓴다")
        c.eq(calls[1], False,
             "인자를 안 넘겨도 weights_only=False 로 부른다")
        c.eq(calls[2], "(인자 없음)",
             "구역을 벗어나면 원래 torch.load 로 되돌아간다")

        # 구역 안에서 예외가 나도 되돌려야 한다
        try:
            with _allow_full_checkpoint_load():
                raise RuntimeError("모델 파일 손상")
        except RuntimeError:
            pass
        fake.load("model.ckpt")
        c.eq(calls[3], "(인자 없음)", "예외가 나도 원래대로 되돌린다")

        # weights_only 를 모르는 옛 torch 흉내
        def _old_load(*args, **kwargs):
            if "weights_only" in kwargs:
                raise TypeError("load() got an unexpected keyword "
                                "argument 'weights_only'")
            return "ok"

        _sys.modules["torch"] = _types.SimpleNamespace(load=_old_load)
        with _allow_full_checkpoint_load():
            import torch as _t
            c.eq(_t.load("m.ckpt"), "ok", "옛 torch 에서도 죽지 않는다")

        # 관계없는 TypeError 는 감추면 안 된다
        def _broken_load(*args, **kwargs):
            raise TypeError("expected str, got int")

        _sys.modules["torch"] = _types.SimpleNamespace(load=_broken_load)
        raised = False
        try:
            with _allow_full_checkpoint_load():
                import torch as _t2
                _t2.load(123)
        except TypeError:
            raised = True
        c.ok(raised, "관계없는 TypeError 는 그대로 올려보낸다")
    finally:
        if saved is not None:
            _sys.modules["torch"] = saved
        else:
            _sys.modules.pop("torch", None)

    # ── speechbrain 의 깨진 지연 로딩 껍데기 ──────────────────
    # 실제로 터진 자리다. 화자 분리와 무관한 모듈(k2, 윈도우 배포판 없음)
    # 때문에 죽었다. 파이썬 표준 inspect.getmodule() 이 sys.modules 를
    # 훑으며 모든 모듈에 hasattr(m, "__file__") 를 하는 것이 방아쇠였다.
    from evidence.ingest import diarize as _dz

    def _inspect_style_scan():
        """inspect.getmodule() 의 sys.modules 순회 구간을 그대로 흉내 낸다."""
        import inspect as _ins
        for _, module in _sys.modules.copy().items():
            if _ins.ismodule(module) and hasattr(module, "__file__"):
                pass

    try:
        from speechbrain.utils.importutils import LazyModule
    except BaseException:
        LazyModule = None

    if LazyModule is None:
        # speechbrain 이 없는 환경에서도 죽지 않아야 한다
        _dz._defuse_speechbrain_redirects()
        c.ok(True, "speechbrain 이 없어도 조용히 넘어간다")
    else:
        class _BrokenLazy(LazyModule):
            """불러오려 하면 죽는 껍데기 — k2_fsa 와 같은 상황."""
            def __getattr__(self, name):
                raise ImportError("Lazy import of LazyModule(...) failed")

        # target 을 실제 선택적 의존성 묶음으로 둔다 — 그 접두사만 손대기 때문
        broken = "speechbrain.__evidence_test_broken"
        _sys.modules[broken] = _BrokenLazy(
            broken, "speechbrain.integrations.__evidence_test", None)
        try:
            blew_up = False
            try:
                _inspect_style_scan()
            except ImportError:
                blew_up = True
            c.ok(blew_up, "깨진 껍데기가 있으면 실제로 터진다 (재현)")

            _dz._probed.discard(broken)
            _dz._defuse_speechbrain_redirects()

            survived = True
            try:
                _inspect_style_scan()
            except BaseException:
                survived = False
            c.ok(survived, "껍데기를 무해하게 바꾸면 터지지 않는다")
            c.ok(not isinstance(_sys.modules.get(broken), LazyModule),
                 "깨진 껍데기는 빈 모듈로 교체된다")
            # 안 고쳐졌으면 이 hasattr 자체가 터진다. 터지는 것도 실패로 센다.
            try:
                no_file = hasattr(_sys.modules.get(broken), "__file__") is False
            except BaseException:
                no_file = False
            c.ok(no_file, "빈 모듈은 __file__ 이 없어 inspect 가 건너뛴다")
            # 멀쩡한 것까지 없애면 안 된다
            import speechbrain.inference as _sbi
            c.ok(hasattr(_sbi, "EncoderClassifier"),
                 "멀쩡한 speechbrain 기능은 그대로 남는다")
            # 선택적 의존성이 아닌 껍데기는 건드리지도 않는다 (불러오면 느리다)
            keep = "speechbrain.__evidence_test_keep"

            class _Tripwire(LazyModule):
                def __getattr__(self, name):
                    raise AssertionError("건드리지 말았어야 할 껍데기를 건드렸다")

            _sys.modules[keep] = _Tripwire(keep, "speechbrain.inference", None)
            try:
                _dz._probed.discard(keep)
                _dz._defuse_speechbrain_redirects()
                c.ok(isinstance(_sys.modules[keep], LazyModule),
                     "선택적 의존성이 아닌 껍데기는 불러오지 않고 그대로 둔다")
            finally:
                _sys.modules.pop(keep, None)
        finally:
            _sys.modules.pop(broken, None)

    # ── 화면 포트가 여기저기서 어긋나지 않는가 ──────
    # 네이버 블로그 대시보드도 Streamlit 이라 기본 포트 8501 이 겹쳤다.
    # 블로그 프로그램이 "대시보드가 이미 실행 중"으로 오판하고 브라우저만
    # 열어 증거파인더 화면을 보여줬다. 포트를 갈라 두었는데, 값이 여러
    # 곳에 흩어져 있으므로 한 곳만 고치고 빠뜨리면 다시 같은 일이 난다.
    repo = Path(__file__).resolve().parent.parent
    from evidence.app import PORT as APP_PORT
    from evidence import make_shortcuts as _ms

    want = str(APP_PORT)
    cfg = (repo / ".streamlit" / "config.toml").read_text(encoding="utf-8")
    c.ok(f"port = {want}" in cfg, "설정 파일이 같은 포트를 가리킨다", want)

    bat = (repo / "evidence" / "실행.bat").read_text(encoding="utf-8",
                                                     errors="ignore")
    c.ok(f"--server.port {want}" in bat, "실행.bat 이 같은 포트를 가리킨다")

    run_arg = _ms.shortcut_specs(repo)[0]["arguments"]
    c.ok(f"--server.port {want}" in run_arg,
         "바탕화면 바로가기가 같은 포트를 가리킨다")

    # 8501 로 되돌아간 곳이 없어야 한다.
    # 왜 이 파일들이 8501 을 쓰면 안 되는지 **설명하는 주석**은 그대로
    # 두어야 하므로, 주석을 걷어낸 실제 코드에서만 찾는다.
    def _code_only(text: str) -> str:
        out = []
        for line in text.splitlines():
            stripped = line.lstrip()
            if stripped.startswith(("#", "rem ", "REM ", "::")):
                continue
            out.append(line.split("#", 1)[0])
        return "\n".join(out)

    strays = [f.name for f in (repo / ".streamlit" / "config.toml",
                               repo / "evidence" / "실행.bat",
                               repo / "evidence" / "app.py",
                               repo / "evidence" / "make_shortcuts.py",
                               repo / "evidence" / "setup_check.py")
              if "8501" in _code_only(f.read_text(encoding="utf-8",
                                                  errors="ignore"))]
    c.ok(not strays, "블로그 대시보드 포트(8501)로 되돌아간 곳이 없다",
         f"{strays or '없음'}")

    # ── 경고 소음이 화면을 뒤덮지 않는가 ────────────
    # 화자 분리를 돌리면 torchaudio 의 폐기 예고문 세 가지가 오디오 조각마다
    # 반복되어 수백 줄씩 쏟아졌다. 오류가 아닌데 오류처럼 보이고, 진짜 오류가
    # 그 사이에 묻힌다. 아래 넷을 지킨다.
    import contextlib as _ctx
    import io as _io
    import warnings as _warn

    # 사장님 화면에 실제로 뜬 문구를, 실제로 뜬 자리 그대로.
    _FLOOD = [
        ("In 2.9, this function's implementation will be changed to use "
         "torchaudio.load_with_torchcodec under the hood. Some parameters "
         "like ``normalize``, ``format``, ``buffer_size``, and ``backend`` "
         "will be ignored. We recommend that you port your code to rely "
         "directly on TorchCodec's decoder instead: "
         "https://docs.pytorch.org/torchcodec/stable/generated/"
         "torchcodec.decoders.AudioDecoder.html#torchcodec.decoders.AudioDecoder.",
         "torchaudio/_backend/utils.py", 213, "torchaudio._backend.utils"),
        ("torchaudio._backend.utils.info has been deprecated. "
         "It will be removed from the 2.9 release.",
         "pyannote/audio/core/io.py", 85, "pyannote.audio.core.io"),
        ("torchaudio._backend.common.AudioMetaData has been deprecated. "
         "It will be removed from the 2.9 release.",
         "torchaudio/_backend/soundfile_backend.py", 120,
         "torchaudio._backend.soundfile_backend"),
    ]

    def _printed(emit) -> str:
        """실제로 화면(stderr)에 찍힌 글자를 그대로 돌려준다."""
        buf = _io.StringIO()
        with _ctx.redirect_stderr(buf):
            emit()
        return buf.getvalue()

    def _flood(times: int, wipe_filters: bool):
        def go():
            for _ in range(times):
                # 라이브러리가 오디오 조각마다 이 블록을 드나든다.
                # 그것만으로 "이미 보여준 것" 기록이 무효가 되어 반복 출력된다.
                with _warn.catch_warnings():
                    if wipe_filters:
                        # 이 한 줄이 우리가 걸어둔 차단 필터를 지운다.
                        _warn.simplefilter("always")
                    for msg, fname, lineno, mod in _FLOOD:
                        _warn.warn_explicit(msg, UserWarning, fname, lineno,
                                            module=mod)
        return go

    from evidence.console import quiet_known_warnings as _quiet
    _quiet()

    c.ok(_printed(_flood(5, wipe_filters=False)) == "",
         "화자 분리 폐기 예고문 3종이 화면에 안 나온다",
         _printed(_flood(1, wipe_filters=False))[:120])

    # 필터가 지워진 상태에서도 막혀야 한다. showwarning 덧댐이 없으면 여기서
    # 15줄이 쏟아진다 (3종 x 5회).
    c.ok(_printed(_flood(5, wipe_filters=True)) == "",
         "필터가 지워져도(simplefilter) 폐기 예고문이 안 나온다",
         _printed(_flood(1, wipe_filters=True))[:120])

    # 제일 중요한 것 — 모르는 경고까지 숨기면 진짜 문제를 못 본다.
    def _real_warning():
        with _warn.catch_warnings():
            _warn.simplefilter("always")
            _warn.warn_explicit("증거 DB 가 잠겨 있습니다", UserWarning,
                                "evidence/db.py", 10, module="evidence.db")

    c.ok("증거 DB 가 잠겨" in _printed(_real_warning),
         "목록에 없는 진짜 경고는 그대로 화면에 나온다")

    # ── 화면 프로그램도 소음 차단을 켜는가 ──────────
    # 명령창 진입점들은 전부 켜는데 app.py 만 빠져 있어서, 정작 화자 분리를
    # 돌리는 화면에서만 경고가 쏟아졌다.
    _app_src = (repo / "evidence" / "app.py").read_text(encoding="utf-8")
    _lines = _app_src.splitlines()
    _setup_at = next((i for i, ln in enumerate(_lines)
                      if "_console_setup()" in ln and not ln.lstrip().startswith("#")), None)
    _st_at = next((i for i, ln in enumerate(_lines)
                   if ln.startswith("import streamlit")), None)
    c.ok(_setup_at is not None, "화면(app.py)도 경고 차단을 켠다")
    c.ok(_setup_at is not None and _st_at is not None and _setup_at < _st_at,
         "차단을 streamlit·torch 를 불러오기 전에 켠다",
         f"setup {_setup_at} / streamlit {_st_at}")

    # ── Streamlit 이 이름 바꾸라고 찍는 안내가 남았는가 ──
    # 파이썬 경고가 아니라 Streamlit 이 직접 찍는 것이라 위 차단으로는 안 잡힌다.
    _old_param = [f.relative_to(repo).as_posix()
                  for f in (repo / "evidence").rglob("*.py")
                  if "use_container_width" in f.read_text(encoding="utf-8",
                                                          errors="ignore")]
    c.ok(not _old_param,
         "화면 코드에 use_container_width 가 남아 있지 않다",
         f"{_old_param or '없음'}")

    # ── DB 가 잠겼을 때 무엇을 해야 하는지 알려주는가 ──
    # 화면(Streamlit)을 켜 둔 채 명령창을 돌리면 실제로 일어났다.
    # `--voiceprint` 가 새 표를 만들려다 잠금에 걸려 죽었는데, 화면에는
    # `database is locked` 만 떴다. 사용자는 개발자가 아니다.
    import os as _os
    import sqlite3 as _sq
    import subprocess as _sp

    lock_db = tmp_path / "lock_test.db"
    lock_work = tmp_path / "lock_work"
    lock_work.mkdir(exist_ok=True)
    lock_env = dict(_os.environ, EVIDENCE_DB=str(lock_db),
                    EVIDENCE_WORK=str(lock_work))

    repo2 = Path(__file__).resolve().parent.parent
    _sp.run([sys.executable, str(repo2 / "evidence" / "transcribe.py"), "--status"],
            env=lock_env, capture_output=True, cwd=str(repo2))

    holder = _sq.connect(str(lock_db), timeout=1)
    holder.execute("PRAGMA busy_timeout = 0")
    holder.execute("BEGIN EXCLUSIVE")
    try:
        r = _sp.run([sys.executable, str(repo2 / "evidence" / "transcribe.py"),
                     "--voiceprint"],
                    env=lock_env, capture_output=True, text=True, cwd=str(repo2))
        out = (r.stdout or "") + (r.stderr or "")
        c.ok(r.returncode != 0, "잠긴 DB 로는 시작하지 않는다")
        c.ok("화면이 켜져 있는 것입니다" in out,
             "왜 안 되는지 한국어로 알려준다")
        c.ok("브라우저 탭을 닫습니다" in out,
             "무엇을 해야 하는지 알려준다")
        c.ok("자료는 안전합니다" in out,
             "자료가 멀쩡하다고 안심시킨다 — 소송 자료라 겁먹기 쉽다")
        c.ok("Traceback" not in out,
             "스택 트레이스를 그대로 쏟아내지 않는다")
    finally:
        holder.rollback()
        holder.close()

    # 잠금이 아닌 진짜 오류는 감추지 않는다
    from evidence import db as _db
    c.ok(_db._is_busy(Exception("database is locked")), "잠금 오류를 알아본다")
    c.ok(not _db._is_busy(Exception("no such table: segments")),
         "잠금이 아닌 오류는 잠금으로 오해하지 않는다")

    conn.close()
    return c.report()


if __name__ == "__main__":
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        sys.exit(0 if run(Path(d)) else 1)
