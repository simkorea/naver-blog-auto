# -*- coding: utf-8 -*-
"""
목소리 지문 — 파일을 가로질러 "같은 사람"을 묶는다.

왜 필요한가 (이것이 없으면 증거 문서에 틀린 이름이 붙는다)
  화자 분리(pyannote)는 **파일 하나씩** 돌아간다. `diarize.diarize()` 가
  파일 하나만 받으므로, 다른 파일에 누가 있었는지 알 방법이 애초에 없다.
  그래서 'SPEAKER_00' 은 **그 파일에서 먼저 말한 사람**일 뿐이다.

  통화는 어떤 날은 내가 먼저 "여보세요" 하고, 어떤 날은 상대가 먼저 한다.
  즉 A파일의 SPEAKER_00 과 B파일의 SPEAKER_00 은 다른 사람일 수 있다.

  그런데 이름 붙이기가 `WHERE speaker = 'SPEAKER_00'` 로 되어 있어서
  53건 전부에 한꺼번에 붙는다. 그대로 두면 **절반쯤에서 '나'와 '상대방'이
  뒤바뀐 전사본**이 나온다. 법정에 내는 문서에서 이건 치명적이다.

어떻게 푸나
  (파일, 화자) 마다 목소리에서 지문을 뽑아 두고, 파일을 가로질러 가까운
  것끼리 묶는다. 사장님 목소리는 53건 전부에 나오고 상대방은 통화마다
  다르므로, **가장 많은 파일에 나오는 묶음이 사장님**이다.

  다만 그것을 프로그램이 단정하지 않는다. 화면이 대표 발화를 들려주고
  사장님이 확인한 뒤에 이름이 붙는다.

    python evidence/transcribe.py --voiceprint   지문 만들고 묶기
"""
import struct
from datetime import datetime
from pathlib import Path

from .. import config, db, integrity

# 지문 하나를 만드는 데 쓸 음성 길이. 길수록 정확하지만 느리다.
TARGET_SECONDS = 24.0
MIN_SPAN = 1.0           # 너무 짧은 구간은 목소리 판단에 쓸모가 없다
MAX_SPAN = 8.0
MIN_TOTAL = 3.0          # 이보다 적게 말한 화자는 지문을 못 만든다

# 코사인 거리 기준. 이보다 가까우면 같은 사람으로 본다.
# 어디까지나 초안이다 — 사장님이 대표 발화를 듣고 확인한다.
DEFAULT_THRESHOLD = 0.45

_embedder_cache = None


class EmbedderUnavailable(RuntimeError):
    """목소리 지문 모델을 못 가져왔다. 사람이 읽고 조치할 메시지를 담는다."""


# ─────────────────────────────────────────────────────────
# 지문 뽑기
# ─────────────────────────────────────────────────────────
def get_embedder():
    """
    목소리 지문 모델. 화자 분리가 안에서 쓰는 것과 같은 모델이므로
    이미 내려받혀 있다 — 새로 받지 않는다.

    돌려주는 것: waveform(float32 1차원, 16kHz) → 지문(1차원 벡터)
    """
    global _embedder_cache
    if _embedder_cache is not None:
        return _embedder_cache

    from . import diarize
    ok, why = diarize.available()
    if not ok:
        raise EmbedderUnavailable(why)

    try:
        import numpy as np
        import torch
        from pyannote.audio.pipelines.speaker_verification import (
            PretrainedSpeakerEmbedding)

        diarize._ensure_hf_compat()
        with diarize._allow_full_checkpoint_load():
            model = PretrainedSpeakerEmbedding(
                config.EMBED_SPEAKER_MODEL,
                device=torch.device(config.hardware()["device"]),
                use_auth_token=config.HF_TOKEN or None,
            )
    except EmbedderUnavailable:
        raise
    except BaseException as e:
        raise EmbedderUnavailable(
            f"목소리 지문 모델을 불러오지 못했습니다: {type(e).__name__}: {e}\n"
            "  화자 분리가 되는 상태라면 같은 모델이므로 대개 됩니다.\n"
            "  python evidence/setup_check.py 로 상태를 확인하세요."
        ) from e

    def run(wave):
        # pyannote 는 (묶음, 채널, 표본) 모양을 기대한다
        t = torch.from_numpy(np.asarray(wave, dtype="float32")).reshape(1, 1, -1)
        with torch.no_grad():
            v = model(t)
        v = np.asarray(v).reshape(-1).astype("float32")
        return v

    _embedder_cache = run
    return run


