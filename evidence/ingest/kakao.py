# -*- coding: utf-8 -*-
"""
카카오톡 대화 내보내기 파서.

주의해야 할 함정 두 가지
  1) 분할 저장
     카카오톡은 대화가 길면 파일을 1MB 단위로 쪼개 저장한다.
     (KakaoTalk_Chats.txt, KakaoTalk_Chats_2.txt ...)
     이걸 모르고 첫 파일만 읽으면 대화가 중간에 잘린 채 분석된다.
     소송 자료에서는 치명적이므로 뒷부분을 자동으로 찾아 잇는다.

  2) 양식이 두 가지
     PC판   :  [홍길동] [오후 2:43] 메시지
     모바일 :  2025년 3월 14일 오후 2:43, 홍길동 : 메시지
     둘 다 지원하고, PC판은 날짜 헤더줄로 연월일 상태를 이어간다.

여러 줄 메시지(줄바꿈이 들어간 메시지)는 다음 줄이 새 메시지 형식이
아니면 앞 메시지에 이어 붙인다.
"""
import re
from datetime import datetime
from pathlib import Path

# ── PC판 ─────────────────────────────────────────────
# --------------- 2025년 3월 14일 금요일 ---------------
_PC_DATE = re.compile(r"^-+\s*(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일.*?-+\s*$")
# [홍길동] [오후 2:43] 메시지
_PC_MSG = re.compile(r"^\[(?P<who>.+?)\]\s*\[(?P<ampm>오전|오후)\s*(?P<h>\d{1,2}):(?P<m>\d{2})\]\s*(?P<text>.*)$")

# ── 모바일판 ─────────────────────────────────────────
# 2025년 3월 14일 오후 2:43, 홍길동 : 메시지
_MO_MSG = re.compile(
    r"^(?P<y>\d{4})년\s*(?P<mo>\d{1,2})월\s*(?P<d>\d{1,2})일\s*"
    r"(?P<ampm>오전|오후)\s*(?P<h>\d{1,2}):(?P<mi>\d{2}),\s*"
    r"(?P<who>.+?)\s*:\s*(?P<text>.*)$"
)
# 2025년 3월 14일 오후 2:43
_MO_DATE_ONLY = re.compile(r"^(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일\s*(오전|오후)?")

# 대화방 머리말
_HEADER = re.compile(r"(님과 카카오톡 대화|저장한 날짜|카카오톡 대화)")

# 시스템 메시지 (증거 가치가 없어 태그만 달아 구분)
_SYSTEM = re.compile(r"(님이 (들어왔습니다|나갔습니다)|채팅방 관리자|삭제된 메시지입니다)")


def _to24(ampm: str, hour: int) -> int:
    """오전/오후 12시간제를 24시간제로."""
    h = hour % 12
    return h + 12 if ampm == "오후" else h


def find_split_files(path) -> list[Path]:
    """
    분할 저장된 뒷부분 파일을 찾아 순서대로 돌려준다.

    KakaoTalk_Chats.txt → KakaoTalk_Chats_2.txt, _3.txt ...
    대화_20250314.txt   → 대화_20250314_2.txt ...
    """
    p = Path(path)
    stem, suffix, folder = p.stem, p.suffix, p.parent

    # 이미 뒷조각이면(끝이 _숫자) 첫 조각만 대표로 처리하도록 자기 자신만 반환
    if re.search(r"_\d+$", stem):
        return [p]

    parts = [p]
    n = 2
    while True:
        nxt = folder / f"{stem}_{n}{suffix}"
        if not nxt.exists():
            break
        parts.append(nxt)
        n += 1
    return parts


