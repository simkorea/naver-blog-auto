"""
zip_importer.py - 카드뉴스 ZIP을 posts/ 폴더 구조로 자동 변환

카드뉴스 생성기가 만든 ZIP은 아래 구조를 가집니다:

    20260816_....zip
    ├── 20260816_....txt      ← [제목]/[메타설명]/[태그]/[본문] 섹션 원고
    ├── 1_image_1.jpg         ← 앞 숫자가 표시 순서
    ├── 2_image_2.jpg
    └── ...

이 모듈은 위 ZIP을 읽어 step2_upload.py 가 바로 쓸 수 있는 형태로 바꿉니다:

    posts/YYYY-MM-DD/글제목/
    ├── content.txt           ← 첫 문단 = 제목, 이후 본문
    ├── tags.txt              ← 네이버 태그 입력란에 넣을 태그 목록
    ├── image_order.txt       ← 이미지 표시 순서
    └── 1.jpg ~ N.jpg

사용법:
    from zip_importer import import_cardnews_zip
    folder = import_cardnews_zip("경로/파일.zip")
"""
import datetime
import re
import zipfile
from pathlib import Path

POSTS_DIR = Path("posts")

_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}

# 소제목 판별 기준 - 이 길이 이하이고 마침표가 없으면 소제목으로 봅니다.
_HEADING_MAX_LEN = 45


# ── 원고 텍스트 파싱 ─────────────────────────────────────────────────────────

def _extract_section(name: str, text: str) -> str:
    """[섹션명] 마커 다음부터 그 다음 [ 마커 전까지를 잘라냅니다."""
    marker = f"[{name}]"
    start = text.find(marker)
    if start == -1:
        return ""
    start += len(marker)
    next_idx = text.find("[", start)
    return (text[start:] if next_idx == -1 else text[start:next_idx]).strip()


def _is_heading(para: str) -> bool:
    """소제목으로 보이는 문단인지 판별합니다.

    카드뉴스 원고는 '소제목 / 빈 줄 / 본문' 구조라서, 그대로 두면 소제목과 본문이
    서로 다른 블록이 되어 이미지가 소제목 바로 뒤에 끼어듭니다.
    짧고 마침표가 없는 줄을 소제목으로 보고 뒤 문단과 합칩니다.
    """
    if not para or para.startswith("#"):
        return False
    if "\n" in para:
        return False
    return len(para) <= _HEADING_MAX_LEN and "." not in para


def _merge_headings(paragraphs: list[str]) -> list[str]:
    """소제목 문단을 바로 뒤 본문 문단과 한 블록으로 합칩니다."""
    merged: list[str] = []
    i = 0
    while i < len(paragraphs):
        cur = paragraphs[i]
        if _is_heading(cur) and i + 1 < len(paragraphs):
            merged.append(f"{cur}\n{paragraphs[i + 1]}")
            i += 2
        else:
            merged.append(cur)
            i += 1
    return merged


def parse_manuscript(text: str) -> tuple[str, str, str]:
    """원고 텍스트에서 (제목, 본문, 태그) 를 추출합니다.

    [제목]/[본문]/[태그] 섹션이 없는 평문이면 첫 줄을 제목으로 씁니다.
    """
    title = _extract_section("제목", text)
    body  = _extract_section("본문", text)
    tags  = _extract_section("태그", text)

    if not title or not body:
        # 섹션 마커가 없는 평문 폴백
        blocks = [b.strip() for b in text.split("\n\n") if b.strip()]
        if not blocks:
            return "", "", ""
        title = title or blocks[0]
        body  = body or "\n\n".join(blocks[1:])

    # 제목은 첫 줄만 사용 - 일부 원고에 '(29자)' 같은 메모가 다음 줄에 붙어 있음
    title = next((ln.strip() for ln in title.splitlines() if ln.strip()), "")
    title = re.sub(r"\s*\(\d+자\)\s*$", "", title).strip()

    paragraphs = [p.strip() for p in body.split("\n\n") if p.strip()]
    body = "\n\n".join(_merge_headings(paragraphs))
    return title.strip(), body.strip(), tags.strip()


