# -*- coding: utf-8 -*-
"""
음성 전사 — 녹음을 검색 가능한 텍스트로.

한국어 전사에서 반드시 챙겨야 하는 것들

  ① 무음 환청
     Whisper는 자막 달린 영상으로 학습해서, 말이 없는 구간에서
     "시청해주셔서 감사합니다" 같은 문장을 지어낸다.
     증거 문서에 이런 게 섞이면 치명적이다. → VAD로 무음을 걸러낸다.

  ② 무한 반복
     긴 통화에서 같은 문장이 끝없이 반복되는 고질 버그가 있다.
     → condition_on_previous_text=False 로 차단한다.

  ③ 고유명사 오인식
     한국어 인식률은 영어보다 확연히 낮아 인명·상호·단지명이 자주 틀린다.
     → 사건 고유명사를 hotwords로 미리 알려준다.

  ④ 단어 단위 타임스탬프
     발췌 구간을 말 중간에서 자르지 않으려면 단어 경계가 필요하다.
"""
import json
from pathlib import Path

from .. import config, db, integrity

_models = {}

# 무음 환청으로 자주 나오는 문구들. 정확히 일치하면 위험 표시를 단다.
_HALLUCINATION_PHRASES = [
    "시청해주셔서 감사합니다", "시청해 주셔서 감사합니다", "구독과 좋아요",
    "감사합니다 다음 영상에서", "MBC 뉴스", "KBS 뉴스", "이덕영입니다",
    "Thanks for watching", "Subtitles by", "다음 영상에서 만나요",
    "한글자막 by", "字幕", "본 영상은",
]


class ModelUnavailable(RuntimeError):
    """모델을 못 가져왔다. 사람이 읽고 조치할 수 있는 메시지를 담는다."""


def _download_hint(err: Exception) -> str:
    """
    모델 다운로드 실패는 원인이 대부분 네트워크다.
    스택 트레이스 대신 무엇을 하면 되는지 알려준다.
    """
    text = f"{type(err).__name__} {err}".lower()
    network = any(k in text for k in (
        "proxy", "connection", "timeout", "resolve", "network",
        "ssl", "403", "connecterror", "max retries", "unreachable"))

    if network:
        return (
            "음성 인식 모델을 내려받지 못했습니다 (인터넷 연결 문제로 보입니다).\n"
            "  · 인터넷 연결을 확인하세요.\n"
            "  · 회사망·공용 와이파이는 huggingface.co를 막는 경우가 있습니다. "
            "다른 네트워크에서 한 번만 받아두면 이후에는 인터넷 없이 동작합니다.\n"
            "  · 미리 받아두기:  python evidence/setup_check.py --models"
        )
    if "out of memory" in text or "cuda" in text:
        return (
            "그래픽카드 메모리가 부족합니다.\n"
            "  · 다른 프로그램을 닫고 다시 시도하세요.\n"
            "  · 또는 .env에 WHISPER_PRIMARY=medium 을 넣어 작은 모델을 쓰세요."
        )
    return f"음성 인식 모델을 불러오지 못했습니다: {err}"


def get_model(name: str):
    """모델을 한 번만 올려 재사용한다. 큰 모델은 로딩만 수십 초 걸린다."""
    if name in _models:
        return _models[name]
    from faster_whisper import WhisperModel

    hw = config.hardware()
    try:
        m = WhisperModel(name, device=hw["device"], compute_type=hw["compute_type"])
    except BaseException as first:
        try:
            # GPU 메모리 부족 등 → CPU로 강등해서라도 돌아가게 한다
            m = WhisperModel(name, device="cpu", compute_type="int8")
        except BaseException as second:
            raise ModelUnavailable(_download_hint(second or first)) from second
    _models[name] = m
    return m


def case_terms() -> list[str]:
    """사건 고유명사 사전을 읽는다. 인식률에 눈에 띄게 영향을 준다."""
    if not config.CASE_TERMS_YAML.exists():
        return []
    try:
        import yaml
        data = yaml.safe_load(config.CASE_TERMS_YAML.read_text(encoding="utf-8")) or {}
        return [str(t).strip() for t in (data.get("고유명사") or []) if str(t).strip()]
    except Exception:
        return []


def _prompt_from_terms(terms: list[str]) -> str | None:
    """
    hotwords/initial_prompt 문자열을 만든다.
    Whisper 프롬프트는 448 토큰 제한이 있어 너무 길면 잘린다.
    """
    if not terms:
        return None
    text = ", ".join(terms)
    return text[:800]


# ─────────────────────────────────────────────────────────
# 신뢰도
# ─────────────────────────────────────────────────────────
def _confidence(seg) -> float:
    """
    구간 신뢰도를 0~1로 환산한다.

    faster-whisper가 주는 세 지표를 합친다.
      avg_logprob        모델이 얼마나 확신했는가 (-1 이하면 의심)
      no_speech_prob     사실 말이 없었을 확률 (높으면 환청 가능성)
      compression_ratio  같은 말 반복 지표 (2.4 넘으면 반복 버그 의심)
    """
    lp = getattr(seg, "avg_logprob", None)
    ns = getattr(seg, "no_speech_prob", None) or 0.0
    cr = getattr(seg, "compression_ratio", None) or 1.0

    score = 1.0
    if lp is not None:
        # -0.2 이상이면 매우 좋음, -1.0이면 나쁨
        score *= max(0.0, min(1.0, (lp + 1.2) / 1.0))
    score *= max(0.0, 1.0 - ns)
    if cr > 2.4:
        score *= 0.4
    return round(max(0.0, min(1.0, score)), 3)


