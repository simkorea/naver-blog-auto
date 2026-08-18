"""
publish.py - 발행 가능한 글을 목록으로 보여주고 골라서 업로드

카드뉴스 ZIP 폴더와 posts/ 폴더를 한꺼번에 훑어 최신순으로 보여줍니다.
ZIP을 고르면 자동으로 임포트한 뒤 업로드까지 이어집니다.

사용법:
    python publish.py            목록 표시 후 번호 입력받아 업로드
    python publish.py --list     목록만 표시 (업로드 안 함)
    python publish.py 3          3번 항목을 바로 업로드
    python publish.py 3 --import-only     3번을 임포트만 하고 업로드는 안 함
    python publish.py 3 --cta "상담문의"   CTA 프리셋을 이름으로 지정

카드뉴스 ZIP 폴더는 .env 의 CARDNEWS_BLOG_DIR 로 바꿀 수 있습니다.
"""
import json
import os
import sys
import zipfile
from pathlib import Path

from dotenv import load_dotenv

# 한글 출력이 콘솔 인코딩 때문에 깨지지 않도록 (직접 실행할 때만 - import 시에는 건드리지 않음)
if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

load_dotenv()

POSTS_DIR = Path("posts")
DEFAULT_CARDNEWS_DIR = r"D:\다운로드\ai등 공부 자료 및 잡동\카드뉴스 신규\블로그"
CARDNEWS_DIR = Path(os.getenv("CARDNEWS_BLOG_DIR", DEFAULT_CARDNEWS_DIR))

_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
_SHOW_LIMIT = 12


# ── 발행 이력 ────────────────────────────────────────────────────────────────

def _published_titles() -> set:
    """publish_log.jsonl 에 기록된 제목 집합. 중복 발행 경고용."""
    log_path = POSTS_DIR / "publish_log.jsonl"
    titles = set()
    if not log_path.exists():
        return titles
    for line in log_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                titles.add(json.loads(line).get("title", ""))
            except Exception:
                continue
    return titles


# ── 후보 수집 ────────────────────────────────────────────────────────────────

def _zip_title(zip_path: Path) -> str:
    """ZIP 안 원고에서 제목만 빠르게 읽습니다. 실패하면 빈 문자열."""
    try:
        with zipfile.ZipFile(zip_path) as zf:
            txts = [n for n in zf.namelist() if n.lower().endswith(".txt")]
            if not txts:
                return ""
            from zip_importer import parse_manuscript
            text = zf.read(txts[0]).decode("utf-8", errors="replace")
            return parse_manuscript(text)[0]
    except Exception:
        return ""


def _zip_image_count(zip_path: Path) -> int:
    try:
        with zipfile.ZipFile(zip_path) as zf:
            return sum(1 for n in zf.namelist()
                       if Path(n).suffix.lower() in _IMAGE_EXTS)
    except Exception:
        return 0


def _folder_title(folder: Path) -> str:
    content = folder / "content.txt"
    if not content.exists():
        return folder.name
    text = content.read_text(encoding="utf-8").strip()
    return text.split("\n\n")[0].strip() if text else folder.name


def collect_candidates() -> list:
    """발행 후보를 최신순으로 모읍니다.

    반환 항목: {kind: 'folder'|'zip', path, title, date, images, mtime}
    이미 posts/ 로 임포트된 ZIP 은 목록에서 빼서 중복 표시를 막습니다.
    """
    import re

    items = []
    # 폴더명은 손으로 바꿀 수 있으므로, 같은 글인지는 '제목'으로 판단합니다.
    folder_titles = set()

    # 1) 이미 임포트된 posts/ 폴더
    if POSTS_DIR.exists():
        for date_dir in POSTS_DIR.iterdir():
            if not date_dir.is_dir():
                continue
            for post_dir in date_dir.iterdir():
                if not post_dir.is_dir() or not (post_dir / "content.txt").exists():
                    continue
                title = _folder_title(post_dir)
                items.append({
                    "kind":   "folder",
                    "path":   post_dir,
                    "title":  title,
                    "date":   date_dir.name,
                    "images": sum(1 for p in post_dir.iterdir()
                                  if p.suffix.lower() in _IMAGE_EXTS),
                    "mtime":  post_dir.stat().st_mtime,
                })
                folder_titles.add(title.strip())

    # 2) 아직 임포트 안 된 카드뉴스 ZIP
    if CARDNEWS_DIR.exists():
        for zp in CARDNEWS_DIR.glob("*.zip"):
            title = _zip_title(zp)
            if not title:
                continue    # 원고 형식이 아닌 ZIP(이미지 묶음 등)은 건너뜀
            if title.strip() in folder_titles:
                continue    # 이미 임포트됨 -> 폴더 쪽으로만 표시

            m = re.match(r"^(\d{4})(\d{2})(\d{2})", zp.stem)
            date = f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else ""

            items.append({
                "kind":   "zip",
                "path":   zp,
                "title":  title,
                "date":   date,
                "images": _zip_image_count(zp),
                "mtime":  zp.stat().st_mtime,
            })

    items.sort(key=lambda x: x["mtime"], reverse=True)
    return items


