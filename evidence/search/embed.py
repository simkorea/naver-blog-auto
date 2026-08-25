# -*- coding: utf-8 -*-
"""
로컬 임베딩 — 의미 검색의 엔진.

BGE-M3를 쓴다. 100개 이상 언어를 지원하는 다국어 모델로 한국어 성능이
좋고, 사용자 PC의 GPU에서 그대로 돌아간다. 소송 자료를 외부 API로
보내지 않아도 "고객이 계약을 인정하는 뉘앙스" 같은 문장 검색이 된다.

모델이 없거나 설치가 안 되어 있으면 조용히 비활성화되고,
키워드 검색만으로 프로그램은 정상 동작한다.
"""
import struct

from .. import config

_model = None
_load_failed = False


def embedder_ready() -> bool:
    return _load()is not None


def _load():
    """모델을 한 번만 올린다. 최초 1회는 다운로드(약 2GB)가 발생한다."""
    global _model, _load_failed
    if _model is not None:
        return _model
    if _load_failed:
        return None
    try:
        from sentence_transformers import SentenceTransformer
        hw = config.hardware()
        _model = SentenceTransformer(
            config.EMBED_MODEL,
            device=hw.get("embed_device", "cpu"),
        )
        return _model
    except Exception as e:
        _load_failed = True
        print(f"        [안내] 의미 검색 비활성화 ({type(e).__name__}) — 키워드 검색은 정상 동작합니다")
        print(f"               설치: pip install sentence-transformers")
        return None


def embed_texts(texts: list[str], batch_size: int = 16, progress=None):
    """여러 문장을 한 번에 임베딩한다."""
    model = _load()
    if model is None:
        return None
    out = []
    for i in range(0, len(texts), batch_size):
        chunk = texts[i:i + batch_size]
        vecs = model.encode(chunk, normalize_embeddings=True,
                            show_progress_bar=False)
        out.extend(vecs)
        if progress:
            progress(min(i + batch_size, len(texts)), len(texts))
    return out


def embed_query(text: str):
    model = _load()
    if model is None:
        return None
    return model.encode([text], normalize_embeddings=True,
                        show_progress_bar=False)[0]


def serialize(vec) -> bytes:
    return struct.pack(f"{len(vec)}f", *[float(x) for x in vec])


def build_index(conn, progress=None, only_missing: bool = True) -> int:
    """
    아직 임베딩되지 않은 구간을 전부 벡터화해 저장한다.
    중단 후 다시 실행해도 남은 것만 처리한다.
    """
    from .. import db
    if not db.vec_available(conn):
        return 0
    if _load() is None:
        return 0

    sql = "SELECT id, text FROM segments"
    if only_missing:
        sql += " WHERE id NOT IN (SELECT segment_id FROM vec_segments)"
    rows = conn.execute(sql).fetchall()
    if not rows:
        return 0

    ids = [r["id"] for r in rows]
    texts = [r["text"] for r in rows]
    vecs = embed_texts(texts, progress=progress)
    if vecs is None:
        return 0

    conn.executemany(
        "INSERT OR REPLACE INTO vec_segments(segment_id, embedding) VALUES (?, ?)",
        [(sid, serialize(v)) for sid, v in zip(ids, vecs)],
    )
    conn.commit()
    return len(ids)