def _hallucination_risk(text: str, seg) -> int:
    """무음 환청 의심 여부."""
    t = (text or "").strip()
    if not t:
        return 0
    for phrase in _HALLUCINATION_PHRASES:
        if phrase in t:
            return 1
    # 같은 말이 세 번 넘게 반복되면 반복 버그
    words = t.split()
    if len(words) >= 6:
        uniq = len(set(words))
        if uniq <= len(words) / 3:
            return 1
    if (getattr(seg, "no_speech_prob", 0) or 0) > 0.7:
        return 1
    return 0


# ─────────────────────────────────────────────────────────
# 전사
# ─────────────────────────────────────────────────────────
def transcribe(path, model_name: str = None, progress=None,
               preprocess_level: str = None) -> list[dict]:
    """
    한 파일을 전사한다. 돌려주는 값: 구간 목록.

    preprocess_level: 잡음 제거 세기 (None이면 음질을 보고 알아서 정한다)
      통화 녹음은 음질이 나빠 그대로 넣으면 인식률이 떨어진다.
      전처리 사본을 만들어 전사에만 쓰고, 원본은 건드리지 않는다.
    """
    model_name = model_name or config.WHISPER_PRIMARY
    model = get_model(model_name)

    # 전처리 — 실패해도 원본으로 계속 진행한다
    from . import preprocess
    if preprocess_level is None:
        preprocess_level = preprocess.probe(path).get("suggested", "standard")
    work_path, prep_note = preprocess.prepare(path, preprocess_level)

    opts = config.whisper_options()
    prompt = _prompt_from_terms(case_terms())
    if prompt:
        # hotwords는 신형 API, initial_prompt는 구형 호환.
        opts["hotwords"] = prompt
        opts["initial_prompt"] = prompt

    try:
        segments, info = model.transcribe(str(work_path), **opts)
    except TypeError:
        # 설치된 faster-whisper 버전이 hotwords를 모르면 빼고 재시도
        opts.pop("hotwords", None)
        segments, info = model.transcribe(str(work_path), **opts)

    total = getattr(info, "duration", None) or 0
    rows = []
    for i, seg in enumerate(segments, 1):
        text = (seg.text or "").strip()
        if not text:
            continue
        words = None
        if getattr(seg, "words", None):
            words = json.dumps(
                [{"w": w.word, "s": round(w.start, 3), "e": round(w.end, 3)}
                 for w in seg.words],
                ensure_ascii=False,
            )
        rows.append({
            "seq": i,
            "text": text,
            "start_sec": round(seg.start, 3),
            "end_sec": round(seg.end, 3),
            "words_json": words,
            "avg_logprob": getattr(seg, "avg_logprob", None),
            "no_speech_prob": getattr(seg, "no_speech_prob", None),
            "compression_ratio": getattr(seg, "compression_ratio", None),
            "confidence": _confidence(seg),
            "hallucination_risk": _hallucination_risk(text, seg),
        })
        if progress and total:
            progress(min(seg.end / total, 1.0))

    return rows


def extract(conn, source_row, cross_verify: bool = None,
            diarize: bool = False, preprocess_level: str = None,
            progress=None, **_) -> int:
    """
    녹음 하나를 처리한다: (전처리) → 전사 → (교차 검증) → (화자 분리)
    """
    cross_verify = config.CROSS_VERIFY if cross_verify is None else cross_verify
    path = Path(source_row["path"])

    rows = transcribe(path, config.WHISPER_PRIMARY, progress=progress,
                      preprocess_level=preprocess_level)
    if not rows:
        db.set_status(conn, source_row["id"], "extracted", "인식된 음성 없음")
        return 0

    detail = f"{len(rows)}개 구간"

    # ── 교차 검증 ────────────────────────────────
    if cross_verify:
        from . import verify
        try:
            rows = verify.cross_check(path, rows, progress=progress,
                                      preprocess_level=preprocess_level)
            mismatched = sum(r.get("alt_mismatch", 0) for r in rows)
            detail += f" · 확인 필요 {mismatched}건"
        except Exception as e:
            detail += f" · 교차검증 건너뜀({type(e).__name__})"

    # ── 화자 분리 ────────────────────────────────
    if diarize:
        from . import diarize as diar
        try:
            rows, n_speakers = diar.apply(path, rows)
            detail += f" · 화자 {n_speakers}명"
        except Exception as e:
            detail += f" · 화자분리 건너뜀({type(e).__name__})"

    db.clear_segments(conn, source_row["id"])
    n = db.add_segments(conn, source_row["id"], rows)

    db.write(conn, "UPDATE sources SET model_used = ? WHERE id = ?",
             (config.WHISPER_PRIMARY, source_row["id"]))
    db.set_status(conn, source_row["id"], "extracted", detail)
    integrity.log("extract_audio", source_id=source_row["id"], segments=n,
                  model=config.WHISPER_PRIMARY, cross_verify=cross_verify,
                  diarize=diarize, hotwords=bool(case_terms()),
                  preprocess=preprocess_level)
    return n
