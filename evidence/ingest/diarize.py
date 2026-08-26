# -*- coding: utf-8 -*-
"""
화자 분리 — "누가 말했는지"를 나눈다.

이게 왜 결정적인가
  소송에서 중요한 것은 대부분 "상대방이 무슨 말을 했는가"다.
  내가 한 말과 상대가 한 말이 섞여 있으면, 유리한 발언을 찾아도
  그게 누구 입에서 나왔는지 증명할 수 없다.

방식
  pyannote가 "언제 누가 말했는지" 타임라인을 만들고,
  그것을 Whisper 전사 구간과 시간으로 겹쳐 맞춘다
  (whisperX·pyannote-whisper가 쓰는 방식과 같다).

pyannote 모델은 HuggingFace 토큰이 필요하다(무료).
토큰이 없거나 모델 접근 동의를 안 했으면 이 단계만 건너뛴다.
"""
from .. import config

_pipeline = None


def available() -> tuple[bool, str]:
    """화자 분리를 쓸 수 있는지와, 안 되면 그 이유."""
    try:
        import pyannote.audio          # noqa: F401
    except BaseException:
        return False, "pyannote.audio 미설치 → pip install pyannote.audio"
    if not config.HF_TOKEN:
        return False, (".env에 HF_TOKEN이 없습니다. huggingface.co에서 무료 발급 후 "
                       "pyannote/speaker-diarization-3.1 모델 페이지에서 약관에 동의하세요.")
    return True, ""


def _ensure_hf_compat() -> None:
    """
    pyannote 3.x 와 huggingface_hub 1.x 사이의 간극을 메운다.

    pyannote.audio 3.x 는 소스 안에 hf_hub_download(use_auth_token=...) 라고
    박혀 있는데, huggingface_hub 1.0 이 그 인자를 없앴다.
    그래서 화자 분리가 이렇게 죽는다:

        hf_hub_download() got an unexpected keyword argument 'use_auth_token'

    버전을 낮춰 맞출 수도 없다. sentence-transformers(의미 검색)는
    huggingface_hub 1.3 이상을 요구해서 서로 배타적이다.

    그래서 받는 쪽에 얇은 껍데기를 씌워 use_auth_token 을 token 으로 옮긴다.
    없어진 인자를 새 이름으로 넘겨주는 것뿐이라 동작이 달라지지 않는다.

    **pyannote 를 부르기 전에** 실행해야 한다. pyannote 가 import 시점에
    함수를 자기 이름공간으로 가져가기 때문이다.
    """
    try:
        import huggingface_hub as hub
    except ImportError:
        return

    import inspect

    for name in ("hf_hub_download", "snapshot_download"):
        fn = getattr(hub, name, None)
        if fn is None or getattr(fn, "_evidence_shim", False):
            continue
        try:
            params = inspect.signature(fn).parameters
        except (TypeError, ValueError):
            continue
        if "use_auth_token" in params or "token" not in params:
            continue          # 아직 옛 인자를 받거나, 손댈 수 없는 형태

        def _wrap(original):
            def shim(*args, use_auth_token=None, **kwargs):
                if use_auth_token is not None and kwargs.get("token") is None:
                    kwargs["token"] = use_auth_token
                return original(*args, **kwargs)
            shim._evidence_shim = True
            shim.__name__ = getattr(original, "__name__", "hf_shim")
            shim.__doc__ = getattr(original, "__doc__", None)
            return shim

        setattr(hub, name, _wrap(fn))

        # 이미 가져다 쓴 곳이 있으면 거기도 바꿔준다
        import sys
        for mod_name, mod in list(sys.modules.items()):
            if not mod_name.startswith("pyannote"):
                continue
            if getattr(mod, name, None) is fn:
                setattr(mod, name, getattr(hub, name))


def get_pipeline():
    global _pipeline
    if _pipeline is not None:
        return _pipeline

    ok, why = available()
    if not ok:
        raise RuntimeError(why)

    _ensure_hf_compat()

    from pyannote.audio import Pipeline
    _pipeline = Pipeline.from_pretrained(
        config.DIARIZE_MODEL, use_auth_token=config.HF_TOKEN
    )
    hw = config.hardware()
    if hw["device"] == "cuda":
        try:
            import torch
            _pipeline.to(torch.device("cuda"))
        except BaseException:
            pass
    return _pipeline


def diarize(path, num_speakers: int = None,
            min_speakers: int = None, max_speakers: int = None) -> list[dict]:
    """
    "언제 누가 말했는지" 타임라인을 만든다.

    통화 녹음은 보통 2명이므로 힌트를 주면 정확도가 오른다.
    """
    pipe = get_pipeline()
    kwargs = {}
    if num_speakers:
        kwargs["num_speakers"] = num_speakers
    else:
        if min_speakers:
            kwargs["min_speakers"] = min_speakers
        if max_speakers:
            kwargs["max_speakers"] = max_speakers

    result = pipe(str(path), **kwargs)
    turns = []
    for turn, _, speaker in result.itertracks(yield_label=True):
        turns.append({"start": float(turn.start), "end": float(turn.end),
                      "speaker": str(speaker)})
    turns.sort(key=lambda t: t["start"])
    return turns