def normalize_tags(raw: str) -> list[str]:
    """'#부동산, #재테크' 또는 '부동산 재테크' -> ['부동산', '재테크']"""
    if not raw:
        return []
    parts = re.split(r"[,\s]+", raw)
    return [p.lstrip("#").strip() for p in parts if p.lstrip("#").strip()]


# ── 이미지 순서 ──────────────────────────────────────────────────────────────

def _image_sort_key(name: str) -> tuple:
    """'10_image_10.jpg' -> 앞 숫자 10 기준 정렬. 숫자가 없으면 이름순."""
    m = re.match(r"^(\d+)", name)
    return (0, int(m.group(1))) if m else (1, name.lower())


# ── 메인 ─────────────────────────────────────────────────────────────────────

def import_cardnews_zip(
    zip_path: str | Path,
    posts_dir: str | Path = POSTS_DIR,
    date: str = "",
    folder_name: str = "",
) -> Path:
    """카드뉴스 ZIP을 posts/ 아래 포스트 폴더로 변환하고 그 경로를 반환합니다.

    date        : 'YYYY-MM-DD'. 비우면 ZIP 파일명 앞 8자리(YYYYMMDD) -> 없으면 오늘.
    folder_name : 포스트 폴더명. 비우면 원고 제목에서 자동 생성.
    """
    zip_path  = Path(zip_path)
    posts_dir = Path(posts_dir)

    if not zip_path.exists():
        raise FileNotFoundError(f"ZIP 파일이 없습니다: {zip_path}")

    with zipfile.ZipFile(zip_path) as zf:
        names = [n for n in zf.namelist() if not n.endswith("/")]

        txt_names = [n for n in names if n.lower().endswith(".txt")]
        if not txt_names:
            raise ValueError("ZIP 안에 원고 .txt 파일이 없습니다.")
        raw_text = zf.read(txt_names[0]).decode("utf-8", errors="replace")

        title, body, tags_raw = parse_manuscript(raw_text)
        if not title or not body:
            raise ValueError("원고에서 제목 또는 본문을 찾지 못했습니다.")

        # 날짜 결정: 인자 -> 파일명 앞 8자리 -> 오늘
        if not date:
            m = re.match(r"^(\d{4})(\d{2})(\d{2})", zip_path.stem)
            date = (f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m
                    else datetime.date.today().isoformat())

        # 폴더명 결정 (경로에 못 쓰는 문자 제거)
        if not folder_name:
            from supabase_db import sanitize_path_component
            folder_name = sanitize_path_component(re.sub(r"[:*?\"<>|]", "", title)[:40])

        dest = posts_dir / date / folder_name
        dest.mkdir(parents=True, exist_ok=True)

        # 원고 저장 - step2_upload 는 첫 문단을 제목으로 씁니다.
        (dest / "content.txt").write_text(f"{title}\n\n{body}\n", encoding="utf-8")

        tags = normalize_tags(tags_raw)
        if tags:
            (dest / "tags.txt").write_text("\n".join(tags), encoding="utf-8")

        # 이미지 추출 - 표시 순서대로 1.jpg ~ N.jpg 로 재명명
        img_names = sorted(
            (n for n in names if Path(n).suffix.lower() in _IMAGE_EXTS),
            key=lambda n: _image_sort_key(Path(n).name),
        )
        saved: list[str] = []
        for idx, name in enumerate(img_names, 1):
            out_name = f"{idx}{Path(name).suffix.lower()}"
            (dest / out_name).write_bytes(zf.read(name))
            saved.append(out_name)

        if saved:
            (dest / "image_order.txt").write_text("\n".join(saved), encoding="utf-8")

    return dest


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("사용법: python zip_importer.py <ZIP파일경로>")
        sys.exit(1)

    folder = import_cardnews_zip(sys.argv[1])
    content = (folder / "content.txt").read_text(encoding="utf-8")
    paras   = [p for p in content.split("\n\n") if p.strip()]
    imgs    = [p for p in folder.iterdir() if p.suffix.lower() in _IMAGE_EXTS]
    print(f"[완료] {folder}")
    print(f"  문단 {len(paras) - 1}개 (제목 제외)  |  이미지 {len(imgs)}장")
