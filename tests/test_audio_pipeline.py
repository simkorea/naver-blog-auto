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

    conn.close()
    return c.report()


if __name__ == "__main__":
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        sys.exit(0 if run(Path(d)) else 1)
