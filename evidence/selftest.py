# -*- coding: utf-8 -*-
"""
자체 점검 — 가짜 사건으로 전 과정을 한 번 통과시켜 본다.

    python evidence/setup_check.py --selftest

왜 필요한가
  실제 소송 자료를 넣고 몇 시간 돌린 뒤에 터지면 그 시간이 통째로 날아간다.
  Whisper 모델 내려받기, GPU 메모리, pyannote 약관 동의, ffmpeg, 윈도우 경로 —
  이런 것들은 실제로 돌려봐야만 드러난다.

  그래서 3분짜리 가짜 사건으로 먼저 전 과정을 밟는다. 여기서 통과하면
  실제 자료를 믿고 넣을 수 있고, 막히면 아직 아무것도 잃지 않은 상태에서 고친다.

무엇을 건드리지 않는가
  실제 DB(evidence.db)와 실제 증거는 손대지 않는다. 전부 임시 폴더에서
  하고 끝나면 지운다.
"""
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

KAKAO_SAMPLE = """\
홍길동 님과 카카오톡 대화
저장한 날짜 : 2025-03-20 10:00:00

--------------- 2025년 3월 14일 금요일 ---------------
[김대표] [오후 2:40] 분양가와 계약 조건을 전부 설명드렸습니다
[홍길동] [오후 2:43] 네 그건 설명 들었어요
계약금 오천만원도 확인했습니다
--------------- 2025년 3월 20일 목요일 ---------------
[홍길동] [오전 9:22] 생각해보니 그때 설명 못 들은 것 같아서요
"""

DOC_SAMPLE = """\
부동산 매매 계약서

제5조 (설명의무)
매도인은 계약 체결 전 매수인에게 중개대상물의 권리관계와
분양가를 성실하게 설명하여야 한다.

분양가: 금 오억 이천만원정
계약금: 금 오천만원정
"""


# 단계의 중요도. 건너뛰었을 때 뭐라고 말해야 하는지가 달라진다.
#   필수  - 이게 안 되면 프로그램을 쓸 수 없다
#   핵심  - 이 사건에서 실제로 필요한 기능. 건너뛰면 "통과"라고 하면 안 된다
#   선택  - 없어도 나머지로 일할 수 있다
REQUIRED, CORE, OPTIONAL = "필수", "핵심", "선택"


class Step:
    """점검 한 단계. 걸린 시간과 결과를 담는다."""

    def __init__(self, name, kind=REQUIRED, note=""):
        self.name = name
        self.kind = kind
        self.note = note
        self.ok = None          # None = 건너뜀
        self.detail = ""
        self.seconds = 0.0


