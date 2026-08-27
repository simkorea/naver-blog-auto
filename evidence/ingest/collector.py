# -*- coding: utf-8 -*-
"""
자료 모으기 — 흩어진 파일을 이름·전화번호로 찾아 한곳에 복사한다.

왜 필요한가
  통화 녹음은 보통 한 폴더에 얌전히 모여 있지 않다. 폰에서 옮긴 것,
  카톡으로 받은 것, 메일에 붙어 온 것이 다운로드 폴더 여기저기에 흩어진다.
  수백 개 중에서 그 사람 것만 손으로 골라내는 것은 몇 시간짜리 일이고,
  **빠뜨리기 쉽다.** 소송에서 결정적인 녹음 하나를 못 찾으면 그것으로 끝이다.

  다행히 통화 녹음은 파일명에 상대방이 남는다:

      010-1234-5678_20240320_143022.m4a
      통화 녹음 홍길동_240320.m4a
      녹음(01012345678).amr

  그래서 이름이나 번호로 훑어서 모아준다.

절대 지키는 것
  **복사만 한다. 원본을 옮기거나 지우거나 이름을 바꾸지 않는다.**
  원본이 있던 자리에 그대로 있어야 나중에 "이 파일이 원래 어디 있었다"를
  말할 수 있다. 복사한 뒤에는 해시를 다시 재서 제대로 복사됐는지 확인한다.
"""
import re
import shutil
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path

from .. import config, integrity
from .scanner import MIN_BYTES, SKIP_DIRS, SKIP_NAMES

# 한 번에 너무 많이 훑다가 화면이 멈춘 것처럼 보이지 않게 상한을 둔다.
MAX_SCAN = 200_000


def phone_folder_hint(path) -> str | None:
    """
    휴대폰을 USB 로 꽂았을 때 보이는 경로인지 알아보고, 맞으면 안내를 돌려준다.

    왜 필요한가
      폰을 꽂으면 탐색기에 이렇게 보인다:

          내 PC\\한의 Z Flip5\\내장 저장공간\\Call

      사람 눈에는 폴더처럼 보이지만 **진짜 폴더가 아니다.** 윈도우가
      탐색기 안에서만 보여주는 가상 경로(MTP)라서 프로그램은 열 수 없다.
      드라이브 문자(`C:`)가 없는 것이 그 표시다.

      그냥 "폴더를 찾을 수 없습니다"라고만 하면 사용자는 경로를 잘못 썼나
      싶어 계속 고쳐 넣게 된다. 실제로 그 일이 있었다. 무엇을 해야 하는지
      정확히 알려준다.
    """
    s = str(path).strip().strip('"')
    if not s:
        return None
    # 드라이브 문자(C:\)나 네트워크 경로(\\서버\)로 시작하면 진짜 경로다
    if re.match(r"^[A-Za-z]:[\\/]", s) or s.startswith("\\\\") or s.startswith("/"):
        return None
    lowered = s.lower()
    markers = ("내 pc", "this pc", "내장 저장공간", "internal storage",
               "phone", "sd card", "휴대전화", "갤럭시", "galaxy")
    if not any(m in lowered for m in markers):
        return None
    return (
        "휴대폰을 USB로 연결했을 때 보이는 경로 같습니다. "
        "이런 경로는 윈도우 탐색기 안에서만 보이는 가상 경로라 프로그램이 열 수 없습니다.\n\n"
        "**먼저 PC로 복사해 주세요.** 탐색기에서 그 폴더(예: `Call`)를 통째로 "
        "바탕화면에 끌어다 놓으신 뒤, 여기에는 복사된 위치"
        "(예: `C:\\\\Users\\\\사용자\\\\Desktop\\\\Call`)를 넣으시면 됩니다."
    )


def normalize_phone(text: str) -> str:
    """전화번호에서 숫자만 남긴다. 010-1234-5678 → 01012345678"""
    return re.sub(r"\D", "", text or "")


def _looks_like_phone(term: str) -> bool:
    """전화번호로 볼 만한가. 숫자가 7자리 이상이면 번호로 본다."""
    return len(normalize_phone(term)) >= 7


def _fold(text: str) -> str:
    """
    비교하기 좋게 다듬는다.

    윈도우 파일명은 한글 자모가 분리된 형태(NFD)로 저장되는 경우가 있어
    눈에는 같아 보여도 글자로는 다르다. 정규화하지 않으면 '홍길동'을
    검색해도 못 찾는다. 공백과 대소문자도 무시한다.
    """
    t = unicodedata.normalize("NFC", text or "")
    return re.sub(r"\s+", "", t).lower()


def match_terms(name: str, terms: list[str]) -> list[str]:
    """
    파일명(또는 경로)이 어떤 검색어에 걸리는지 돌려준다.

    전화번호는 숫자만 뽑아서 비교한다 — 파일명에 `010-1234-5678` 로 있든
    `01012345678` 로 있든 `010 1234 5678` 로 있든 같은 번호로 본다.
    이름은 공백을 무시하고 부분 일치로 본다.
    """
    hits = []
    folded = _fold(name)
    digits = normalize_phone(name)
    for term in terms:
        term = (term or "").strip()
        if not term:
            continue
        if _looks_like_phone(term):
            if normalize_phone(term) in digits:
                hits.append(term)
        elif _fold(term) in folded:
            hits.append(term)
    return hits