def _read(path) -> str:
    """카카오톡은 UTF-8(BOM 포함)로 내보낸다. 구버전 대비 cp949도 시도."""
    p = Path(path)
    for enc in ("utf-8-sig", "utf-8", "cp949"):
        try:
            return p.read_text(encoding=enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return p.read_text(encoding="utf-8", errors="ignore")


def parse(path) -> list[dict]:
    """
    카톡 내보내기를 메시지 목록으로 변환한다.

    각 메시지: {seq, speaker, text, occurred_at, is_system}
    분할 파일이 있으면 자동으로 이어 붙인다.
    """
    files = find_split_files(path)
    messages = []
    cur_date = None          # PC판에서 날짜 헤더로 갱신
    last = None              # 여러 줄 메시지 이어붙이기 대상

    for fp in files:
        for raw in _read(fp).splitlines():
            line = raw.rstrip("\n")

            if not line.strip():
                # 빈 줄도 여러 줄 메시지의 일부일 수 있다
                if last is not None:
                    last["text"] += "\n"
                continue

            if _HEADER.search(line) and len(line) < 80:
                last = None
                continue

            m = _PC_DATE.match(line)
            if m:
                cur_date = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
                last = None
                continue

            m = _MO_MSG.match(line)
            if m:
                dt = datetime(
                    int(m.group("y")), int(m.group("mo")), int(m.group("d")),
                    _to24(m.group("ampm"), int(m.group("h"))), int(m.group("mi")),
                )
                last = {
                    "speaker": m.group("who").strip(),
                    "text": m.group("text"),
                    "occurred_at": dt.isoformat(timespec="minutes"),
                }
                messages.append(last)
                continue

            m = _PC_MSG.match(line)
            if m:
                occurred = None
                if cur_date:
                    dt = datetime(
                        cur_date[0], cur_date[1], cur_date[2],
                        _to24(m.group("ampm"), int(m.group("h"))), int(m.group("m")),
                    )
                    occurred = dt.isoformat(timespec="minutes")
                last = {
                    "speaker": m.group("who").strip(),
                    "text": m.group("text"),
                    "occurred_at": occurred,
                }
                messages.append(last)
                continue

            # 날짜만 있는 줄 (모바일판 구분선)
            if _MO_DATE_ONLY.match(line) and len(line) < 40:
                last = None
                continue

            # 위 어디에도 안 맞으면 직전 메시지의 이어지는 줄
            if last is not None:
                last["text"] += "\n" + line

    # 정리: 번호 부여, 시스템 메시지 표시, 빈 메시지 제거
    out = []
    for i, msg in enumerate(m for m in messages if m["text"].strip()):
        msg["seq"] = i + 1
        msg["is_system"] = bool(_SYSTEM.search(msg["text"]))
        msg["text"] = msg["text"].strip()
        out.append(msg)
    return out


def participants(messages: list[dict]) -> list[str]:
    """대화 참여자 목록 (등장 횟수 순)."""
    from collections import Counter
    c = Counter(m["speaker"] for m in messages if not m.get("is_system"))
    return [name for name, _ in c.most_common()]


def to_segments(messages: list[dict]) -> list[dict]:
    """DB의 segments 행 형태로 변환한다."""
    return [
        {
            "seq": m["seq"],
            "text": m["text"],
            "speaker": m["speaker"],
            "speaker_label": m["speaker"],   # 카톡은 발신자 이름이 이미 확실하다
            "occurred_at": m.get("occurred_at"),
            "confidence": 1.0,               # 문자 기록이므로 전사 오류가 없다
        }
        for m in messages
    ]


def extract(conn, source_row) -> int:
    """원본 하나를 파싱해 DB에 넣는다. 돌려주는 값: 저장한 메시지 수."""
    from .. import db, integrity

    msgs = parse(source_row["path"])
    segs = to_segments(msgs)
    db.clear_segments(conn, source_row["id"])
    n = db.add_segments(conn, source_row["id"], segs)

    # 대화 기간을 원본의 발생 일시로 되돌려 기록 (타임라인 정확도 향상)
    dated = [m["occurred_at"] for m in msgs if m.get("occurred_at")]
    if dated:
        db.write(conn,
                 "UPDATE sources SET occurred_at = ?, occurred_at_est = 0 WHERE id = ?",
                 (min(dated), source_row["id"]))

    parts = participants(msgs)
    db.set_status(conn, source_row["id"], "extracted",
                  f"메시지 {n}건 · 참여자 {', '.join(parts[:4])}")
    integrity.log("extract_kakao", source_id=source_row["id"], messages=n,
                  files=len(find_split_files(source_row["path"])),
                  participants=parts)
    return n
