# -*- coding: utf-8 -*-
"""
SQLite 저장소 — 전부 한 파일(evidence.db) 안에 들어간다.

여기 담기는 것
  sources     등록된 원본 파일 (해시 봉인 · 적법성 플래그)
  segments    텍스트화된 구간 (녹음 구간 / 카톡 메시지 / 문서 페이지)
  segments_fts  한국어 키워드 검색용 FTS5 trigram 인덱스
  vec_segments  의미 검색용 벡터 (sqlite-vec, 선택)
  tags/issues/notes   쟁점 · 판단 · 청취 확인 기록
  basket/clips        발췌 장바구니와 추출된 클립
  law_articles/precedents/comments  법률 계층

한국어 검색에 trigram을 쓰는 이유:
  기본 토크나이저(unicode61)는 "계약금을"을 통째로 한 토큰으로 잡아
  '계약'으로 검색하면 걸리지 않는다. trigram은 3글자 단위로 쪼개므로
  조사가 붙어도 부분 일치가 된다. 다만 2글자 이하 검색어는 trigram MATCH가
  불가능해 LIKE로 넘긴다(이때도 trigram 인덱스가 LIKE를 가속한다).
"""
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from . import config

SCHEMA_VERSION = 1

_SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- ───────────────────────────────────────── 원본 파일
CREATE TABLE IF NOT EXISTS sources (
    id                  INTEGER PRIMARY KEY,
    path                TEXT NOT NULL UNIQUE,
    sha256              TEXT NOT NULL,
    kind                TEXT NOT NULL,        -- audio|image|document|kakao|email
    bytes               INTEGER,
    mtime               TEXT,
    duration_sec        REAL,

    -- 적법성 게이트: 본인이 대화 당사자인 녹음만 안전하게 쓸 수 있다.
    is_my_conversation  TEXT DEFAULT 'UNKNOWN',   -- Y | N | UNKNOWN | NA
    counterparty        TEXT,
    occurred_at         TEXT,                     -- 실제 발생 일시
    occurred_at_est     INTEGER DEFAULT 0,        -- 1이면 추정값
    memo                TEXT,

    status              TEXT DEFAULT 'registered',
        -- registered → extracting → extracted → verified → failed
    status_detail       TEXT,
    model_used          TEXT,
    ingested_at         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sources_sha ON sources(sha256);
CREATE INDEX IF NOT EXISTS idx_sources_kind ON sources(kind);

-- ───────────────────────────────────────── 텍스트 구간
CREATE TABLE IF NOT EXISTS segments (
    id              INTEGER PRIMARY KEY,
    source_id       INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    seq             INTEGER NOT NULL,
    text            TEXT NOT NULL,

    speaker           TEXT,        -- 'SPEAKER_00' 등 자동 분리 결과
    speaker_label     TEXT,        -- '나' / '고객 홍○○' 등 사용자가 붙인 이름
    speaker_uncertain INTEGER DEFAULT 0,   -- 말이 겹쳐 누구 말인지 불확실
    start_sec       REAL,
    end_sec         REAL,
    page_no         INTEGER,
    occurred_at     TEXT,

    words_json      TEXT,          -- 단어 단위 타임스탬프

    -- 신뢰도 (Whisper가 내놓는 지표 + 교차 검증)
    avg_logprob         REAL,
    no_speech_prob      REAL,
    compression_ratio   REAL,
    confidence          REAL,      -- 0~1 종합 점수
    alt_text            TEXT,      -- 2차 모델 전사 결과
    alt_mismatch        INTEGER DEFAULT 0,
    mismatch_kind       TEXT,      -- 부정어 뒤집힘 | 숫자 불일치 | 표현 불일치
    hallucination_risk  INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_seg_source ON segments(source_id, seq);
CREATE INDEX IF NOT EXISTS idx_seg_speaker ON segments(speaker_label);
CREATE INDEX IF NOT EXISTS idx_seg_conf ON segments(confidence);

-- 한국어 키워드 검색
CREATE VIRTUAL TABLE IF NOT EXISTS segments_fts
    USING fts5(text, content='segments', content_rowid='id', tokenize='trigram');

CREATE TRIGGER IF NOT EXISTS segments_ai AFTER INSERT ON segments BEGIN
    INSERT INTO segments_fts(rowid, text) VALUES (new.id, new.text);
END;
CREATE TRIGGER IF NOT EXISTS segments_ad AFTER DELETE ON segments BEGIN
    INSERT INTO segments_fts(segments_fts, rowid, text) VALUES('delete', old.id, old.text);
END;
CREATE TRIGGER IF NOT EXISTS segments_au AFTER UPDATE OF text ON segments BEGIN
    INSERT INTO segments_fts(segments_fts, rowid, text) VALUES('delete', old.id, old.text);
    INSERT INTO segments_fts(rowid, text) VALUES (new.id, new.text);
END;

-- ───────────────────────────────────────── 쟁점 · 태그 · 판단
CREATE TABLE IF NOT EXISTS issues (
    id           INTEGER PRIMARY KEY,
    name         TEXT NOT NULL UNIQUE,
    description  TEXT,
    my_position  TEXT
);

CREATE TABLE IF NOT EXISTS tags (
    id          INTEGER PRIMARY KEY,
    segment_id  INTEGER NOT NULL REFERENCES segments(id) ON DELETE CASCADE,
    category    TEXT,           -- 쟁점 | 상황 | 감정 | 유불리
    tag         TEXT NOT NULL,
    score       REAL,
    engine      TEXT,           -- keyword | local | gemini
    matched     TEXT,           -- 실제로 걸린 표현
    UNIQUE(segment_id, category, tag, engine)
);
CREATE INDEX IF NOT EXISTS idx_tags_seg ON tags(segment_id);
CREATE INDEX IF NOT EXISTS idx_tags_tag ON tags(tag);

CREATE TABLE IF NOT EXISTS notes (
    segment_id       INTEGER PRIMARY KEY REFERENCES segments(id) ON DELETE CASCADE,
    issue_id         INTEGER REFERENCES issues(id),
    verdict          TEXT,      -- 유리 | 불리 | 중립
    memo             TEXT,
    verified_by_ear  INTEGER DEFAULT 0,   -- 원본을 실제로 들어 확인했는가
    verified_at      TEXT,
    corrected_text   TEXT       -- 들어보고 고친 전사문
);

-- ───────────────────────────────────────── 발췌 장바구니 · 클립
CREATE TABLE IF NOT EXISTS basket (
    id              INTEGER PRIMARY KEY,
    segment_id      INTEGER NOT NULL REFERENCES segments(id) ON DELETE CASCADE,
    source_id       INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    clip_start_sec  REAL,
    clip_end_sec    REAL,
    order_no        INTEGER,
    reason          TEXT,        -- 이 구간을 제출하는 이유
    created_at      TEXT,
    UNIQUE(segment_id)
);

CREATE TABLE IF NOT EXISTS clips (
    id              INTEGER PRIMARY KEY,
    basket_id       INTEGER REFERENCES basket(id) ON DELETE SET NULL,
    out_path        TEXT NOT NULL,
    sha256          TEXT,
    bytes           INTEGER,
    duration_sec    REAL,
    extract_mode    TEXT,        -- pcm(정밀) | copy(스트림복사)
    orig_path       TEXT,
    orig_sha256     TEXT,
    orig_start_sec  REAL,
    orig_end_sec    REAL,
    exported_at     TEXT
);

-- ───────────────────────────────────────── 법률 계층
CREATE TABLE IF NOT EXISTS law_articles (
    id             INTEGER PRIMARY KEY,
    law_name       TEXT NOT NULL,
    law_id         TEXT,
    article_no     TEXT NOT NULL,      -- '제25조' / '제25조제1항'
    article_title  TEXT,
    body           TEXT NOT NULL,
    enforce_date   TEXT,
    source_url     TEXT,
    fetched_at     TEXT,
    UNIQUE(law_name, article_no)
);

CREATE TABLE IF NOT EXISTS precedents (
    id           INTEGER PRIMARY KEY,
    case_no      TEXT NOT NULL UNIQUE,   -- '2011다109357'
    court        TEXT,
    decided_on   TEXT,
    case_name    TEXT,
    holding      TEXT,                   -- 판시사항
    summary      TEXT,                   -- 판결요지
    body         TEXT,
    source_url   TEXT,
    fetched_at   TEXT
);

CREATE VIRTUAL TABLE IF NOT EXISTS law_fts
    USING fts5(body, ref_type UNINDEXED, ref_id UNINDEXED, tokenize='trigram');

CREATE TABLE IF NOT EXISTS comments (
    id               INTEGER PRIMARY KEY,
    segment_id       INTEGER REFERENCES segments(id) ON DELETE CASCADE,
    issue_id         INTEGER REFERENCES issues(id),
    issue_name       TEXT,
    stance           TEXT,       -- 유리 | 불리 | 중립
    reasoning        TEXT,
    citation_status  TEXT DEFAULT 'pending',   -- verified | blocked | pending
    block_reason     TEXT,
    engine           TEXT,
    created_at       TEXT
);

CREATE TABLE IF NOT EXISTS comment_citations (
    id           INTEGER PRIMARY KEY,
    comment_id   INTEGER NOT NULL REFERENCES comments(id) ON DELETE CASCADE,
    ref_type     TEXT NOT NULL,       -- article | precedent
    ref_id       INTEGER NOT NULL,
    verified_at  TEXT,
    verified_ok  INTEGER DEFAULT 0,
    source_url   TEXT
);

-- ───────────────────────────────────────── 메타
CREATE TABLE IF NOT EXISTS meta (
    key    TEXT PRIMARY KEY,
    value  TEXT
);
"""


# ─────────────────────────────────────────────────────────
# 연결
# ─────────────────────────────────────────────────────────
# Streamlit은 화면을 다시 그릴 때마다 새 스레드에서 스크립트를 실행한다.
# 연결 하나를 캐시해 재사용하려면 스레드 검사를 꺼야 하고, 대신 쓰기를
# 직렬화해 동시 기록이 겹치지 않게 한다.
_write_lock = threading.RLock()


def connect(path=None) -> sqlite3.Connection:
    conn = sqlite3.connect(
        path or config.DB_PATH,
        timeout=30,
        check_same_thread=False,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def write(conn, sql, args=()):
    """쓰기 한 건. 스레드 간 충돌을 막기 위해 잠금 안에서 실행한다."""
    with _write_lock:
        cur = conn.execute(sql, args)
        conn.commit()
        return cur


def write_many(conn, sql, rows):
    with _write_lock:
        conn.executemany(sql, rows)
        conn.commit()


def init(path=None) -> sqlite3.Connection:
    """스키마 생성. 이미 있으면 그대로 둔다."""
    conn = connect(path)
    conn.executescript(_SCHEMA)
    conn.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES('schema_version', ?)",
        (str(SCHEMA_VERSION),),
    )
    conn.commit()
    _init_vec(conn)
    return conn


def _init_vec(conn) -> bool:
    """
    sqlite-vec 확장을 붙인다. 없으면 의미 검색만 비활성화되고
    키워드 검색은 정상 동작한다.
    """
    try:
        import sqlite_vec
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        conn.execute(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS vec_segments USING vec0("
            f"segment_id INTEGER PRIMARY KEY, embedding FLOAT[{config.EMBED_DIM}])"
        )
        conn.execute(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS vec_law USING vec0("
            f"rowid INTEGER PRIMARY KEY, embedding FLOAT[{config.EMBED_DIM}])"
        )
        conn.commit()
        return True
    except BaseException:
        return False


def vec_available(conn) -> bool:
    try:
        conn.execute("SELECT count(*) FROM vec_segments").fetchone()
        return True
    except sqlite3.Error:
        return _init_vec(conn)


# ─────────────────────────────────────────────────────────
# 원본 등록
# ─────────────────────────────────────────────────────────
def add_source(conn, fp: dict, kind: str, **extra) -> tuple[int, bool]:
    """
    원본을 등록한다. 돌려주는 값: (source_id, 새로 추가되었는가)

    같은 해시가 이미 있으면 같은 파일이므로 등록하지 않는다
    (같은 녹음을 여러 폴더에 복사해둔 경우가 흔하다).
    """
    with _write_lock:
        dup = conn.execute(
            "SELECT id FROM sources WHERE sha256 = ?", (fp["sha256"],)
        ).fetchone()
        if dup:
            return dup["id"], False

        cur = conn.execute(
            """INSERT INTO sources
               (path, sha256, kind, bytes, mtime, duration_sec,
                is_my_conversation, counterparty, occurred_at, occurred_at_est,
                memo, ingested_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (fp["path"], fp["sha256"], kind, fp["bytes"], fp["mtime"],
             extra.get("duration_sec"),
             extra.get("is_my_conversation", "UNKNOWN"),
             extra.get("counterparty"),
             extra.get("occurred_at"),
             1 if extra.get("occurred_at_est") else 0,
             extra.get("memo"),
             datetime.now().isoformat(timespec="seconds")),
        )
        conn.commit()
        return cur.lastrowid, True


def set_status(conn, source_id: int, status: str, detail: str = None) -> None:
    write(conn, "UPDATE sources SET status = ?, status_detail = ? WHERE id = ?",
          (status, detail, source_id))


def clear_segments(conn, source_id: int) -> None:
    """재처리 전 기존 구간을 지운다."""
    write(conn, "DELETE FROM segments WHERE source_id = ?", (source_id,))


def add_segments(conn, source_id: int, rows: list[dict]) -> int:
    """구간 일괄 저장."""
    if not rows:
        return 0
    write_many(
        conn,
        """INSERT INTO segments
           (source_id, seq, text, speaker, speaker_label, speaker_uncertain,
            start_sec, end_sec,
            page_no, occurred_at, words_json,
            avg_logprob, no_speech_prob, compression_ratio, confidence,
            alt_text, alt_mismatch, mismatch_kind, hallucination_risk)
           VALUES (:source_id,:seq,:text,:speaker,:speaker_label,:speaker_uncertain,
                   :start_sec,:end_sec,
                   :page_no,:occurred_at,:words_json,
                   :avg_logprob,:no_speech_prob,:compression_ratio,:confidence,
                   :alt_text,:alt_mismatch,:mismatch_kind,:hallucination_risk)""",
        [{**_SEG_DEFAULTS, "source_id": source_id, **r} for r in rows],
    )
    return len(rows)


_SEG_DEFAULTS = {
    "seq": 0, "text": "", "speaker": None, "speaker_label": None,
    "speaker_uncertain": 0,
    "start_sec": None, "end_sec": None, "page_no": None, "occurred_at": None,
    "words_json": None, "avg_logprob": None, "no_speech_prob": None,
    "compression_ratio": None, "confidence": None, "alt_text": None,
    "alt_mismatch": 0, "mismatch_kind": None, "hallucination_risk": 0,
}


# ─────────────────────────────────────────────────────────
# 통계
# ─────────────────────────────────────────────────────────
def stats(conn) -> dict:
    def one(sql, *a):
        r = conn.execute(sql, a).fetchone()
        return r[0] if r else 0

    return {
        "sources": one("SELECT count(*) FROM sources"),
        "audio": one("SELECT count(*) FROM sources WHERE kind='audio'"),
        "segments": one("SELECT count(*) FROM segments"),
        "extracted": one("SELECT count(*) FROM sources WHERE status IN ('extracted','verified')"),
        "pending": one("SELECT count(*) FROM sources WHERE status='registered'"),
        "low_conf": one("SELECT count(*) FROM segments WHERE confidence IS NOT NULL AND confidence < 0.6"),
        "mismatch": one("SELECT count(*) FROM segments WHERE alt_mismatch = 1"),
        # 한 구간이 '전사 불일치'이면서 동시에 '신뢰도 낮음'인 경우가 흔하다.
        # 두 값을 더하면 그런 구간을 두 번 세어, 확인 필요 건수가 전체 구간
        # 수보다 커지는 일이 생긴다(실제로 1,486 > 1,443 이 화면에 떴다).
        # 숫자가 안 맞으면 나머지 숫자도 못 믿게 되므로 한 번만 센다.
        "needs_check": one(
            "SELECT count(*) FROM segments "
            "WHERE alt_mismatch = 1 "
            "   OR (confidence IS NOT NULL AND confidence < 0.6)"),
        "verified_ear": one("SELECT count(*) FROM notes WHERE verified_by_ear = 1"),
        "basket": one("SELECT count(*) FROM basket"),
        "tags": one("SELECT count(*) FROM tags"),
        "illegal": one("SELECT count(*) FROM sources WHERE is_my_conversation='N'"),
        "unknown_legal": one("SELECT count(*) FROM sources WHERE kind='audio' AND is_my_conversation='UNKNOWN'"),
    }