def pick_spans(conn, source_id: int, speaker: str,
               want_sec: float = TARGET_SECONDS) -> list[tuple]:
    """
    지문을 만들 구간을 고른다.

    말이 겹친 구간(speaker_uncertain)과 환청 의심 구간은 뺀다 —
    두 사람 목소리가 섞인 조각으로 지문을 만들면 묶기가 어긋난다.
    """
    rows = conn.execute(
        """SELECT start_sec, end_sec
           FROM segments
           WHERE source_id = ? AND speaker = ?
             AND start_sec IS NOT NULL AND end_sec IS NOT NULL
             AND COALESCE(speaker_uncertain, 0) = 0
             AND COALESCE(hallucination_risk, 0) = 0
           ORDER BY (end_sec - start_sec) DESC""",
        (source_id, speaker),
    ).fetchall()

    spans, total = [], 0.0
    for r in rows:
        s, e = float(r["start_sec"]), float(r["end_sec"])
        if e - s < MIN_SPAN:
            break                       # 길이순이므로 여기서부터는 전부 짧다
        e = min(e, s + MAX_SPAN)
        spans.append((s, e))
        total += e - s
        if total >= want_sec:
            break
    return spans


def embed_spans(wav_path, spans: list, embedder) -> tuple:
    """
    고른 구간들의 지문을 만들어 평균낸다.
    돌려주는 값: (지문, 실제로 쓴 초)
    """
    import numpy as np
    import soundfile as sf

    vecs, used = [], 0.0
    with sf.SoundFile(str(wav_path)) as f:
        rate = f.samplerate
        n_frames = len(f)
        for start, end in spans:
            a = int(start * rate)
            b = min(int(end * rate), n_frames)
            if b - a < int(MIN_SPAN * rate):
                continue
            f.seek(a)
            wave = f.read(b - a, dtype="float32", always_2d=True)[:, 0]
            try:
                v = embedder(wave)
            except BaseException:
                continue                # 한 조각이 실패해도 나머지로 만든다
            v = np.asarray(v, dtype="float32").reshape(-1)
            n = float(np.linalg.norm(v))
            if n > 0:
                vecs.append(v / n)
                used += (b - a) / rate

    if not vecs:
        return None, 0.0
    mean = np.mean(np.stack(vecs), axis=0)
    n = float(np.linalg.norm(mean))
    return (mean / n if n > 0 else mean), used


def _serialize(vec) -> bytes:
    return struct.pack(f"{len(vec)}f", *[float(x) for x in vec])


def _deserialize(blob: bytes, dim: int):
    import numpy as np
    return np.asarray(struct.unpack(f"{dim}f", blob), dtype="float32")


def pairs(conn, only_missing: bool = True) -> list[dict]:
    """지문을 만들어야 할 (파일, 화자) 목록."""
    sql = """SELECT s.source_id, s.speaker, src.path,
                    count(*) AS n,
                    SUM(COALESCE(s.end_sec,0) - COALESCE(s.start_sec,0)) AS talk_sec
             FROM segments s JOIN sources src ON src.id = s.source_id
             WHERE s.speaker IS NOT NULL"""
    if only_missing:
        sql += (" AND NOT EXISTS (SELECT 1 FROM voiceprints v"
                " WHERE v.source_id = s.source_id AND v.speaker = s.speaker)")
    sql += " GROUP BY s.source_id, s.speaker ORDER BY s.source_id, s.speaker"
    return [dict(r) for r in conn.execute(sql).fetchall()]


def build(conn, progress=None, embedder=None, only_missing: bool = True) -> dict:
    """
    지문을 만들어 저장한다. 중단 후 다시 실행하면 남은 것만 한다.

    돌려주는 값: {"made": n, "skipped": n, "failed": [(파일, 화자, 이유)]}
    """
    from . import preprocess

    todo = pairs(conn, only_missing=only_missing)
    out = {"made": 0, "skipped": 0, "failed": []}
    if not todo:
        return out

    embed = embedder or get_embedder()
    for i, it in enumerate(todo, 1):
        name = Path(it["path"]).name
        if progress:
            progress(i, len(todo), name, it["speaker"])

        if (it["talk_sec"] or 0) < MIN_TOTAL:
            out["skipped"] += 1
            out["failed"].append((name, it["speaker"], "말한 시간이 너무 짧음"))
            continue

        spans = pick_spans(conn, it["source_id"], it["speaker"])
        if not spans:
            out["skipped"] += 1
            out["failed"].append((name, it["speaker"], "쓸 만한 구간 없음"))
            continue

        src = Path(it["path"])
        if not src.exists():
            out["skipped"] += 1
            out["failed"].append((name, it["speaker"], "원본 파일을 찾을 수 없음"))
            continue

        try:
            # 전사·화자분리가 실제로 들은 그 사본을 그대로 쓴다.
            # 이미 만들어져 있으므로 다시 만들지 않는다.
            level = preprocess.probe(src).get("suggested", "standard")
            wav, _ = preprocess.prepare(src, level)
            vec, used = embed_spans(wav, spans, embed)
        except BaseException as e:
            out["skipped"] += 1
            out["failed"].append((name, it["speaker"], f"{type(e).__name__}: {e}"))
            continue

        if vec is None:
            out["skipped"] += 1
            out["failed"].append((name, it["speaker"], "지문을 만들지 못함"))
            continue

        db.write(
            conn,
            """INSERT OR REPLACE INTO voiceprints
               (source_id, speaker, vector, dim, seconds, group_no, made_at)
               VALUES (?,?,?,?,?,NULL,?)""",
            (it["source_id"], it["speaker"], _serialize(vec), len(vec),
             round(used, 2), datetime.now().isoformat(timespec="seconds")),
        )
        out["made"] += 1

    integrity.log("voiceprints_built", made=out["made"], skipped=out["skipped"])
    return out


