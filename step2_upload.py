import os
import time
import datetime
from dotenv import load_dotenv

try:
    import pyperclip
    PYPERCLIP_OK = True
except ImportError:
    PYPERCLIP_OK = False

try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_OK = True
except ImportError:
    PLAYWRIGHT_OK = False

load_dotenv()

NAVER_ID = os.getenv("NAVER_ID")
NAVER_PW = os.getenv("NAVER_PASSWORD")

def get_today_folder():
    """
    posts/YYYY-MM-DD/ 아래 글제목 서브폴더 중 업로드할 폴더를 반환합니다.
    서브폴더가 1개면 자동 선택, 여러 개면 목록을 보여주고 사용자가 선택합니다.
    """
    today_str = datetime.datetime.now().strftime("%Y-%m-%d")
    date_dir = os.path.join("posts", today_str)

    if not os.path.isdir(date_dir):
        return date_dir  # 기존 방식 폴백 (오류는 upload 함수에서 처리)

    subfolders = sorted(
        [d for d in os.listdir(date_dir) if os.path.isdir(os.path.join(date_dir, d))],
        key=lambda d: os.path.getmtime(os.path.join(date_dir, d)),
        reverse=True
    )

    if not subfolders:
        return date_dir  # 서브폴더 없음 → 기존 방식 폴백

    if len(subfolders) == 1:
        chosen = subfolders[0]
        print(f"[시스템] 오늘 작성된 포스트: {chosen}")
        return os.path.join(date_dir, chosen)

    print(f"\n오늘({today_str}) 작성된 포스트가 여러 개 있습니다. 업로드할 포스트를 선택하세요:\n")
    for idx, name in enumerate(subfolders, 1):
        print(f"  {idx}. {name}")
    print()

    while True:
        sel = input(f"번호를 입력하세요 (1~{len(subfolders)}): ").strip()
        if sel.isdigit() and 1 <= int(sel) <= len(subfolders):
            chosen = subfolders[int(sel) - 1]
            return os.path.join(date_dir, chosen)
        print("올바른 번호를 입력해주세요.")

def get_images(folder_path):
    """이미지 목록 반환. image_order.txt 있으면 그 순서대로."""
    if not os.path.exists(folder_path):
        return []

    all_imgs = [
        os.path.join(folder_path, f)
        for f in os.listdir(folder_path)
        if f.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp'))
    ]

    order_file = os.path.join(folder_path, "image_order.txt")
    if os.path.exists(order_file):
        img_map = {os.path.basename(p): p for p in all_imgs}
        ordered, seen = [], set()
        with open(order_file, encoding="utf-8") as f:
            for name in f.read().splitlines():
                name = name.strip()
                if name in img_map and name not in seen:
                    ordered.append(img_map[name])
                    seen.add(name)
        for p in all_imgs:
            if os.path.basename(p) not in seen:
                ordered.append(p)
        return ordered

    try:
        all_imgs.sort(key=lambda x: int(os.path.splitext(os.path.basename(x))[0]))
    except Exception:
        all_imgs.sort()
    return all_imgs

def _paste_text(page, text: str):
    """텍스트 붙여넣기 — pyperclip 없으면 JS 클립보드 API 사용."""
    if PYPERCLIP_OK:
        pyperclip.copy(text)
        page.keyboard.press("Control+V")
    else:
        try:
            page.evaluate("(t) => navigator.clipboard.writeText(t)", text)
            time.sleep(0.05)
            page.keyboard.press("Control+V")
        except Exception:
            page.keyboard.type(text, delay=0)
    time.sleep(0.3)


