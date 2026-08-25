import os
import sys
import time
import datetime
from dotenv import load_dotenv

# Windows 콘솔 기본 인코딩(cp949)은 '-', '>' 같은 문자를 출력하지 못해
# print 하는 순간 UnicodeEncodeError 가 나고 업로드 전체가 중단됩니다.
# 출력 때문에 작업이 실패하는 일이 없도록 UTF-8 + 대체문자 모드로 바꿉니다.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

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

# 로그인 쿠키를 저장해 두는 파일.
# 매번 새로 로그인하면 네이버가 자동화로 보고 캡차를 띄우므로, 한 번 로그인한 세션을
# 재사용합니다. 계정 접근 권한이 담긴 파일이니 절대 공유/커밋하지 마세요(.gitignore 등록됨).
SESSION_FILE = os.getenv("NAVER_SESSION_FILE", "naver_session.json")

# 캡차 등 추가 인증을 사용자가 직접 푸는 동안 기다려 줄 시간(분)
LOGIN_WAIT_MIN = 10

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
        return date_dir  # 서브폴더 없음 -> 기존 방식 폴백

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
    """텍스트 붙여넣기 - pyperclip 없으면 JS 클립보드 API 사용."""
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


def _wait_for_user_close(page, hours: int = 1) -> None:
    """사용자가 브라우저에서 검토/발행을 마칠 때까지 기다립니다.

    창을 닫는 것은 '작업을 끝냈다'는 정상 신호이므로 오류로 취급하지 않습니다.
    (예전에는 창을 닫으면 'Target page ... has been closed' 예외가 그대로 떠서
     정상 종료인데도 실패한 것처럼 보였습니다.)
    """
    try:
        page.wait_for_timeout(hours * 3600 * 1000)
    except Exception:
        print("  -> 브라우저 창이 닫혔습니다. 작업을 마칩니다.")


def _is_logged_in(page) -> bool:
    """네이버에 이미 로그인된 상태인지 확인합니다."""
    try:
        page.goto("https://www.naver.com", wait_until="domcontentloaded", timeout=20000)
        time.sleep(1.5)
        # 로그인 상태면 로그아웃/내정보 관련 요소가 보입니다.
        for sel in ("a.link_login[href*='logout']", ".MyView-module__link_login",
                    "a[href*='nid.naver.com/nidlogin.logout']"):
            if page.locator(sel).count() > 0:
                return True
        # 폴백: 블로그 글쓰기로 가봤을 때 로그인 페이지로 튕기지 않으면 로그인 상태
        page.goto(f"https://blog.naver.com/{NAVER_ID}?Redirect=Write",
                  wait_until="domcontentloaded", timeout=25000)
        time.sleep(2)
        return "nid.naver.com" not in page.url
    except Exception:
        return False


