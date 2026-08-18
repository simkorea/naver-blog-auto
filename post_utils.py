"""
post_utils.py - posts/ 폴더를 다루는 공용 헬퍼

포스트 목록 조회, 이미지 순서 읽기/쓰기, ZIP 묶기처럼
여러 화면에서 똑같이 쓰이던 로직을 한곳에 모았습니다.

Streamlit 에 의존하지 않으므로 스크립트(publish.py 등)에서도 그대로 씁니다.
"""
import io
import zipfile
from pathlib import Path

POSTS_DIR = Path("posts")

IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif")
ORDER_FILE = "image_order.txt"


def get_all_posts(posts_dir: Path | str = POSTS_DIR) -> list:
    """posts/ 아래 포스트를 최신순으로 반환합니다.

    반환 항목: {date, title, dir, content_path}
    content.txt 가 있는 폴더만 포스트로 봅니다.
    """
    posts_dir = Path(posts_dir)
    posts = []
    if not posts_dir.exists():
        return posts

    for date_dir in sorted(posts_dir.iterdir(), reverse=True):
        if not date_dir.is_dir():
            continue
        for post_dir in sorted(date_dir.iterdir(),
                               key=lambda d: d.stat().st_mtime, reverse=True):
            if not post_dir.is_dir():
                continue
            content_file = post_dir / "content.txt"
            if content_file.exists():
                posts.append({
                    "date":         date_dir.name,
                    "title":        post_dir.name,
                    "dir":          post_dir,
                    "content_path": content_file,
                })
    return posts


def get_images(folder: Path | str) -> list:
    """폴더의 이미지를 표시 순서대로 반환합니다.

    image_order.txt 가 있으면 그 순서를 따르고, 목록에 없는 파일은 뒤에 붙입니다.
    없으면 파일명 숫자순(1.jpg, 2.jpg …)으로 정렬합니다.
    """
    folder = Path(folder)
    if not folder.exists() or not folder.is_dir():
        return []

    all_imgs = [f for f in folder.iterdir()
                if f.is_file() and f.suffix.lower() in IMAGE_EXTS]
    try:
        all_imgs.sort(key=lambda x: int(x.stem))
    except Exception:
        all_imgs.sort()

    order_file = folder / ORDER_FILE
    if not order_file.exists():
        return all_imgs

    img_map = {f.name: f for f in all_imgs}
    ordered, seen = [], set()
    for name in order_file.read_text(encoding="utf-8").splitlines():
        name = name.strip()
        if name in img_map and name not in seen:
            ordered.append(img_map[name])
            seen.add(name)
    for f in all_imgs:
        if f.name not in seen:
            ordered.append(f)
    return ordered


def load_img_order(post_dir: Path | str) -> list:
    """이미지 경로를 문자열 목록으로 반환합니다."""
    post_dir = Path(post_dir)
    if not post_dir.exists() or not post_dir.is_dir():
        return []
    return [str(p) for p in get_images(post_dir)]


def save_img_order(post_dir: Path | str, order: list) -> None:
    """현재 이미지 순서를 image_order.txt 에 저장합니다."""
    (Path(post_dir) / ORDER_FILE).write_text(
        "\n".join(Path(p).name for p in order), encoding="utf-8"
    )


def make_zip(post_dir: Path | str) -> bytes:
    """포스트 폴더의 파일 전체를 ZIP bytes 로 묶습니다."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(Path(post_dir).iterdir()):
            if f.is_file():
                zf.write(f, f.name)
    return buf.getvalue()