class SelfTest:
    def __init__(self, marks: dict):
        self.M = marks
        self.steps: list[Step] = []
        self.tmp: Path | None = None

    # ── 화면 출력 ─────────────────────────────
    def _say(self, text=""):
        print(text)

    def _run(self, name, fn, kind=REQUIRED, note="") -> Step:
        step = Step(name, kind, note)
        self.steps.append(step)
        print(f"  {name} ... ", end="", flush=True)
        started = time.time()
        # 라이브러리가 중간에 안내문을 뱉으면 줄이 엉킨다. 모았다가 나중에 보여준다.
        import contextlib
        import io

        captured = io.StringIO()
        try:
            with contextlib.redirect_stdout(captured):
                result = fn()
            step.seconds = time.time() - started
            if result is None:
                step.ok = None
                step.detail = "건너뜀"
                print(f"건너뜀")
            else:
                step.ok = True
                step.detail = str(result)
                print(f"{self.M['ok']} {result}  ({step.seconds:.1f}초)")
        except SkipStep as e:
            step.seconds = time.time() - started
            step.ok = None
            step.detail = str(e).replace("\n", " ")[:160]
            print(f"건너뜀 - {step.detail}")
        except BaseException as e:
            step.seconds = time.time() - started
            step.ok = False
            step.detail = f"{type(e).__name__}: {str(e)[:200]}"
            print(f"{self.M['no']} 실패")
            print(f"      {step.detail}")

        noise = captured.getvalue().strip()
        if noise and step.ok is False:
            for line in noise.splitlines()[-4:]:
                print(f"      {line.strip()}")
        return step

    # ── 가짜 사건 만들기 ───────────────────────
    def _make_evidence(self) -> str:
        from . import config

        ev = self.tmp / "가짜증거"
        ev.mkdir(parents=True, exist_ok=True)

        (ev / "KakaoTalk_Chats.txt").write_text(KAKAO_SAMPLE, encoding="utf-8")
        (ev / "계약서.txt").write_text(DOC_SAMPLE, encoding="utf-8")

        made = ["카톡", "문서"]

        exe = config.ffmpeg_path()
        if exe:
            audio = ev / "20250314_143022_상담통화.m4a"
            # 두 사람이 번갈아 말하는 것처럼 음높이를 달리한다.
            # 화자 분리가 실제로 두 명을 잡아내는지 보기 위함이다.
            filt = (
                "sine=frequency=180:duration=5,volume=0.8[a];"
                "sine=frequency=420:duration=5,volume=0.8[b];"
                "sine=frequency=180:duration=5,volume=0.8[c];"
                "sine=frequency=420:duration=5,volume=0.8[d]"
            )
            r = subprocess.run(
                [exe, "-y",
                 "-f", "lavfi", "-i", "sine=frequency=180:duration=5",
                 "-f", "lavfi", "-i", "sine=frequency=420:duration=5",
                 "-f", "lavfi", "-i", "sine=frequency=180:duration=5",
                 "-f", "lavfi", "-i", "sine=frequency=420:duration=5",
                 "-filter_complex", "[0][1][2][3]concat=n=4:v=0:a=1",
                 "-c:a", "aac", "-b:a", "96k", str(audio)],
                capture_output=True, timeout=180)
            if r.returncode == 0 and audio.exists():
                made.append("녹음 20초")

        self.ev = ev
        return " · ".join(made)

    # ── 각 단계 ──────────────────────────────
    def _scan(self):
        from . import db, integrity
        from .ingest import scanner

        self.conn = db.init()
        result = scanner.scan(self.conn, self.ev, defaults={"counterparty": "홍길동"})
        if not result["added"]:
            raise RuntimeError("파일이 하나도 등록되지 않았습니다")

        # 녹음은 본인 대화로 표시 (점검용)
        db.write(self.conn,
                 "UPDATE sources SET is_my_conversation = 'Y' WHERE kind = 'audio'")

        rows = integrity.verify_all(self.conn)
        bad = [r for r in rows if r["status"] != "ok"]
        if bad:
            raise RuntimeError(f"해시 대조 실패 {len(bad)}건")
        return f"{len(result['added'])}개 등록 · 해시 봉인 확인"

    def _extract_text(self):
        from .ingest import pipeline

        res = pipeline.run(self.conn, kinds=pipeline.TEXT_KINDS)
        if res["segments"] == 0:
            raise RuntimeError("텍스트를 하나도 뽑지 못했습니다")
        return f"{res['segments']}개 구간"

    def _transcribe(self):
        from . import config, db
        from .ingest import audio, pipeline

        row = self.conn.execute(
            "SELECT * FROM sources WHERE kind = 'audio' LIMIT 1").fetchone()
        if not row:
            raise SkipStep("녹음 파일이 없습니다 (ffmpeg 미설치)")

        try:
            audio.get_model(config.WHISPER_PRIMARY)
        except BaseException as e:
            raise SkipStep(f"모델을 못 불러왔습니다 - {str(e).splitlines()[0][:120]}")

        n, msg = pipeline.extract_one(
            self.conn, row, cross_verify=False, diarize=False)
        self.audio_row = row
        return f"{n}개 구간 ({config.WHISPER_PRIMARY})"

    def _diarize(self):
        from . import config
        from .ingest import diarize

        ok, why = diarize.available()
        if not ok:
            raise SkipStep(why)
        row = getattr(self, "audio_row", None)
        if row is None:
            raise SkipStep("전사된 녹음이 없습니다")

        turns = diarize.diarize(row["path"], min_speakers=1, max_speakers=4)
        n = len({t["speaker"] for t in turns})
        return f"화자 {n}명 · 구간 {len(turns)}개"

    def _search(self):
        from .analyze import keywords
        from .search import hybrid

        keywords.scan(self.conn)
        hits = hybrid.search(self.conn, "설명", use_semantic=False)
        if not hits:
            raise RuntimeError("검색 결과가 없습니다")

        from .analyze import timeline
        contras = timeline.contradictions(self.conn)
        extra = f" · 진술 모순 {len(contras)}건 탐지" if contras else ""
        return f"'설명' {len(hits)}건{extra}"

    def _semantic(self):
        from . import db
        from .search import embed

        if not embed.embedder_ready():
            raise SkipStep("의미 검색 모델이 없습니다")
        n = embed.build_index(self.conn)
        from .search import hybrid
        hits = hybrid.semantic_search(self.conn, "고객이 설명을 인정하는 말", limit=5)
        return f"색인 {n}건 · 문장 검색 {len(hits)}건"

    def _package(self):
        from . import basket
        from .report import package

        rows = self.conn.execute(
            "SELECT id FROM segments WHERE text LIKE '%설명%' LIMIT 3").fetchall()
        if not rows:
            raise RuntimeError("발췌할 구간이 없습니다")
        for r in rows:
            basket.add(self.conn, r["id"], "자체 점검")

        out = package.build(self.conn, self.tmp / "제출",
                            target="점검", case_name="자체 점검")
        files = sorted(f.name for f in out["root"].iterdir())
        clips = len([c for c in out["clips"] if c.get("ok")])
        return f"문서 {len([f for f in files if '.' in f])}개 · 발췌본 {clips}개"

    def _backup(self):
        from . import backup

        bp = backup.create(self.tmp / "백업", note="자체 점검")
        info = backup.inspect(bp)
        return f"{info['size_mb']}MB · 구간 {info['stats'].get('segments', 0)}개"

    # ── 실행 ─────────────────────────────────
    def run(self) -> bool:
        from . import config

        M = self.M
        print()
        print(M["dline"] * 68)
        print("  자체 점검 - 가짜 사건으로 전 과정을 돌려봅니다")
        print(M["dline"] * 68)
        print()
        print("  실제 증거와 분석 결과는 건드리지 않습니다.")
        print("  임시 폴더에서 하고 끝나면 지웁니다.")
        print()

        hw = config.hardware()
        print(f"  실행 환경 : {hw['device']}"
              + (f" ({hw['gpu_name']})" if hw.get("gpu_name") else ""))
        print(f"  전사 모델 : {config.WHISPER_PRIMARY}")
        print()
        print(M["line"] * 68)

        started = time.time()
        with tempfile.TemporaryDirectory(prefix="evidence_selftest_") as d:
            self.tmp = Path(d)
            # 점검용 DB·작업폴더를 임시로 돌려놓는다
            import os
            saved = (os.environ.get("EVIDENCE_DB"), os.environ.get("EVIDENCE_WORK"))
            os.environ["EVIDENCE_DB"] = str(self.tmp / "점검.db")
            os.environ["EVIDENCE_WORK"] = str(self.tmp / "작업")
            _reload_config()

            try:
                self._run("가짜 사건 만들기", self._make_evidence, REQUIRED)
                self._run("자료 등록·해시 봉인", self._scan, REQUIRED)
                self._run("텍스트 추출", self._extract_text, REQUIRED)
                self._run("녹음 전사", self._transcribe, CORE)
                self._run("화자 분리", self._diarize, OPTIONAL)
                self._run("검색·쟁점 분류", self._search, REQUIRED)
                self._run("의미 검색", self._semantic, OPTIONAL)
                self._run("발췌본·제출 패키지", self._package, REQUIRED)
                self._run("백업", self._backup, REQUIRED)
            finally:
                try:
                    self.conn.close()
                except BaseException:
                    pass
                for key, value in zip(("EVIDENCE_DB", "EVIDENCE_WORK"), saved):
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value
                _reload_config()

        return self._report(time.time() - started)

    def _report(self, elapsed: float) -> bool:
        M = self.M
        failed = [s for s in self.steps if s.ok is False]
        skipped = [s for s in self.steps if s.ok is None]
        passed = [s for s in self.steps if s.ok is True]

        print(M["line"] * 68)
        print(f"  통과 {len(passed)} · 건너뜀 {len(skipped)} · 실패 {len(failed)}"
              f"　({elapsed:.1f}초)")

        # 전사 속도를 실제 녹음 길이로 환산해 알려준다
        transcribe = next((s for s in self.steps if s.name == "녹음 전사"), None)
        if transcribe and transcribe.ok and transcribe.seconds > 0:
            ratio = 20.0 / transcribe.seconds       # 20초짜리를 몇 배속으로 처리했나
            hour = 3600 / ratio / 60 if ratio > 0 else 0
            print()
            print(f"  전사 속도 : 20초 녹음을 {transcribe.seconds:.1f}초에 처리")
            print(f"              1시간 녹음이면 대략 {hour:.0f}분 걸립니다")
            if hour > 30:
                print(f"              {M['no']} 느립니다. GPU 가속이 켜져 있는지 확인하세요:")
                print("                  python evidence/setup_check.py --repair")

        if skipped:
            print()
            print("  건너뛴 것")
            for s in skipped:
                tag = f"[{s.kind}] " if s.kind != OPTIONAL else ""
                print(f"    - {tag}{s.name}: {s.detail}")

        core_skipped = [s for s in skipped if s.kind == CORE]

        if failed:
            print()
            print(f"  {M['no']} 실패한 것 - 실제 자료를 넣기 전에 고쳐야 합니다")
            for s in failed:
                print(f"    - {s.name}")
                print(f"        {s.detail}")
            print()
            print("  화면에 뜬 내용을 그대로 알려주시면 원인을 짚어드릴 수 있습니다.")
        elif core_skipped:
            # 여기서 "통과했습니다" 라고 하면 안 된다.
            # 핵심 기능이 확인되지 않았는데 다 됐다고 믿고 실제 자료를 넣으면,
            # 몇 시간 뒤에 같은 자리에서 막힌다.
            print()
            print(f"  {M['no']} 핵심 기능이 확인되지 않았습니다: "
                  f"{', '.join(s.name for s in core_skipped)}")
            print()
            for s in core_skipped:
                print(f"    {s.name} - {s.detail}")
            print()
            print("  나머지(카톡·문서 검색, 발췌, 제출 패키지)는 지금도 쓸 수 있지만,")
            print("  녹음을 다루려면 먼저 모델을 받아야 합니다:")
            print()
            print("      python evidence/setup_check.py --models")
            print()
            print("  받은 뒤 이 점검을 다시 돌려주세요.")
        else:
            print()
            print(f"  {M['ok']} 전 과정이 통과했습니다. 실제 자료를 넣으셔도 됩니다.")
            print()
            print("  다음 단계")
            print("      python -m streamlit run evidence/app.py --server.port 8532")
            print()
            print("  처음에는 녹음 1~2개만 넣어 전사 품질을 확인하세요.")
            print("  [분석 실행] 탭의 '사건 고유명사 사전'에 사람 이름·상호를 넣으면")
            print("  인식률이 눈에 띄게 좋아집니다.")

        print(M["dline"] * 68)
        print()
        return not failed and not core_skipped


class SkipStep(Exception):
    """이 단계는 조건이 안 되어 건너뛴다 (실패가 아니다)."""


def _reload_config():
    """환경 변수를 바꾼 뒤 설정 모듈을 다시 읽는다."""
    import importlib
    import sys

    for name in [m for m in list(sys.modules) if m.startswith("evidence")]:
        if name in ("evidence.console", "evidence.selftest", "evidence.setup_check"):
            continue
        sys.modules.pop(name, None)


def run(marks: dict) -> bool:
    return SelfTest(marks).run()