def _ensure_logged_in(page, headless: bool) -> bool:
    """로그인 상태를 보장합니다. 필요하면 로그인하고, 추가 인증은 사용자에게 맡깁니다.

    네이버는 자동 로그인을 감지하면 캡차(영수증 문제 등) 같은 추가 인증을 요구합니다.
    이 함수는 그걸 대신 풀지 않습니다 - 열려 있는 브라우저에서 직접 풀어달라고 안내하고,
    통과할 때까지 기다립니다. 한 번 통과하면 세션이 저장되어 다음부터는 이 단계를 건너뜁니다.
    """
    if _is_logged_in(page):
        print("  -> 이미 로그인된 상태입니다. 로그인 단계를 건너뜁니다.")
        return True

    print("  -> 로그인을 진행합니다.")
    page.goto("https://nid.naver.com/nidlogin.login")
    page.wait_for_load_state("networkidle")

    page.click("#id")
    _paste_text(page, NAVER_ID)
    page.click("#pw")
    _paste_text(page, NAVER_PW)

    login_btn = page.locator("#loginBtn_row")
    if not login_btn.is_visible():
        login_btn = page.locator("#loginBtn_column")
    login_btn.click()
    page.wait_for_timeout(4000)

    # 로그인 페이지를 벗어났으면 성공
    if "nid.naver.com" not in page.url:
        print("  -> 로그인 성공")
        return True

    # 아직 nid.naver.com 이면 추가 인증(캡차 등) 화면일 가능성이 큽니다.
    if headless:
        print(
            "\n[중단] 네이버가 추가 인증(캡차)을 요구했습니다.\n"
            "  headless 모드에서는 처리할 수 없습니다.\n"
            "  headless=False 로 다시 실행해서 화면에서 직접 인증해주세요.\n"
        )
        return False

    print(
        "\n" + "=" * 58 + "\n"
        "  네이버가 추가 인증을 요구했습니다 (캡차 등).\n"
        "\n"
        "  > 열려 있는 크롬 창에서 직접 인증을 완료해주세요.\n"
        "    (자동으로 풀지 않습니다 - 계정 보호를 위해 사람이 해야 합니다)\n"
        "\n"
        f"  인증을 마치면 자동으로 이어서 진행됩니다. 최대 {LOGIN_WAIT_MIN}분 대기합니다.\n"
        + "=" * 58 + "\n"
    )

    # 사용자가 인증을 마칠 때까지 대기 (로그인 페이지를 벗어나면 통과)
    deadline = time.time() + LOGIN_WAIT_MIN * 60
    while time.time() < deadline:
        try:
            if "nid.naver.com" not in page.url:
                print("  -> 인증 완료 확인. 계속 진행합니다.")
                time.sleep(2)
                return True
        except Exception:
            print("\n[중단] 브라우저 창이 닫혔습니다. 다시 실행해주세요.")
            return False
        time.sleep(3)

    print(f"\n[중단] {LOGIN_WAIT_MIN}분 안에 인증이 완료되지 않았습니다. 다시 실행해주세요.")
    return False


def _load_tags(folder_path: str, full_text: str) -> list:
    """태그 목록을 반환합니다. tags.txt 우선, 없으면 본문 해시태그에서 추출."""
    import re

    tags_file = os.path.join(folder_path, "tags.txt")
    if os.path.exists(tags_file):
        with open(tags_file, encoding="utf-8") as f:
            tags = [t.strip().lstrip("#") for t in f.read().splitlines() if t.strip()]
        if tags:
            return tags[:30]        # 네이버 태그 상한

    seen, tags = set(), []
    for t in re.findall(r"#(\S+)", full_text):
        if t not in seen:
            seen.add(t)
            tags.append(t)
    return tags[:30]


def _fill_publish_options(page, iframe, tags: list, category: str = "",
                          visibility: str = "") -> None:
    """발행 패널을 열고 태그 / 카테고리 / 공개설정을 채웁니다.

    최종 [발행] 버튼은 누르지 않습니다 - 사용자가 검토 후 직접 누르도록 패널만 열어둡니다.
    네이버 UI가 바뀌어 각 항목이 실패해도 본문 입력 결과에는 영향이 없도록
    항목별로 따로 try 처리합니다.
    """
    try:
        print("[7] 발행 옵션 설정 중...")
        iframe.locator("button.publish_btn__m9KHH, button:has-text('발행')").first.click(timeout=8000)
        time.sleep(2)
    except Exception as e:
        print(f"  [안내] 발행 패널을 열지 못했습니다 ({e}) - 직접 [발행]을 눌러 설정해주세요.")
        return

    # ── 카테고리 ──
    if category:
        try:
            iframe.locator(
                "button.selectbox_button__jb1Dt, button[class*='category'], "
                "button:has-text('카테고리')"
            ).first.click(timeout=5000)
            time.sleep(1)
            iframe.locator(f"label:has-text('{category}'), li:has-text('{category}')").first.click(timeout=5000)
            time.sleep(0.5)
            print(f"  -> 카테고리: {category}")
        except Exception as e:
            print(f"  [안내] 카테고리 '{category}' 선택 실패 ({e}) - 직접 선택해주세요.")

    # ── 공개 설정 ──
    if visibility:
        try:
            iframe.locator(f"label:has-text('{visibility}'), span:has-text('{visibility}')").first.click(timeout=5000)
            time.sleep(0.5)
            print(f"  -> 공개설정: {visibility}")
        except Exception as e:
            print(f"  [안내] 공개설정 '{visibility}' 적용 실패 ({e}) - 직접 선택해주세요.")

    # ── 태그 ──
    if tags:
        try:
            tag_input = None
            for sel in ("input#tag-input", "input.tag_input__rvUB5",
                        "input[placeholder*='태그']", ".tag_area input"):
                loc = iframe.locator(sel).first
                try:
                    loc.wait_for(state="visible", timeout=3000)
                    tag_input = loc
                    break
                except Exception:
                    continue

            if tag_input is None:
                print("  [안내] 태그 입력란을 찾지 못했습니다 - 직접 입력해주세요.")
            else:
                tag_input.click()
                for tag in tags:
                    _paste_text(page, tag)
                    page.keyboard.press("Enter")
                    time.sleep(0.3)
                print(f"  -> 태그 {len(tags)}개 입력 완료")
        except Exception as e:
            print(f"  [안내] 태그 자동 입력을 건너뜁니다 ({e}) - 직접 입력해주세요.")


