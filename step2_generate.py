"""
step2_generate.py — Supabase watcher 에서 전달받은 데이터로 네이버 블로그 업로드

호출 방식 (watcher.py 에서):
    from step2_generate import upload_post
    upload_post(row_dict)

직접 실행 (테스트):
    python step2_generate.py                   # 더미 데이터로 테스트
    python step2_generate.py post_data.json    # JSON 파일로 테스트

post_data 구조 (Supabase post_queue 행):
    {
        "id":           "uuid",
        "title":        "포스트 제목",
        "content":      "본문 전체 (문단 구분 \\n\\n)",
        "tags":         "태그1,태그2,태그3",
        "date":         "2024-01-15",
        "local_folder": "2024-01-15_제목슬러그",
        "status":       "pending"
    }
"""
import os
import time
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

NAVER_ID = os.getenv("NAVER_ID", "")
NAVER_PW = os.getenv("NAVER_PASSWORD", "")
POSTS_DIR = Path("posts")


# ── 로컬 폴더 준비 ────────────────────────────────────────────────────────────

def _prepare_folder(post_data: dict) -> Path:
    """로컬 폴더를 찾거나 생성 후 content.txt 를 Supabase 내용으로 동기화."""
    date         = post_data.get("date", "")
    local_folder = post_data.get("local_folder", "")
    content      = post_data.get("content", "")
    title        = post_data.get("title", "")

    # 기존 폴더 탐색
    candidates = [
        POSTS_DIR / date / local_folder,
        POSTS_DIR / local_folder,
    ]
    folder: Path | None = None
    for p in candidates:
        if p.exists() and (p / "content.txt").exists():
            folder = p
            break

    # 날짜 폴더 아래 유사 이름 탐색 (앞 10자 기준)
    if folder is None and date:
        date_dir = POSTS_DIR / date
        if date_dir.exists():
            for d in sorted(date_dir.iterdir()):
                if d.is_dir() and local_folder[:10] in d.name:
                    folder = d
                    break

    # 못 찾으면 새로 생성
    if folder is None:
        folder = POSTS_DIR / date / local_folder
        folder.mkdir(parents=True, exist_ok=True)
        print(f"  [경고] 로컬 폴더 없음 → {folder} 임시 생성 (이미지 없음)")

    # content.txt: Supabase 버전이 더 최신이면 덮어쓰기
    content_file = folder / "content.txt"
    local_text = content_file.read_text(encoding="utf-8").strip() if content_file.exists() else ""
    if content.strip() and local_text != content.strip():
        # 첫 줄이 제목이 아니면 제목을 맨 앞에 추가
        first_line = content.strip().split("\n")[0]
        write_content = content if first_line == title else f"{title}\n\n{content}"
        content_file.write_text(write_content, encoding="utf-8")
        print(f"  content.txt 업데이트 완료")

    return folder


# ── 이미지 경로 수집 ──────────────────────────────────────────────────────────

def _get_images(folder: Path) -> list[str]:
    """이미지 목록 반환. image_order.txt 있으면 해당 순서대로."""
    exts = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
    all_imgs = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in exts]

    order_file = folder / "image_order.txt"
    if order_file.exists():
        img_map = {p.name: p for p in all_imgs}
        ordered, seen = [], set()
        for name in order_file.read_text(encoding="utf-8").splitlines():
            name = name.strip()
            if name in img_map and name not in seen:
                ordered.append(str(img_map[name].resolve()))
                seen.add(name)
        for p in all_imgs:
            if p.name not in seen:
                ordered.append(str(p.resolve()))
        return ordered

    try:
        all_imgs.sort(key=lambda x: int(x.stem))
    except Exception:
        all_imgs.sort()
    return [str(p.resolve()) for p in all_imgs]


# ── ★ 셀레니움 업로드 함수 ★ ────────────────────────────────────────────────
# 아래 함수 안에 기존 셀레니움 매크로 코드를 붙여 넣으세요.
# ────────────────────────────────────────────────────────────────────────────