# ─────────────────────────────────────────────────────────
# 파일을 가로질러 묶기
# ─────────────────────────────────────────────────────────
def cluster(conn, threshold: float = DEFAULT_THRESHOLD) -> int:
    """
    지문이 가까운 것끼리 묶는다. 돌려주는 값: 묶음 개수.

    묶음 번호는 **파일 수가 많은 순**으로 매긴다. 사장님은 모든 통화에
    있고 상대방은 통화마다 다르므로, 0번이 사장님일 가능성이 가장 높다.
    (단정하지 않는다 — 화면이 대표 발화를 들려주고 확인받는다)
    """
    import numpy as np

    rows = conn.execute(
        "SELECT id, source_id, speaker, vector, dim FROM voiceprints"
    ).fetchall()
    if not rows:
        return 0

    vecs = np.stack([_deserialize(r["vector"], r["dim"]) for r in rows])

    if len(rows) == 1:
        labels = np.array([0])
    else:
        try:
            from sklearn.cluster import AgglomerativeClustering
            labels = AgglomerativeClustering(
                n_clusters=None, distance_threshold=threshold,
                metric="cosine", linkage="average",
            ).fit_predict(vecs)
        except BaseException:
            labels = _greedy_cluster(vecs, threshold)

    # 파일 수가 많은 묶음부터 0, 1, 2 …
    files_of = {}
    for lab, r in zip(labels, rows):
        files_of.setdefault(int(lab), set()).add(r["source_id"])
    order = sorted(files_of, key=lambda k: (-len(files_of[k]), k))
    renumber = {old: new for new, old in enumerate(order)}

    db.write_many(
        conn, "UPDATE voiceprints SET group_no = ? WHERE id = ?",
        [(renumber[int(lab)], r["id"]) for lab, r in zip(labels, rows)],
    )
    integrity.log("voiceprints_clustered", groups=len(order),
                  prints=len(rows), threshold=threshold)
    return len(order)


def _greedy_cluster(vecs, threshold: float):
    """
    sklearn 이 없을 때를 위한 대비책. 앞에서부터 훑으며 가까우면 붙인다.
    결과는 sklearn 만 못하지만 아무것도 못 하는 것보다 낫다.
    """
    import numpy as np

    labels = np.full(len(vecs), -1)
    centers = []
    for i, v in enumerate(vecs):
        best, best_d = -1, 1e9
        for j, c in enumerate(centers):
            d = 1.0 - float(np.dot(v, c))
            if d < best_d:
                best, best_d = j, d
        if best >= 0 and best_d <= threshold:
            labels[i] = best
            k = int((labels[:i + 1] == best).sum())
            c = centers[best] * (k - 1) / k + v / k
            n = float(np.linalg.norm(c))
            centers[best] = c / n if n else c
        else:
            labels[i] = len(centers)
            centers.append(v)
    return labels