def _log_publish(folder_path, title, n_paragraphs, n_images, tags, auto_published) -> None:
    """업로드 결과를 posts/publish_log.jsonl 에 한 줄씩 기록합니다.

    같은 글을 실수로 두 번 올리는 것을 막고, 언제 무엇을 올렸는지 추적하기 위한 기록입니다.
    (에디터 입력까지 완료된 시점 기준 - 최종 발행 버튼은 사용자가 누릅니다.)
    """
    import json

    try:
        log_path = os.path.join("posts", "publish_log.jsonl")
        os.makedirs("posts", exist_ok=True)
        record = {
            "at":            datetime.datetime.now().isoformat(timespec="seconds"),
            "folder":        str(folder_path),
            "title":         title,
            "paragraphs":    n_paragraphs,
            "images":        n_images,
            "tags":          tags,
            "auto_published": bool(auto_published),
        }
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"  [안내] 발행 이력 기록 실패: {e}")


def _insert_cta(page, iframe, cta: dict) -> None:
    """본문 맨 끝에 CTA 블록(문구 / 링크 / 이미지 / 지도)을 넣습니다.

    각 요소는 독립적으로 시도하며, 하나가 실패해도 나머지는 계속 진행합니다.
    지도는 네이버 에디터 UI 의존도가 높아 실패 가능성이 있어 마지막에 넣습니다.
    """
    import os as _os

    name = cta.get("name") or "CTA"
    print(f"[CTA] '{name}' 삽입 중...")

    # 본문과 구분되도록 빈 줄 하나
    page.keyboard.press("Enter")
    time.sleep(0.3)

    # 1) 문구
    text = str(cta.get("text", "")).strip()
    if text:
        for para in [p for p in text.split("\n") if p.strip()]:
            _paste_text(page, para.strip())
            page.keyboard.press("Enter")
            time.sleep(0.25)
        print("  -> 문구 삽입 완료")

    # 2) 이미지 (배너)
    img = str(cta.get("image", "")).strip()
    if img:
        if _os.path.exists(img):
            try:
                with page.expect_file_chooser(timeout=5000) as fc:
                    iframe.locator("button.se-image-toolbar-button").first.click()
                fc.value.set_files(_os.path.abspath(img))
                time.sleep(4)
                page.keyboard.press("Enter")
                time.sleep(0.5)
                print("  -> 배너 이미지 삽입 완료")
            except Exception as e:
                print(f"  [경고] 배너 이미지 삽입 실패: {e}")
        else:
            print(f"  [경고] 배너 이미지 파일이 없습니다: {img}")

    # 3) 링크 - URL 을 그대로 붙이면 네이버가 링크 카드로 바꿔줍니다.
    link = str(cta.get("link", "")).strip()
    if link:
        _paste_text(page, link)
        page.keyboard.press("Enter")
        time.sleep(1.5)
        print("  -> 링크 삽입 완료")

    # 4) 지도 - 에디터 UI 의존도가 높아 실패해도 넘어갑니다.
    addr = str(cta.get("map", "")).strip()
    if addr:
        try:
            iframe.locator("button.se-map-toolbar-button").first.click(timeout=5000)
            time.sleep(1.5)
            search = iframe.locator("input[placeholder*='장소'], input[placeholder*='주소'], .se-map-search input").first
            search.wait_for(state="visible", timeout=5000)
            search.click()
            _paste_text(page, addr)
            page.keyboard.press("Enter")
            time.sleep(2)
            iframe.locator("button:has-text('확인'), .se-map-search-result li").first.click(timeout=5000)
            time.sleep(1.5)
            print("  -> 지도 삽입 완료")
        except Exception as e:
            print(f"  [안내] 지도 자동 삽입을 건너뜁니다 ({e})")
            print(f"         발행 화면에서 직접 추가해주세요 - 주소: {addr}")