def assign(segments: list[dict], turns: list[dict]) -> list[dict]:
    """
    전사 구간에 화자를 붙인다.

    모델마다 구간을 나누는 지점이 달라 1:1로 맞지 않는다.
    그래서 시간이 가장 많이 겹치는 화자를 고른다.

    단어 단위 타임스탬프가 있으면 그것으로 더 정밀하게 판단한다.
    한 구간 안에서 화자가 바뀌는 경우(말이 겹칠 때)를 잡아내기 위함이다.
    """
    import json

    out = []
    for seg in segments:
        row = dict(seg)
        s, e = seg.get("start_sec"), seg.get("end_sec")
        if s is None or e is None or not turns:
            out.append(row)
            continue

        # 겹치는 시간을 화자별로 합산
        totals = {}
        for t in turns:
            ov = max(0.0, min(e, t["end"]) - max(s, t["start"]))
            if ov > 0:
                totals[t["speaker"]] = totals.get(t["speaker"], 0.0) + ov

        if totals:
            ordered = sorted(totals.items(), key=lambda x: -x[1])
            best, best_ov = ordered[0]
            row["speaker"] = best

            span = max(0.01, e - s)
            share = best_ov / span
            runner_up = (ordered[1][1] / span) if len(ordered) > 1 else 0.0

            # 누구 말인지 단정할 수 없는 두 경우
            #   ① 1등 화자가 구간의 60%도 못 채운다 → 애초에 근거가 약하다
            #   ② 2등 화자도 상당 부분을 차지한다 → 두 사람이 겹쳐 말했다
            #
            # ②를 따로 보는 이유: 화자 구간이 서로 겹치면 1등과 2등이
            # 동시에 60%를 넘길 수 있다. 1등 점유율만 보면 완전한 겹침을
            # "확실하다"고 통과시킨다. 발언을 엉뚱한 사람에게 귀속시키는 것은
            # 증거에서 가장 치명적인 오류다.
            if share < 0.6 or runner_up > 0.35:
                row["speaker_uncertain"] = 1
                row["confidence"] = round((row.get("confidence") or 0.7) * 0.8, 3)
        out.append(row)
    return out


def apply(path, segments: list[dict], num_speakers: int = None) -> tuple[list, int]:
    """전사 결과에 화자를 붙인다. 돌려주는 값: (구간 목록, 화자 수)"""
    turns = diarize(path, num_speakers=num_speakers, min_speakers=1, max_speakers=6)
    rows = assign(segments, turns)
    n = len({t["speaker"] for t in turns})
    return rows, n


# ─────────────────────────────────────────────────────────
# 화자 라벨링 (사용자가 '나' / '고객'을 지정)
# ─────────────────────────────────────────────────────────
def speaker_list(conn, source_id: int = None) -> list[dict]:
    """
    자동 분리된 화자 목록과, 각 화자를 알아볼 수 있는 대표 발화.

    사용자는 이 발화들을 듣고 "이게 나", "이게 고객"이라고 지정한다.
    """
    sql = """SELECT speaker, speaker_label, count(*) AS n,
                    SUM(COALESCE(end_sec,0) - COALESCE(start_sec,0)) AS talk_sec,
                    MIN(source_id) AS source_id
             FROM segments
             WHERE speaker IS NOT NULL"""
    args = []
    if source_id:
        sql += " AND source_id = ?"
        args.append(source_id)
    sql += " GROUP BY speaker, speaker_label ORDER BY talk_sec DESC"

    out = []
    for r in conn.execute(sql, args).fetchall():
        samples = conn.execute(
            """SELECT id, text, start_sec, end_sec, source_id
               FROM segments
               WHERE speaker = ? AND length(text) > 8
               ORDER BY length(text) DESC LIMIT 3""",
            (r["speaker"],),
        ).fetchall()
        out.append({
            "speaker": r["speaker"],
            "label": r["speaker_label"],
            "count": r["n"],
            "talk_sec": r["talk_sec"] or 0,
            "samples": [dict(s) for s in samples],
        })
    return out


def set_label(conn, speaker: str, label: str, source_id: int = None) -> int:
    """'SPEAKER_00' → '고객 홍○○' 처럼 이름을 붙인다."""
    from .. import db, integrity

    sql = "UPDATE segments SET speaker_label = ? WHERE speaker = ?"
    args = [label, speaker]
    if source_id:
        sql += " AND source_id = ?"
        args.append(source_id)
    cur = db.write(conn, sql, args)
    integrity.log("speaker_labeled", speaker=speaker, label=label,
                  source_id=source_id, rows=cur.rowcount)
    return cur.rowcount


def set_segment_speaker(conn, segment_id: int, label: str) -> None:
    """
    한 구간의 화자를 손으로 고친다.
    음질이 나쁜 통화에서는 자동 분리가 틀리기도 하므로 반드시 필요하다.
    """
    from .. import db, integrity
    db.write(conn, "UPDATE segments SET speaker_label = ? WHERE id = ?",
             (label, segment_id))
    integrity.log("speaker_corrected", segment_id=segment_id, label=label)