def groups(conn) -> list[dict]:
    """
    묶음 목록. 화면이 이걸로 "이 사람은 누구인가요?"를 묻는다.

    각 묶음마다 대표 발화를 붙인다 — 사장님이 듣고 판단하실 근거다.
    """
    rows = conn.execute(
        """SELECT v.group_no, v.source_id, v.speaker, v.seconds,
                  src.path,
                  (SELECT speaker_label FROM segments
                    WHERE source_id = v.source_id AND speaker = v.speaker
                      AND speaker_label IS NOT NULL LIMIT 1) AS label
           FROM voiceprints v JOIN sources src ON src.id = v.source_id
           WHERE v.group_no IS NOT NULL
           ORDER BY v.group_no, v.source_id"""
    ).fetchall()

    by_group = {}
    for r in rows:
        g = by_group.setdefault(int(r["group_no"]), {
            "group_no": int(r["group_no"]), "members": [],
            "files": set(), "label": None})
        g["members"].append({"source_id": r["source_id"],
                             "speaker": r["speaker"],
                             "file": Path(r["path"]).name})
        g["files"].add(r["source_id"])
        if r["label"] and not g["label"]:
            g["label"] = r["label"]

    out = []
    for g in sorted(by_group.values(), key=lambda x: x["group_no"]):
        ids = list(g["files"])
        marks = ",".join("?" * len(ids))
        stat = conn.execute(
            f"""SELECT count(*) AS n,
                       SUM(COALESCE(end_sec,0) - COALESCE(start_sec,0)) AS sec
                FROM segments
                WHERE source_id IN ({marks})
                  AND (source_id, speaker) IN (
                      SELECT source_id, speaker FROM voiceprints
                      WHERE group_no = ?)""",
            ids + [g["group_no"]],
        ).fetchone()

        samples = conn.execute(
            f"""SELECT s.id, s.text, s.start_sec, s.source_id, src.path
                FROM segments s JOIN sources src ON src.id = s.source_id
                WHERE (s.source_id, s.speaker) IN (
                          SELECT source_id, speaker FROM voiceprints
                          WHERE group_no = ?)
                  AND length(s.text) > 10
                ORDER BY length(s.text) DESC LIMIT 3""",
            (g["group_no"],),
        ).fetchall()

        out.append({
            "group_no": g["group_no"],
            "label": g["label"],
            "file_count": len(g["files"]),
            "members": g["members"],
            "segments": (stat["n"] if stat else 0) or 0,
            "talk_sec": (stat["sec"] if stat else 0) or 0,
            "samples": [dict(s) for s in samples],
        })
    return out


def set_group_label(conn, group_no: int, label: str) -> int:
    """
    묶음에 이름을 붙인다. **(파일, 화자) 쌍 단위로만** 바꾼다.

    옛 방식(`WHERE speaker = 'SPEAKER_00'`)은 파일을 가리지 않고 전부
    바꿔서, 파일마다 번호가 다르다는 사실 때문에 절반쯤이 뒤바뀌었다.
    """
    cur = db.write(
        conn,
        """UPDATE segments SET speaker_label = ?
           WHERE (source_id, speaker) IN (
               SELECT source_id, speaker FROM voiceprints WHERE group_no = ?)""",
        (label, group_no),
    )
    integrity.log("voice_group_labeled", group_no=group_no, label=label,
                  rows=cur.rowcount)
    return cur.rowcount


def suggest_me(conn):
    """
    사장님일 가능성이 가장 높은 묶음 번호.

    사장님은 모든 통화에 있고 상대방은 통화마다 다르다. 그러니 **가장 많은
    파일에 나오는 묶음**이 사장님이다. 어디까지나 제안이고, 화면이
    대표 발화를 들려주고 확인받은 뒤에야 이름이 붙는다.
    """
    gs = groups(conn)
    if not gs:
        return None
    top = max(gs, key=lambda g: (g["file_count"], g["talk_sec"]))
    others = [g for g in gs if g["group_no"] != top["group_no"]]
    # 다른 묶음과 견줘 뚜렷하게 많은 파일에 나와야 제안한다
    if others and top["file_count"] <= max(g["file_count"] for g in others):
        return None
    return top["group_no"]


def problems(conn) -> list[str]:
    """
    묶기 결과가 미심쩍은 곳. 사장님이 눈으로 확인해야 하는 지점이다.

    한 파일 안에서 두 화자가 같은 묶음에 들어갔다면 묶기가 틀린 것이다 —
    같은 통화에서 같은 사람이 두 명일 수 없다.
    """
    out = []
    dup = conn.execute(
        """SELECT v.group_no, src.path, count(*) AS n
           FROM voiceprints v JOIN sources src ON src.id = v.source_id
           WHERE v.group_no IS NOT NULL
           GROUP BY v.group_no, v.source_id
           HAVING count(*) > 1"""
    ).fetchall()
    for r in dup:
        out.append(f"{Path(r['path']).name} — 한 통화에서 화자 {r['n']}명이 "
                   f"같은 사람(묶음 {r['group_no']})으로 묶였습니다. 확인하세요.")

    missing = conn.execute(
        """SELECT count(*) FROM sources
           WHERE kind = 'audio' AND status IN ('extracted','verified')
             AND id NOT IN (SELECT source_id FROM voiceprints)"""
    ).fetchone()[0]
    if missing:
        out.append(f"녹음 {missing}건은 목소리 지문이 없습니다 "
                   "(화자 분리를 안 했거나 말이 너무 짧은 경우).")
    return out