def plan_image_positions(n_paragraphs: int, n_images: int) -> dict:
    """이미지를 본문 전체에 균등 배치할 위치를 계산합니다.

    반환값: {문단번호(1-base): 이미지인덱스} - 해당 문단을 입력한 뒤 그 이미지를 넣습니다.

    이전에는 `문단수 // 이미지수` 로 간격을 구했는데, 나눗셈에서 소수점이 버려지면
    간격이 1로 좁아져 앞쪽 문단에서 이미지를 다 써버리고 뒤쪽 절반이 비는 문제가
    있었습니다 (예: 문단 18 / 이미지 10 -> 간격 1 -> 1~10문단에 몰림).
    지금은 각 이미지를 본문 길이에 비례한 위치에 배치해 문단 수와 무관하게
    처음부터 끝까지 고르게 퍼지도록 합니다.
    """
    if n_images <= 0 or n_paragraphs <= 0:
        return {}

    positions: dict[int, int] = {}
    for k in range(n_images):
        pos = round((k + 1) * n_paragraphs / (n_images + 1))
        pos = max(1, min(pos, n_paragraphs))
        # 같은 문단에 두 장이 겹치면 뒤 문단으로 밀어냅니다.
        while pos in positions and pos < n_paragraphs:
            pos += 1
        if pos in positions:      # 뒤쪽이 이미 꽉 찼으면 앞으로 당김
            pos = next((p for p in range(1, n_paragraphs + 1) if p not in positions), None)
            if pos is None:
                break
        positions[pos] = k
    return positions