def find(roots, terms: list[str], kinds: list[str] = None,
         days: int = None, include_folder_name: bool = True,
         progress=None) -> dict:
    """
    폴더들을 훑어 검색어에 걸리는 파일을 찾는다. **복사하지 않는다.**

    먼저 무엇이 걸렸는지 보여주고, 사용자가 확인한 뒤에 복사한다.
    엉뚱한 파일이 딸려 오는 것을 눈으로 걸러야 하기 때문이다.

    roots  : 훑을 폴더들
    terms  : 이름 또는 전화번호 목록
    kinds  : config.KIND_* 목록. None 이면 전부
    days   : 최근 N일 안에 만들어진 것만. None 이면 전부
    include_folder_name : 폴더 이름에 걸려도 인정할지
        (`홍길동 통화녹음/` 폴더 안의 `20240320.m4a` 같은 경우)
    """
    terms = [t for t in (terms or []) if (t or "").strip()]
    if not terms:
        return {"hits": [], "scanned": 0, "errors": [], "stopped": False}

    cutoff = None
    if days:
        cutoff = datetime.now() - timedelta(days=int(days))

    hits, errors = [], []
    seen = set()
    scanned = 0
    stopped = False

    for root in roots:
        hint = phone_folder_hint(root)
        if hint:
            errors.append(f"**{root}**\n\n{hint}")
            continue
        root = Path(root).expanduser()
        if not root.exists():
            errors.append(f"폴더를 찾을 수 없습니다: {root}")
            continue
        for p in root.rglob("*"):
            if scanned >= MAX_SCAN:
                stopped = True
                break
            if any(part in SKIP_DIRS for part in p.parts):
                continue
            try:
                if not p.is_file() or p.name in SKIP_NAMES or p.name.startswith("~$"):
                    continue
                st = p.stat()
                if st.st_size < MIN_BYTES:
                    continue
            except OSError:
                continue
            scanned += 1
            if progress and scanned % 500 == 0:
                progress(scanned, len(hits))

            kind = config.classify(p)
            if kind is None or (kinds and kind not in kinds):
                continue
            if cutoff and datetime.fromtimestamp(st.st_mtime) < cutoff:
                continue

            haystack = p.name if not include_folder_name else str(p)
            matched = match_terms(haystack, terms)
            if not matched:
                continue

            try:
                real = p.resolve()
            except OSError:
                real = p
            if real in seen:
                continue          # 바로가기 등으로 같은 파일이 두 번 걸린 경우
            seen.add(real)

            hits.append({
                "path": str(p),
                "name": p.name,
                "kind": kind,
                "size": st.st_size,
                "mtime": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M"),
                "matched": matched,
                # 파일명이 아니라 폴더명에 걸린 것은 따로 표시한다 —
                # 딸려 온 것일 수 있으니 사용자가 한 번 더 봐야 한다.
                "by_folder": not match_terms(p.name, terms),
            })
        if stopped:
            break

    hits.sort(key=lambda h: h["mtime"], reverse=True)
    return {"hits": hits, "scanned": scanned, "errors": errors, "stopped": stopped}


def _unique_name(dest: Path, name: str) -> Path:
    """
    같은 이름이 이미 있으면 뒤에 번호를 붙인다.

    덮어쓰면 안 된다. 다른 폴더에 같은 이름의 다른 녹음이 있는 것은
    흔한 일이고(`통화 녹음.m4a`), 그걸 덮으면 증거가 사라진다.
    """
    out = dest / name
    if not out.exists():
        return out
    stem, suffix = Path(name).stem, Path(name).suffix
    for i in range(2, 10000):
        cand = dest / f"{stem} ({i}){suffix}"
        if not cand.exists():
            return cand
    raise RuntimeError(f"이름이 겹쳐 저장할 수 없습니다: {name}")


def collect(hits: list[dict], dest) -> dict:
    """
    찾은 파일을 저장 폴더로 **복사**한다.

    돌려주는 값
      copied     복사한 것
      duplicate  이미 같은 내용이 있어 건너뛴 것 (해시로 판단)
      failed     복사하지 못한 것과 그 이유
    """
    dest = Path(dest).expanduser()
    dest.mkdir(parents=True, exist_ok=True)

    # 저장 폴더에 이미 들어 있는 것들의 해시. 같은 파일을 두 번 담지 않는다.
    existing = {}
    for p in dest.rglob("*"):
        if p.is_file():
            try:
                existing[integrity.sha256_file(p)] = p.name
            except OSError:
                continue

    copied, duplicate, failed = [], [], []
    for h in hits:
        src = Path(h["path"])
        try:
            digest = integrity.sha256_file(src)
        except OSError as e:
            failed.append({"path": str(src), "reason": f"읽을 수 없음 ({e.strerror or e})"})
            continue

        if digest in existing:
            duplicate.append({"path": str(src), "same_as": existing[digest]})
            continue

        try:
            out = _unique_name(dest, src.name)
            # 원본을 건드리지 않는지 한 번 더 확인한다.
            integrity.guard_not_original(out)
            shutil.copy2(src, out)
            # 복사가 온전한지 해시로 확인한다. 크기만 보면 놓치는 경우가 있다.
            if integrity.sha256_file(out) != digest:
                out.unlink(missing_ok=True)
                failed.append({"path": str(src), "reason": "복사본이 원본과 다릅니다"})
                continue
        except BaseException as e:
            failed.append({"path": str(src), "reason": f"{type(e).__name__}: {e}"})
            continue

        existing[digest] = out.name
        copied.append({"path": str(src), "saved_as": out.name, "size": h.get("size", 0)})

    return {"copied": copied, "duplicate": duplicate, "failed": failed,
            "dest": str(dest)}


def default_roots() -> list[Path]:
    """흔히 자료가 있는 곳. 사용자가 고르기 전 기본값으로 보여준다."""
    home = Path.home()
    names = ["Downloads", "Desktop", "Documents", "다운로드", "바탕 화면", "문서"]
    out = []
    for n in names:
        p = home / n
        if p.exists() and p not in out:
            out.append(p)
    return out