# ── 출력 ─────────────────────────────────────────────────────────────────────

def print_list(items: list, limit: int = _SHOW_LIMIT) -> None:
    if not items:
        print("발행 가능한 글이 없습니다.")
        print(f"  카드뉴스 ZIP 폴더: {CARDNEWS_DIR}")
        print(f"  포스트 폴더      : {POSTS_DIR.resolve()}")
        return

    done = _published_titles()
    print(f"\n발행 가능한 글 (최신순, 상위 {min(len(items), limit)}건)\n")
    for i, it in enumerate(items[:limit], 1):
        badge = "[ZIP]" if it["kind"] == "zip" else "[폴더]"
        date  = it["date"] or "날짜없음"
        mark  = "  [OK] 이미 발행함" if it["title"] in done else ""
        title = it["title"][:52]
        print(f"  {i:>2}. [{date}] {title}")
        print(f"      {badge}  이미지 {it['images']}장{mark}")
    print()


# ── 실행 ─────────────────────────────────────────────────────────────────────

def prepare(item: dict) -> Path:
    """ZIP이면 임포트하고, 폴더면 그대로 경로를 돌려줍니다."""
    if item["kind"] == "folder":
        return item["path"]

    from zip_importer import import_cardnews_zip
    print(f"[임포트] {item['path'].name}")
    dest = import_cardnews_zip(item["path"], posts_dir=POSTS_DIR)
    n_img = sum(1 for p in dest.iterdir() if p.suffix.lower() in _IMAGE_EXTS)
    n_par = len([p for p in (dest / "content.txt").read_text(encoding="utf-8").split("\n\n")
                 if p.strip()]) - 1
    print(f"  -> {dest}")
    print(f"  -> 문단 {n_par}개 · 이미지 {n_img}장")
    return dest


def pick_cta(preset_name: str = "") -> dict | None:
    """CTA 프리셋을 고릅니다. 이름을 주면 바로 찾고, 없으면 목록에서 선택받습니다."""
    from cta_presets import load_presets, get_preset, summary

    if preset_name:
        cta = get_preset(preset_name)
        if cta is None:
            print(f"[안내] '{preset_name}' CTA를 찾지 못했습니다 - CTA 없이 진행합니다.")
        return cta

    presets = load_presets()
    if not presets:
        return None

    print("\n붙일 CTA 블록:")
    print("   0. (사용 안 함)")
    for i, p in enumerate(presets, 1):
        print(f"   {i}. {p['name']}  -  {summary(p)}")
    try:
        raw = input(f"번호 선택 (0~{len(presets)}, Enter는 사용 안 함): ").strip()
    except EOFError:
        return None
    if not raw or raw == "0" or not raw.isdigit():
        return None
    idx = int(raw)
    return presets[idx - 1] if 1 <= idx <= len(presets) else None


def upload(folder: Path, cta: dict | None = None) -> None:
    from step2_upload import upload_to_naver_blog
    upload_to_naver_blog(folder_path=str(folder), headless=False,
                         auto_publish=False, cta=cta)


def main() -> None:
    args = [a for a in sys.argv[1:]]
    list_only   = "--list" in args
    import_only = "--import-only" in args
    nums = [a for a in args if a.isdigit()]

    items = collect_candidates()

    if list_only or (not nums and not items):
        print_list(items)
        return

    if nums:
        idx = int(nums[0])
    else:
        print_list(items)
        try:
            raw = input(f"업로드할 번호 (1~{min(len(items), _SHOW_LIMIT)}, 취소는 Enter): ").strip()
        except EOFError:
            print("입력을 받을 수 없는 환경입니다. `python publish.py <번호>` 형태로 실행하세요.")
            return
        if not raw:
            print("취소했습니다.")
            return
        if not raw.isdigit():
            print("숫자를 입력해주세요.")
            return
        idx = int(raw)

    if not 1 <= idx <= len(items):
        print(f"1 ~ {len(items)} 사이 번호를 입력해주세요.")
        return

    item = items[idx - 1]
    if item["title"] in _published_titles():
        print(f"\n!  이 글은 이미 발행 이력이 있습니다: {item['title'][:50]}")
        try:
            if input("그래도 진행할까요? (y/N): ").strip().lower() != "y":
                print("취소했습니다.")
                return
        except EOFError:
            print("중복으로 보여 중단합니다. 계속하려면 대화형으로 실행하세요.")
            return

    print(f"\n> 선택: [{item['date'] or '날짜없음'}] {item['title'][:52]}")
    folder = prepare(item)

    if import_only:
        print(f"\n[완료] 임포트만 했습니다 -> {folder}")
        return

    # --cta "이름" 으로 지정하거나, 없으면 목록에서 선택
    cta_name = ""
    if "--cta" in args:
        i = args.index("--cta")
        if i + 1 < len(args):
            cta_name = args[i + 1]
    cta = pick_cta(cta_name)

    print()
    upload(folder, cta=cta)


if __name__ == "__main__":
    main()