def upload_to_naver_blog(folder_path=None, headless=False, auto_publish=False,
                         cta=None, category="", visibility=""):
    """네이버 블로그에 원고와 이미지를 자동 입력합니다.

    cta        : CTA 프리셋 dict (cta_presets.get_preset 결과). None 이면 넣지 않음
    category   : 블로그 카테고리 이름. 비우면 네이버 기본값 사용
    visibility : '전체공개' / '이웃공개' / '서로이웃공개' / '비공개'. 비우면 기본값
    """
    if not PLAYWRIGHT_OK:
        # 대부분은 '패키지가 없어서'가 아니라 '엉뚱한 파이썬으로 실행돼서' 입니다.
        # 어느 파이썬으로 돌고 있는지 같이 보여줘야 원인을 바로 알 수 있습니다.
        print("[오류] playwright 를 불러오지 못했습니다.")
        print(f"       현재 파이썬: {sys.executable}")
        if "venv" not in sys.executable.replace("\\", "/"):
            print("       → venv 가 아닌 파이썬으로 실행되고 있습니다. 이것이 원인입니다.")
            print("         대시보드를 완전히 닫고 '네이버 블로그 자동화' 바로가기로 다시 여세요.")
        else:
            print("       → 설치: venv\\Scripts\\python.exe -m pip install playwright")
            print("               venv\\Scripts\\python.exe -m playwright install chromium")
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

    # 태그: tags.txt 가 있으면 사용, 없으면 본문 해시태그에서 추출
    tags = _load_tags(folder_path, full_text)
    if tags:
        print(f"[시스템] 태그 {len(tags)}개: {', '.join(tags)}")

    # 이미지를 본문 전체에 균등 배치 (문단 수와 무관하게 고르게 퍼짐)
    image_positions = plan_image_positions(len(paragraphs), len(images))

    # CTA - 내용이 없는 프리셋은 무시
    from cta_presets import is_empty as _cta_empty
    if _cta_empty(cta):
        cta = None
    elif cta:
        print(f"[시스템] CTA: '{cta.get('name', '이름없음')}'")

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

        # 저장된 로그인 세션이 있으면 재사용 -> 매번 로그인하지 않아 캡차가 잘 뜨지 않습니다.
        if os.path.exists(SESSION_FILE):
            ctx_kwargs["storage_state"] = SESSION_FILE
            print(f"[1] 저장된 로그인 세션 사용 ({SESSION_FILE})")
        else:
            print("[1] 저장된 세션 없음 - 로그인이 필요합니다.")

        context = browser.new_context(**ctx_kwargs)
        page = context.new_page()

        if not _ensure_logged_in(page, headless):
            context.close()
            browser.close()
            return

        # 로그인 성공 상태를 저장해 다음 실행 때 재사용
        try:
            context.storage_state(path=SESSION_FILE)
            print(f"  -> 로그인 세션 저장 완료 ({SESSION_FILE})")
        except Exception as e:
            print(f"  [안내] 세션 저장 실패(무시 가능): {e}")

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
                iframe.locator("div.se-component.se-text .se-text-paragraph").first.click(timeout=5000)
            except Exception:
                iframe.locator(".se-component.se-text").first.click()
            time.sleep(0.5)

            print("[5] 문단과 이미지 교차 업로드 시작...")
            uploaded_imgs = 0

            for i, para in enumerate(paragraphs):
                _paste_text(page, para)
                page.keyboard.press("Enter")
                time.sleep(0.3)

                img_idx = image_positions.get(i + 1)
                if img_idx is not None and img_idx < len(images):
                    img_path = os.path.abspath(images[img_idx])
                    print(f"  -> 이미지 업로드 중: {os.path.basename(img_path)}  (문단 {i+1} 뒤)")
                    try:
                        with page.expect_file_chooser(timeout=5000) as fc_info:
                            iframe.locator("button.se-image-toolbar-button").first.click()
                        fc_info.value.set_files(img_path)
                        time.sleep(4)
                        page.keyboard.press("Enter")
                        time.sleep(0.5)
                        uploaded_imgs += 1
                    except Exception as img_e:
                        print(f"  [경고] 이미지 업로드 실패 ({os.path.basename(img_path)}): {img_e}")

            print(f"\n[성공] 글과 이미지 업로드 완료! (이미지 {uploaded_imgs}/{len(images)}장)")

            # CTA 블록 - 본문 맨 끝에 붙입니다 (발행 패널을 열기 전에 넣어야 함)
            if cta:
                _insert_cta(page, iframe, cta)

            # 발행 패널을 열어 태그·카테고리·공개설정을 채웁니다.
            # 실패해도 본문 입력 결과는 그대로 유지됩니다.
            if tags or category or visibility:
                _fill_publish_options(page, iframe, tags, category, visibility)

            _log_publish(folder_path, title, len(paragraphs), uploaded_imgs, tags, auto_publish)

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
                        _wait_for_user_close(page)
            else:
                print("에디터 창에서 최종 확인 후 직접 [발행] 버튼을 눌러주세요.")
                _wait_for_user_close(page)

        except Exception as e:
            print(f"\n[오류 발생] 에디터 조작 중 문제 발생: {e}")
            if not headless:
                _wait_for_user_close(page)
            context.close()
            browser.close()
            raise RuntimeError(f"네이버 에디터 조작 실패: {e}") from e

        context.close()
        browser.close()

if __name__ == "__main__":
    upload_to_naver_blog()
