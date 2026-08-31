# -*- coding: utf-8 -*-
"""
음성 파이프라인 검증 — 모델 없이 우리 코드만 시험한다.

여기서 확인하는 것
  · Whisper가 내놓은 구간을 우리가 제대로 받아 적는가
  · 신뢰도 계산이 의도대로 되는가
  · 환청 문구를 잡아내는가
  · 사건 고유명사가 실제로 hotwords로 전달되는가
  · 구버전 faster-whisper(hotwords 미지원)에서도 죽지 않는가
  · 이중 모델 교차 검증이 부정어 뒤집힘·금액 차이를 잡는가
  · 화자 분리 결과가 구간에 제대로 붙는가
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from conftest import (Check, FakeSegment, FakeWhisper, fake_turns,
                      install_fake_whisper, use_temp_db)


def run(tmp_path) -> bool:
    config = use_temp_db(tmp_path)
    from evidence import db
    from evidence.ingest import audio, diarize, verify

    c = Check("음성 파이프라인")
    conn = db.init()

    # ── 전사 결과 처리 ────────────────────────
    segs = [
        FakeSegment(0.0, 3.2, " 안녕하세요 상담 문의드립니다 "),
        FakeSegment(3.2, 8.5, "제가 분양가와 조건을 전부 설명드렸습니다"),
        FakeSegment(8.5, 9.0, ""),                       # 빈 구간 → 버려야 함
        FakeSegment(9.0, 12.0, "네 그건 설명 들었어요"),
        # 무음 환청: no_speech_prob 높고 정형 문구
        FakeSegment(50.0, 53.0, "시청해주셔서 감사합니다",
                    avg_logprob=-1.1, no_speech_prob=0.88, compression_ratio=1.1),
        # 반복 버그: 같은 말 반복 + 압축률 높음
        FakeSegment(53.0, 58.0, "네 네 네 네 네 네 네 네",
                    avg_logprob=-0.9, compression_ratio=3.1),
    ]
    fake = install_fake_whisper(audio, config.WHISPER_PRIMARY,
                               FakeWhisper(segs, duration=60.0))

    src = tmp_path / "통화.m4a"
    src.write_bytes(b"fake audio")

    rows = audio.transcribe(src, preprocess_level="none")

    c.eq(len(rows), 5, "빈 구간은 버린다")
    c.eq(rows[0]["text"], "안녕하세요 상담 문의드립니다", "앞뒤 공백을 정리한다")
    c.ok(all(r["seq"] == i + 1 for i, r in enumerate(rows)), "번호가 1부터 이어진다")

    # 단어 타임스탬프
    words = json.loads(rows[0]["words_json"])
    c.ok(len(words) == 3 and words[0]["s"] == 0.0, "단어 타임스탬프를 저장한다",
         f"{words[:2]}")

    # 신뢰도
    good = rows[1]
    hall = next(r for r in rows if "시청해주셔서" in r["text"])
    loop = next(r for r in rows if r["text"].startswith("네 네"))
    c.ok(good["confidence"] > 0.7, "정상 구간은 신뢰도가 높다",
         f"{good['confidence']}")
    c.ok(hall["confidence"] < 0.3, "무음 환청 구간은 신뢰도가 낮다",
         f"{hall['confidence']}")
    c.eq(hall["hallucination_risk"], 1, "정형 환청 문구를 잡아낸다")
    c.eq(loop["hallucination_risk"], 1, "같은 말 반복을 잡아낸다")

    # ── 사건 고유명사 전달 ─────────────────────
    import yaml
    config.CASE_TERMS_YAML.write_text(
        yaml.safe_dump({"고유명사": ["래미안원베일리", "홍길동", "확인설명서"]},
                       allow_unicode=True), encoding="utf-8")
    fake.calls.clear()
    audio.transcribe(src, preprocess_level="none")
    opts = fake.calls[-1]["opts"]
    c.ok("래미안원베일리" in (opts.get("hotwords") or ""),
         "사건 고유명사가 hotwords로 전달된다")
    c.eq(opts.get("condition_on_previous_text"), False,
         "무한 반복 차단 설정이 켜져 있다")
    c.eq(opts.get("vad_filter"), True, "무음 필터가 켜져 있다")
    c.eq(opts.get("word_timestamps"), True, "단어 타임스탬프가 켜져 있다")
    c.eq(opts.get("language"), "ko", "한국어로 고정되어 있다")

    # ── 구버전 호환 ──────────────────────────
    old = install_fake_whisper(audio, config.WHISPER_PRIMARY,
                               FakeWhisper(segs, reject_hotwords=True))
    rows2 = audio.transcribe(src, preprocess_level="none")
    c.ok(len(rows2) == 5, "hotwords를 모르는 구버전에서도 전사된다")
    c.ok("hotwords" not in old.calls[-1]["opts"],
         "구버전에서는 hotwords를 빼고 재시도한다")
    config.CASE_TERMS_YAML.unlink()

    # ── 교차 검증 ────────────────────────────
    install_fake_whisper(audio, config.WHISPER_PRIMARY, FakeWhisper(segs))
    second = [
        FakeSegment(0.0, 3.2, "안녕하세요 상담 문의드립니다"),        # 같음
        FakeSegment(3.2, 8.5, "제가 분양가와 조건을 전부 설명드렸습니다"),  # 같음
        FakeSegment(9.0, 12.0, "네 그건 설명 못 들었어요"),            # 부정어 뒤집힘
        # 50초대 환청 구간에 대응하는 것이 없다 → 2차가 못 들음
    ]
    install_fake_whisper(audio, config.WHISPER_SECONDARY, FakeWhisper(second))
    checked = verify.cross_check(src, rows, preprocess_level="none")

    flip = next(r for r in checked if "설명 들었" in r["text"])
    c.eq(flip["alt_mismatch"], 1, "부정어 뒤집힘을 불일치로 잡는다")
    c.eq(flip["mismatch_kind"], "부정어 뒤집힘", "불일치 종류를 기록한다")
    c.ok(flip["confidence"] <= 0.1, "부정어 뒤집힘은 신뢰도를 최하로 내린다",
         f"{flip['confidence']}")
    c.eq(flip["alt_text"], "네 그건 설명 못 들었어요", "2차 모델 결과를 보관한다")

    same = next(r for r in checked if "안녕하세요" in r["text"])
    c.eq(same["alt_mismatch"], 0, "두 모델이 같으면 통과시킨다")

    orphan = next(r for r in checked if "시청해주셔서" in r["text"])
    c.eq(orphan["alt_mismatch"], 1, "2차가 못 들은 구간은 환청으로 본다")
    c.eq(orphan["hallucination_risk"], 1, "2차 미검출 구간에 환청 표시를 단다")

    # ── 화자 분리 매칭 ────────────────────────
    turns = fake_turns([
        (0.0, 3.3, "SPEAKER_00"),
        (3.2, 8.6, "SPEAKER_01"),
        (8.9, 12.1, "SPEAKER_00"),
        (50.0, 52.0, "SPEAKER_00"), (51.0, 53.0, "SPEAKER_01"),  # 말 겹침
    ])
    assigned = diarize.assign(rows, turns)
    c.eq(assigned[0]["speaker"], "SPEAKER_00", "첫 구간 화자를 맞춘다")
    c.eq(assigned[1]["speaker"], "SPEAKER_01", "둘째 구간 화자를 맞춘다")
    overlap = next(a for a in assigned if "시청해주셔서" in a["text"])
    c.eq(overlap.get("speaker_uncertain"), 1, "말이 겹치면 불확실 표시를 단다")

    # ── DB 저장까지 ───────────────────────────
    from evidence import integrity
    fp = integrity.fingerprint(src)
    sid, _ = db.add_source(conn, fp, "audio", is_my_conversation="Y")
    install_fake_whisper(audio, config.WHISPER_PRIMARY, FakeWhisper(segs))
    install_fake_whisper(audio, config.WHISPER_SECONDARY, FakeWhisper(second))
    row = conn.execute("SELECT * FROM sources WHERE id = ?", (sid,)).fetchone()
    n = audio.extract(conn, row, cross_verify=True, diarize=False,
                      preprocess_level="none")
    c.eq(n, 5, "DB에 구간이 저장된다")

    saved = conn.execute(
        "SELECT text, confidence, alt_mismatch, mismatch_kind, words_json "
        "FROM segments WHERE source_id = ? ORDER BY seq", (sid,)).fetchall()
    c.ok(all(s["words_json"] for s in saved if s["text"]),
         "단어 타임스탬프가 DB까지 간다")
    c.ok(any(s["mismatch_kind"] == "부정어 뒤집힘" for s in saved),
         "불일치 종류가 DB까지 간다")

    detail = conn.execute("SELECT status_detail FROM sources WHERE id = ?",
                          (sid,)).fetchone()[0]
    c.ok("확인 필요" in detail, "요약에 확인 필요 건수가 남는다", detail)

    # ── 이어서 하기 · 진행률 배선 ──────────────────
    # 사용자가 전사를 한참 돌리다 멈춘 줄 알고 다시 눌렀다.
    # 화면이 [1/27] 로 보여 "처음부터 다시 한다"고 생각했지만, 실제로는
    # 남은 27건 중 1번째였다. 진짜 결함은 두 가지였다:
    #   · 파일 안 진행률 콜백이 pipeline 에서 audio 로 전달되지 않아
    #     긴 녹음에서 화면이 멈춘 듯 보였다 (배선이 끊겨 있었다)
    #   · "이미 몇 건 끝났는지"를 화면이 말해주지 않았다
    from evidence.ingest import pipeline, scanner

    resume_dir = tmp_path / "이어하기"
    resume_dir.mkdir()
    for i in range(4):
        (resume_dir / f"녹음{i}.m4a").write_bytes(f"AUDIO{i}".encode())
    scanner.scan(conn, resume_dir)

    pend = pipeline.pending(conn, kinds=(config.KIND_AUDIO,))
    ids = [r["id"] for r in pend]
    c.ok(len(ids) >= 4, "새로 넣은 녹음이 대기 목록에 들어간다")

    # 두 건을 끝난 것으로 표시하면 다음부터 목록에서 빠져야 한다
    # (앞 단계에서 이미 끝난 건이 있으므로 늘어난 만큼으로 센다)
    done_before = pipeline.already_done(conn, (config.KIND_AUDIO,))
    db.set_status(conn, ids[0], "extracted", "완료")
    db.set_status(conn, ids[1], "verified", "완료")
    after = pipeline.pending(conn, kinds=(config.KIND_AUDIO,))
    c.eq(len(after), len(ids) - 2, "끝난 것은 다시 처리하지 않는다")
    c.ok(all(r["id"] not in ids[:2] for r in after),
         "끝난 그 두 건이 목록에서 빠졌다")
    c.eq(pipeline.already_done(conn, (config.KIND_AUDIO,)), done_before + 2,
         "건너뛸 건수를 셀 수 있다 (화면에 '이미 N건 끝남'으로 보여준다)")

    # 중간에 멈춘 것(extracting)은 다시 목록에 들어와야 한다
    db.set_status(conn, ids[2], "extracting")
    again = pipeline.pending(conn, kinds=(config.KIND_AUDIO,))
    c.ok(any(r["id"] == ids[2] for r in again),
         "중간에 멈춘 파일은 다시 처리 대상이 된다")

    # 파일 안 진행률이 실제로 audio 까지 전달되는가 ← 이번 결함의 핵심
    seen = []

    def _file_progress(i, total, name, frac):
        seen.append(frac)

    import evidence.ingest.audio as audio_mod
    real_extract = audio_mod.extract

    def _spy(conn_, row, progress=None, **kw):
        # 실제 전사 대신, 받은 콜백을 그대로 불러 본다
        if progress:
            progress(0.5)
            progress(1.0)
        return real_extract(conn_, row, progress=progress, **kw)

    audio_mod.extract = _spy
    try:
        pipeline.run(conn, kinds=(config.KIND_AUDIO,),
                     file_progress=_file_progress)
    finally:
        audio_mod.extract = real_extract

    c.ok(seen, "파일 안 진행률이 pipeline 을 거쳐 전달된다",
         f"{len(seen)}회 보고됨")
    c.ok(all(0.0 <= f <= 1.0 for f in seen), "진행률이 0~1 범위다")

    # 멈추라고 하면 지금 파일까지만 하고 멈춘다
    for sid in ids:
        db.set_status(conn, sid, "registered")
    stop_after = {"n": 0}

    def _stop():
        stop_after["n"] += 1
        return stop_after["n"] > 2

    res = pipeline.run(conn, kinds=(config.KIND_AUDIO,), stop=_stop)
    c.ok(res["stopped"], "멈추라는 신호를 받으면 멈춘다")
    c.ok(res["done"] < len(ids), "남은 것은 다음에 이어서 한다",
         f"{res['done']}건만 처리")

    # 확인 필요 건수를 두 번 세지 않는다
    seg = conn.execute("SELECT id FROM segments LIMIT 1").fetchone()
    if seg:
        db.write(conn, "UPDATE segments SET alt_mismatch = 1, confidence = 0.1 "
                       "WHERE id = ?", (seg[0],))
        st = db.stats(conn)
        c.ok(st["needs_check"] <= st["segments"],
             "확인 필요 건수가 전체 구간 수를 넘지 않는다",
             f"확인 필요 {st['needs_check']} / 전체 {st['segments']}")
        c.ok(st["needs_check"] < st["mismatch"] + st["low_conf"]
             or st["mismatch"] == 0 or st["low_conf"] == 0,
             "둘 다 해당하는 구간을 두 번 세지 않는다")

    # ── 파일을 가로질러 같은 사람 묶기 ──────────────
    # 화자 분리(pyannote)는 파일 하나씩 돈다 — diarize.diarize() 가 파일
    # 하나만 받으므로 다른 파일에 누가 있었는지 알 방법이 없다. 그래서
    # 'SPEAKER_00' 은 **그 통화에서 먼저 말한 사람**일 뿐이다.
    # 통화마다 누가 먼저 말하는지 다르므로, 한꺼번에 이름을 붙이면
    # 상당수에서 '나'와 '상대방'이 뒤바뀐다. 법정 문서에서 치명적이다.
    import numpy as np
    from datetime import datetime as _dt
    from evidence.ingest import voiceprint as vp

    rng = np.random.default_rng(7)
    me_voice = rng.normal(size=64)
    me_voice /= np.linalg.norm(me_voice)
    other_voices, who = {}, {}

    for sid in range(101, 106):
        vf = tmp_path / f"call{sid}.m4a"
        vf.write_text(f"call{sid}", encoding="utf-8")
        vsid, _ = db.add_source(conn, integrity.fingerprint(vf), "audio",
                                is_my_conversation="Y")
        db.set_status(conn, vsid, "extracted")
        me_first = (sid % 2 == 1)          # 홀수 통화만 내가 먼저 말한다
        rows = []
        for turn in range(6):
            # pyannote 는 **먼저 말한 사람**에게 SPEAKER_00 을 준다
            spk = "SPEAKER_00" if turn % 2 == 0 else "SPEAKER_01"
            who[(vsid, spk)] = "나" if (turn % 2 == 0) == me_first else f"상대{sid}"
            rows.append({"seq": turn + 1, "speaker": spk,
                         "text": f"{sid}번 통화 {turn}번째 발언입니다 길게 말합니다",
                         "start_sec": turn * 10, "end_sec": turn * 10 + 9})
        db.add_segments(conn, vsid, rows)

    for (vsid, spk), person in who.items():
        base = me_voice if person == "나" else other_voices.setdefault(
            person, rng.normal(size=64) / np.linalg.norm(rng.normal(size=64)))
        v = base + rng.normal(scale=0.05, size=64)
        v = v / np.linalg.norm(v)
        db.write(conn,
                 """INSERT OR REPLACE INTO voiceprints
                    (source_id, speaker, vector, dim, seconds, group_no, made_at)
                    VALUES (?,?,?,?,?,NULL,?)""",
                 (vsid, spk, vp._serialize(v), 64, 20.0,
                  _dt.now().isoformat(timespec="seconds")))

    n_groups = vp.cluster(conn)
    c.eq(n_groups, 6, "통화 5건에서 사람 6명(나 1 + 상대 5)으로 묶는다")

    me_group = vp.suggest_me(conn)
    c.ok(me_group is not None, "사장님으로 보이는 묶음을 제안한다")
    gs = {g["group_no"]: g for g in vp.groups(conn)}
    c.eq(gs[me_group]["file_count"], 5,
         "제안한 묶음이 통화 5건 전부에 나온다 — 상대방은 통화마다 다르다")

    # 이름 붙이기가 파일마다 정확한가. 이것이 이 작업의 전부다.
    vp.set_group_label(conn, me_group, "나")
    labeled = conn.execute(
        "SELECT source_id, speaker FROM segments WHERE speaker_label = '나' "
        "GROUP BY source_id, speaker").fetchall()
    wrong = [(r["source_id"], r["speaker"]) for r in labeled
             if who.get((r["source_id"], r["speaker"])) != "나"]
    c.eq(len(labeled), 5, "통화 5건 모두에 '나'가 붙는다")
    c.ok(not wrong, "'나'가 상대방에게 잘못 붙은 곳이 없다", f"{wrong}")

    # 옛 방식이면 실제로 뒤바뀌는지 — 안 뒤바뀐다면 이 작업이 무의미하다
    old_way_wrong = [k for k in who
                     if k[1] == "SPEAKER_00" and who[k] != "나"]
    c.ok(len(old_way_wrong) > 0,
         "옛 방식(SPEAKER_00 전부에 '나')이었다면 실제로 뒤바뀐다",
         f"5건 중 {len(old_way_wrong)}건")

    c.ok(not any("한 통화에서" in w for w in vp.problems(conn)),
         "제대로 묶인 상태에서는 '한 통화에 같은 사람 둘' 경고가 없다")

    # 한 통화 안에 같은 사람이 둘일 수는 없다 → 억지로 만들어 잡히는지
    bad_no = max(gs) + 1
    db.write(conn, "UPDATE voiceprints SET group_no = ? WHERE source_id = "
                   "(SELECT MIN(source_id) FROM voiceprints)", (bad_no,))
    c.ok(any("한 통화에서" in w for w in vp.problems(conn)),
         "한 통화에서 두 화자가 같은 사람으로 묶이면 경고한다")
    vp.cluster(conn)                       # 원상복구

    # 화면이 묶기 전에는 이름을 못 붙이게 막는가
    sp_src = (Path(__file__).resolve().parent.parent
              / "evidence" / "ui" / "tab_speakers.py").read_text(encoding="utf-8")
    c.ok("_needs_voiceprint" in sp_src and "voiceprint.groups" in sp_src,
         "화면이 묶음 기준으로 이름을 붙인다")
    c.ok("뒤바뀝니다" in sp_src,
         "묶기 전에 이름을 붙이면 뒤바뀐다고 화면이 경고한다")

    # ── 전사본을 한 번에 전부 뽑는가 ────────────────
    from evidence.report import export as _exp
    outdir = tmp_path / "전사본전체"
    r = _exp.all_transcripts(conn, outdir, as_docx=False)
    c.ok(len(r["made"]) >= 5, "처리된 자료를 한 번에 전부 뽑는다",
         f"{len(r['made'])}건")
    c.eq(len(r["failed"]), 0, "실패 없이 저장된다")
    names = sorted(f.name for f in r["made"])
    c.ok(names[0][:2].isdigit(),
         "파일 이름 앞에 번호가 붙어 시간순으로 정렬된다", names[0])
    body = r["made"][0].read_text(encoding="utf-8")
    c.ok("전사본 —" in body and "해시" in body,
         "전사본에 원본 이름과 해시가 들어간다")

    conn.close()
    return c.report()


if __name__ == "__main__":
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        sys.exit(0 if run(Path(d)) else 1)