def upload_to_naver_blog(folder_path=None, headless=False, auto_publish=False):
    if not PLAYWRIGHT_OK:
        print("[오류] playwright가 설치되지 않았습니다. pip install playwright 후 playwright install chromium 실행하세요.")
        return
    if not NAVER_ID or not NAVER_PW or NAVER_ID == "your_naver_id":
        print("[오류] .env 파일에 네이버 계정 정보를 입력해주세요.")
        return

    if folder_path is None:
        folder_path = get_today_folder()
    content_path = os.path.join(folder_path, "content.txt")
    
    if not os.path.exists(content_path):
        print(f"[오류] {content_path} 파일이 없습니다. step1_generate.py를 먼저 실행하세요.")
        return

    with open(content_path, "r", encoding="utf-8") as f:
        full_text = f.read().strip()
        
    # 문단 나누기 (빈 줄 기준)
    paragraphs = [p.strip() for p in full_text.split('\n\n') if p.strip()]
    if not paragraphs:
        print("[오류] content.txt에 내용이 없습니다.")
        return

    # 첫 번째 문단을 제목으로 사용
    title = paragraphs.pop(0)
    
    images = get_images(folder_path)
    print(f"[시스템] 읽어온 문단 수: {len(paragraphs)}개, 업로드할 이미지 수: {len(images)}장")

    # 이미지 삽입 주기 계산 (예: 문단 15개, 이미지 5장이면 3문단마다 1장)
    insert_interval = max(1, len(paragraphs) // len(images)) if images else 999

    print(f"네이버 블로그 에디터 자동화를 시작합니다... (headless={headless})")

    launch_args = ["--disable-blink-features=AutomationControlled"]
    if headless:
        launch_args += ["--no-sandbox", "--disable-dev-shm-usage"]
    else:
        launch_args.append("--start-maximized")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless, args=launch_args)
        ctx_kwargs = dict(permissions=["clipboard-read", "clipboard-write"])
        if headless:
            ctx_kwargs["viewport"] = {"width": 1920, "height": 1080}
        else:
            ctx_kwargs["no_viewport"] = True
        context = browser.new_context(**ctx_kwargs)
        page = context.new_page()

        print("[1] 로그인 진행 중...")
        page.goto("https://nid.naver.com/nidlogin.login")
        page.wait_for_load_state("networkidle")

        page.click("#id")
        _paste_text(page, NAVER_ID)

        page.click("#pw")
        _paste_text(page, NAVER_PW)

        page.click(".btn_login")
        page.wait_for_timeout(3000)

        print("[2] 스마트에디터로 이동 중...")
        page.goto(f"https://blog.naver.com/{NAVER_ID}?Redirect=Write")
        page.wait_for_load_state("networkidle")
        time.sleep(3)

        try:
            iframe = page.frame_locator("#mainFrame")
            iframe.locator(".se-documentTitle").wait_for(state="visible", timeout=15000)

            # 임시저장 팝업 무시
            try:
                iframe.locator("button.se-popup-button-cancel").click(timeout=2000)
            except Exception:
                pass

            print("[3] 제목 입력 중...")
            iframe.locator(".se-documentTitle").click()
            time.sleep(0.5)
            _paste_text(page, title)
            time.sleep(1)

            print("[4] 본문 영역 포커스 이동...")
            try:
                iframe.locator("span:has-text('나의 일상을 기록해보세요!')").first.click(timeout=3000)
            except Exception:
                iframe.locator(".se-main-container").click()
            time.sleep(0.5)

            print("[5] 문단과 이미지 교차 업로드 시작...")
            image_idx = 0

            for i, para in enumerate(paragraphs):
                _paste_text(page, para)
                page.keyboard.press("Enter")
                time.sleep(0.3)

                if images and image_idx < len(images) and (i + 1) % insert_interval == 0:
                    img_path = os.path.abspath(images[image_idx])
                    print(f"  -> 이미지 업로드 중: {os.path.basename(img_path)}")
                    try:
                        with page.expect_file_chooser(timeout=5000) as fc_info:
                            iframe.locator("button.se-image-toolbar-button").first.click()
                        fc_info.value.set_files(img_path)
                        time.sleep(4)
                        page.keyboard.press("Enter")
                        time.sleep(0.5)
                        image_idx += 1
                    except Exception as img_e:
                        print(f"  [경고] 이미지 업로드 실패 ({os.path.basename(img_path)}): {img_e}")

            print("\n[성공] 글과 이미지 업로드 완료!")

            if auto_publish:
                print("[6] 자동 발행 중...")
                try:
                    # 발행 버튼 클릭 (Naver Smart Editor 3.0)
                    publish_btn = iframe.locator("button:has-text('발행')")
                    publish_btn.wait_for(state="visible", timeout=10000)
                    publish_btn.click()
                    time.sleep(2)
                    # 발행 확인 팝업에서 확인 버튼 클릭
                    try:
                        iframe.locator("button.se-popup-button-publish").click(timeout=5000)
                    except Exception:
                        pass
                    page.wait_for_timeout(3000)
                    print("[발행 완료]")
                except Exception as pub_e:
                    print(f"[경고] 자동 발행 실패: {pub_e}\n수동으로 [발행] 버튼을 눌러주세요.")
                    if not headless:
                        page.wait_for_timeout(3600000)
            else:
                print("에디터 창에서 최종 확인 후 직접 [발행] 버튼을 눌러주세요.")
                page.wait_for_timeout(3600000)

        except Exception as e:
            print(f"\n[오류 발생] 에디터 조작 중 문제 발생: {e}")
            if not headless:
                page.wait_for_timeout(3600000)
            context.close()
            browser.close()
            raise RuntimeError(f"네이버 에디터 조작 실패: {e}") from e

        context.close()
        browser.close()

if __name__ == "__main__":
    upload_to_naver_blog()