def _upload_with_selenium(
    title: str,
    content: str,
    tags: list[str],
    images: list[str],
) -> None:
    """
    ★ 여기에 기존 Selenium 매크로 코드를 붙여 넣으세요 ★

    전달 인자
    ---------
    title   : 포스트 제목 (str)
    content : 본문 전체 텍스트. 문단 구분은 \\n\\n (str)
    tags    : 태그 목록  예) ["서울아파트", "분양정보", "청약"]  (list[str])
    images  : 이미지 절대경로 목록  예) ["C:/posts/2024-01/img1.jpg", ...]  (list[str])

    주의
    ----
    - 업로드 완료 시 정상 return 하면 됩니다.
    - 실패 시 Exception 을 raise 하면 watcher 가 자동으로 'error' 상태로 기록합니다.
    - NAVER_ID / NAVER_PW 는 이 파일 상단 전역변수를 사용하세요.
    """

    # =========================================================================
    # 아래 예시 뼈대를 실제 셀레니움 코드로 교체하세요.
    # =========================================================================

    # from selenium import webdriver
    # from selenium.webdriver.common.by import By
    # from selenium.webdriver.common.keys import Keys
    # from selenium.webdriver.support.ui import WebDriverWait
    # from selenium.webdriver.support import expected_conditions as EC
    # import pyperclip
    #
    # options = webdriver.ChromeOptions()
    # options.add_argument("--start-maximized")
    # driver = webdriver.Chrome(options=options)
    # wait = WebDriverWait(driver, 15)
    #
    # try:
    #     # 1) 로그인
    #     driver.get("https://nid.naver.com/nidlogin.login")
    #     wait.until(EC.presence_of_element_located((By.ID, "id")))
    #     pyperclip.copy(NAVER_ID)
    #     driver.find_element(By.ID, "id").send_keys(Keys.CONTROL, "v")
    #     pyperclip.copy(NAVER_PW)
    #     driver.find_element(By.ID, "pw").send_keys(Keys.CONTROL, "v")
    #     driver.find_element(By.CSS_SELECTOR, ".btn_login").click()
    #     time.sleep(3)
    #
    #     # 2) 글쓰기 이동
    #     driver.get(f"https://blog.naver.com/{NAVER_ID}?Redirect=Write")
    #     time.sleep(3)
    #
    #     # 3) 제목 입력
    #     title_area = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, ".se-documentTitle")))
    #     title_area.click()
    #     pyperclip.copy(title)
    #     title_area.send_keys(Keys.CONTROL, "v")
    #     time.sleep(0.5)
    #
    #     # 4) 본문 입력 + 이미지 삽입
    #     # (본문을 문단별로 나눠 입력하고, 이미지를 images 리스트 순서대로 삽입)
    #     paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]
    #     insert_interval = max(1, len(paragraphs) // len(images)) if images else 999
    #     image_idx = 0
    #     for i, para in enumerate(paragraphs):
    #         # ... 문단 입력 ...
    #         if images and image_idx < len(images) and (i + 1) % insert_interval == 0:
    #             img_path = images[image_idx]
    #             # ... 이미지 파일 업로드 ...
    #             image_idx += 1
    #
    #     # 5) 태그 입력
    #     for tag in tags:
    #         # ... 태그 입력 ...
    #         pass
    #
    #     # 6) 발행
    #     # ... 발행 버튼 클릭 ...
    #
    # finally:
    #     driver.quit()

    # =========================================================================
    # 셀레니움 코드가 아직 없으면 아래 줄이 실행되어 Playwright 폴백으로 넘어갑니다.
    raise NotImplementedError("_upload_with_selenium() 에 셀레니움 코드를 넣어주세요.")


# ── Playwright 폴백 ───────────────────────────────────────────────────────────

def _upload_with_playwright(folder: Path, headless: bool = False, auto_publish: bool = False) -> None:
    """셀레니움 코드가 없을 때 기존 step2_upload.py 의 Playwright 로직을 사용."""
    from step2_upload import upload_to_naver_blog
    upload_to_naver_blog(
        folder_path=str(folder),
        headless=headless,
        auto_publish=auto_publish,
    )


# ── 공개 인터페이스 ───────────────────────────────────────────────────────────

def upload_post(post_data: dict, use_selenium: bool = True) -> None:
    """
    watcher.py 에서 호출하는 메인 함수.

    Args:
        post_data   : Supabase post_queue 행 딕셔너리
        use_selenium: True  → _upload_with_selenium() 사용 (셀레니움 코드 넣은 후)
                      False → Playwright (step2_upload.py) 직접 사용
    """
    title  = post_data.get("title", "")
    content = post_data.get("content", "")
    tags   = [t.strip() for t in post_data.get("tags", "").split(",") if t.strip()]

    folder = _prepare_folder(post_data)
    images = _get_images(folder)

    print(f"  제목  : {title[:60]}")
    print(f"  태그  : {tags}")
    print(f"  이미지: {len(images)}장  |  폴더: {folder}")

    if use_selenium:
        try:
            _upload_with_selenium(title, content, tags, images)
            return
        except NotImplementedError:
            print("  [안내] 셀레니움 코드 미설정 → Playwright 폴백으로 실행합니다.")
        except Exception:
            raise   # 셀레니움 실행 중 실제 오류는 그대로 전파

    # Playwright 폴백 (headless=False → 사무실 PC 에서 화면 표시)
    _upload_with_playwright(folder, headless=False, auto_publish=False)


# ── 직접 실행 (테스트용) ──────────────────────────────────────────────────────

if __name__ == "__main__":
    import json, sys

    if len(sys.argv) > 1:
        # python step2_generate.py post_data.json
        with open(sys.argv[1], encoding="utf-8") as f:
            data = json.load(f)
    else:
        # 더미 데이터
        import datetime
        today = datetime.date.today().isoformat()
        data = {
            "id":           "test-001",
            "title":        "테스트 포스트 제목",
            "content":      "첫 번째 문단입니다.\n\n두 번째 문단입니다.\n\n세 번째 문단입니다.",
            "tags":         "테스트,네이버블로그,부동산",
            "date":         today,
            "local_folder": f"{today}_test-post",
            "status":       "pending",
        }

    print("[테스트 실행]")
    upload_post(data)
