"""
image_fetcher.py

실제 이미지를 두 가지 경로로 수집합니다.
  1. 참조 기사 본문 이미지 — 기사 URL에서 직접 추출
  2. 청약/분양 특화 이미지 — 단지명을 추출하여 조감도·평면도·배치도를 네이버 이미지 검색으로 수집

사용처: step1_generate.py 에서 Leonardo AI 이미지 생성 전에 먼저 호출합니다.
실제 이미지로 채워진 슬롯 번호를 반환하면, Leonardo 는 그 다음 번호부터 채웁니다.
"""

import os
import re
import time
import requests
import urllib.parse
from PIL import Image, ImageFilter
from bs4 import BeautifulSoup

# ─────────────────────────────────────────────
# 전화번호 OCR 블러 처리
# ─────────────────────────────────────────────

_ocr_reader = None  # EasyOCR Reader 싱글톤

# 전화번호 정규식 (구분자 제거 후 매칭)
_PHONE_RE = re.compile(
    r'0\d{1,2}\d{7,8}'          # 010·011·02 등 일반 전화
    r'|1[5-9]\d{2}\d{4}'        # 1588·1566 등 대표번호 8자리
    r'|1[5-9]\d{6}'             # 1800·1899 등
)

def _get_ocr_reader():
    """EasyOCR Reader를 최초 1회만 초기화합니다."""
    global _ocr_reader
    if _ocr_reader is None:
        try:
            import easyocr
            print("        [OCR] EasyOCR 초기화 중 (첫 실행 시 모델 다운로드 약 30초)...")
            _ocr_reader = easyocr.Reader(['ko', 'en'], gpu=False, verbose=False)
            print("        [OCR] 초기화 완료")
        except ImportError:
            _ocr_reader = False  # 미설치 표시
            print("        [안내] easyocr 미설치 → 전화번호 제거 건너뜀")
            print("               설치: pip install easyocr")
    return _ocr_reader


def _blur_phone_numbers(image_path):
    """
    이미지에서 전화번호 텍스트 영역을 감지하여 가우시안 블러로 처리합니다.
    """
    reader = _get_ocr_reader()
    if not reader:
        return

    try:
        results = reader.readtext(image_path)
        img = Image.open(image_path).convert("RGB")
        modified = False

        for (bbox, text, _conf) in results:
            # 구분자(공백·하이픈·점·괄호) 제거 후 패턴 매칭
            normalized = re.sub(r'[\s\-\.\(\)\+]', '', text)
            if _PHONE_RE.search(normalized):
                xs = [p[0] for p in bbox]
                ys = [p[1] for p in bbox]
                pad = 10
                x1 = max(0, int(min(xs)) - pad)
                y1 = max(0, int(min(ys)) - pad)
                x2 = min(img.width,  int(max(xs)) + pad)
                y2 = min(img.height, int(max(ys)) + pad)

                region  = img.crop((x1, y1, x2, y2))
                blurred = region.filter(ImageFilter.GaussianBlur(radius=25))
                img.paste(blurred, (x1, y1))
                modified = True
                print(f"        [전화번호 제거] '{text}' → 블러 처리")

        if modified:
            img.save(image_path, quality=95)

    except Exception as e:
        print(f"        [경고] 전화번호 제거 중 오류: {e}")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://www.naver.com/",
    "Accept-Language": "ko-KR,ko;q=0.9",
}

# 청약/분양 글임을 판단하는 키워드
RE_TRIGGER_KEYWORDS = [
    "청약", "분양", "아파트", "단지", "입주", "조감도", "평면도",
    "84㎡", "59㎡", "전용", "분양가", "청약일정"
]

# 아파트 브랜드명 (단지명 추출에 사용)
APT_BRANDS = [
    "자이", "래미안", "아이파크", "푸르지오", "힐스테이트", "롯데캐슬",
    "더샵", "e편한세상", "SK뷰", "호반써밋", "두산위브", "리센츠",
    "트리마제", "아크로", "디에이치", "파크리오", "엘스", "자이르네",
    "아테라", "시그니처", "마크원", "드파인", "오디세이", "더클래스"
]

# 조감도/평면도 검색 유형 (순서 = 우선순위)
IMAGE_SEARCH_TYPES = [
    "{name} 조감도",
    "{name} 평면도 84",
    "{name} 평면도 59",
    "{name} 단지배치도",
    "{name} 모델하우스",
]


# ─────────────────────────────────────────────
# 기본 유틸
# ─────────────────────────────────────────────

def _download_single(url, save_path, min_bytes=15000):
    """
    단일 이미지 URL을 다운로드합니다.
    min_bytes 미만이면 아이콘·광고 이미지로 간주하고 스킵합니다.
    성공 시 True, 실패 시 False 반환.
    """
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        if len(resp.content) < min_bytes:
            return False
        # 이미지 Content-Type 확인
        ct = resp.headers.get("Content-Type", "")
        if not any(t in ct for t in ["image/", "jpeg", "png", "webp"]):
            return False
        with open(save_path, "wb") as f:
            f.write(resp.content)
        _blur_phone_numbers(save_path)
        return True
    except Exception as e:
        print(f"        [경고] 다운로드 실패 ({url[:70]}): {e}")
        return False


# ─────────────────────────────────────────────
# 1. 기사 본문 이미지 추출
# ─────────────────────────────────────────────

def fetch_article_images(news_url, folder_path, start_num=1, max_images=5):
    """
    뉴스 기사 URL의 본문 영역에서 이미지를 추출하여 다운로드합니다.
    다운로드 후 다음 사용 가능한 슬롯 번호를 반환합니다.
    """
    if not news_url:
        return start_num

    print(f"\n[이미지 1단계] 참조 기사 본문 이미지 추출 중...")
    downloaded = 0

    try:
        resp = requests.get(news_url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')

        # 네이버 뉴스 본문 영역 우선순위
        body = (
            soup.select_one('#dic_area') or
            soup.select_one('#newsct_article') or
            soup.select_one('.news_end_body') or
            soup.select_one('article')
        )
        if not body:
            print("     [경고] 기사 본문 영역을 찾지 못했습니다.")
            return start_num

        for img in body.find_all('img'):
            if downloaded >= max_images:
                break

            # data-src 우선, 없으면 src
            img_url = img.get('data-src') or img.get('data-lazy-src') or img.get('src') or ''
            img_url = img_url.strip()

            if not img_url or img_url.startswith('data:'):
                continue
            if img_url.startswith('//'):
                img_url = 'https:' + img_url
            if not img_url.startswith('http'):
                continue

            # 아이콘성 URL 스킵 (emoji, icon, logo 등)
            if any(skip in img_url.lower() for skip in ['icon', 'logo', 'emoji', 'transparent', 'blank']):
                continue

            num = start_num + downloaded
            save_path = os.path.join(folder_path, f"{num}.jpg")
            print(f"     -> 기사 이미지 [{num}] 다운로드 중...")

            if _download_single(img_url, save_path):
                downloaded += 1

        print(f"     [완료] 기사 이미지 {downloaded}장 수집")

    except Exception as e:
        print(f"     [경고] 기사 이미지 추출 중 오류: {e}")

    return start_num + downloaded


# ─────────────────────────────────────────────
# 2. 네이버 이미지 검색 (조감도·평면도)
# ─────────────────────────────────────────────

def _search_naver_images(query, max_urls=4):
    """
    네이버 이미지 검색으로 이미지 URL 목록을 반환합니다.
    네이버 검색 결과 HTML의 스크립트 내 JSON 데이터를 파싱합니다.
    """
    encoded = urllib.parse.quote(query)

    # 방법 A: 네이버 이미지 검색 API 스타일 엔드포인트
    api_url = (
        f"https://s.search.naver.com/p/image/search.naver"
        f"?where=image&query={encoded}&start=1&display=10&sm=tab_pge"
    )
    try:
        resp = requests.get(api_url, headers=HEADERS, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            items = data.get('items', [])
            urls = [item.get('link', '') or item.get('thumbnail', '') for item in items]
            urls = [u for u in urls if u.startswith('http')]
            if urls:
                return urls[:max_urls]
    except Exception:
        pass

    # 방법 B: 일반 검색 페이지 HTML에서 originalUrl 패턴 추출
    try:
        page_url = f"https://search.naver.com/search.naver?where=image&query={encoded}"
        resp2 = requests.get(page_url, headers=HEADERS, timeout=15)
        html = resp2.text

        # 네이버 이미지 검색 결과 JSON 내 originalUrl / thumbnail 패턴
        patterns = [
            r'"originalUrl"\s*:\s*"(https?://[^"]+\.(?:jpg|jpeg|png|webp)[^"]*)"',
            r'"imageUrl"\s*:\s*"(https?://[^"]+\.(?:jpg|jpeg|png|webp)[^"]*)"',
            r'"thumbnail"\s*:\s*"(https?://[^"]+)"',
        ]
        urls = []
        for pat in patterns:
            found = re.findall(pat, html)
            for u in found:
                u_clean = u.replace('\\u0026', '&').replace('\\/', '/')
                if u_clean not in urls:
                    urls.append(u_clean)
            if len(urls) >= max_urls * 2:
                break

        # 이미지 파일 확장자가 있는 것만 우선 필터
        real_imgs = [u for u in urls if re.search(r'\.(jpg|jpeg|png|webp)', u, re.I)]
        result = (real_imgs or urls)[:max_urls]
        return result

    except Exception as e:
        print(f"        [경고] 네이버 이미지 검색 실패 ({query}): {e}")
        return []


def _extract_apt_names(content_text):
    """
    블로그 원고 텍스트에서 아파트 단지명을 추출합니다.
    브랜드명 기반 패턴 매칭 + 따옴표/꺽쇠 안의 단지명 패턴 적용.
    """
    names = []

    # 패턴 1: 브랜드명을 포함하는 단지명
    for brand in APT_BRANDS:
        pattern = rf'[가-힣A-Za-z0-9\s]{{1,10}}{re.escape(brand)}[가-힣A-Za-z0-9\s]{{0,10}}'
        matches = re.findall(pattern, content_text)
        for m in matches:
            name = m.strip().replace('\n', ' ')
            name = re.sub(r'\s+', ' ', name)[:25]
            if name and name not in names:
                names.append(name)

    # 패턴 2: '단지명' 또는 「단지명」 형식
    quoted = re.findall(r"['‘’“”「」『』'\"']([\w가-힣\s]+아파트|[\w가-힣\s]+단지)['‘’“”「」『』'\"\']", content_text)
    for q in quoted:
        name = q.strip()[:25]
        if name and name not in names:
            names.append(name)

    return names[:3]  # 최대 3개 단지만


def fetch_realestate_images(content_text, folder_path, start_num=1, max_images=6):
    """
    블로그 원고에서 단지명을 추출하고 조감도·평면도·배치도를 검색하여 다운로드합니다.
    청약/분양 관련 글이 아니면 건너뜁니다.
    다운로드 후 다음 사용 가능한 슬롯 번호를 반환합니다.
    """
    if not any(kw in content_text for kw in RE_TRIGGER_KEYWORDS):
        print("[이미지 2단계] 청약/분양 글이 아니어서 부동산 특화 이미지 검색을 건너뜁니다.")
        return start_num

    print(f"\n[이미지 2단계] 조감도·평면도 검색 시작...")

    apt_names = _extract_apt_names(content_text)
    if not apt_names:
        # 단지명을 찾지 못한 경우 일반 검색어로 폴백
        apt_names = ["신규 아파트"]
        print("     [안내] 단지명을 찾지 못해 일반 검색으로 진행합니다.")
    else:
        print(f"     발견된 단지명: {apt_names}")

    downloaded = 0

    for apt_name in apt_names:
        if downloaded >= max_images:
            break

        for search_template in IMAGE_SEARCH_TYPES:
            if downloaded >= max_images:
                break

            query = search_template.format(name=apt_name)
            print(f"     -> 검색: '{query}'")

            img_urls = _search_naver_images(query, max_urls=2)

            for img_url in img_urls:
                if downloaded >= max_images:
                    break
                num = start_num + downloaded
                save_path = os.path.join(folder_path, f"{num}.jpg")
                print(f"        이미지 [{num}] 다운로드 중...")
                if _download_single(img_url, save_path, min_bytes=20000):
                    downloaded += 1
                time.sleep(0.3)  # 서버 부하 방지

    print(f"     [완료] 부동산 특화 이미지 {downloaded}장 수집")
    return start_num + downloaded


# ─────────────────────────────────────────────
# 통합 진입점
# ─────────────────────────────────────────────

def fetch_all_real_images(news_url, content_text, folder_path,
                          max_article=4, max_realestate=5):
    """
    기사 이미지와 부동산 특화 이미지를 순서대로 수집합니다.
    반환값: 다음으로 Leonardo 가 사용할 시작 슬롯 번호 (int)

    슬롯 구성 예시 (총 15장):
      1~4   : 기사 본문 이미지 (실제 뉴스 사진)
      5~9   : 조감도·평면도 (부동산 특화)
      10~15 : Leonardo AI 생성 이미지 (분위기·스토리 보완)
    """
    print("\n" + "=" * 50)
    print("  실제 이미지 수집 단계")
    print("=" * 50)

    next_num = fetch_article_images(
        news_url, folder_path,
        start_num=1, max_images=max_article
    )
    next_num = fetch_realestate_images(
        content_text, folder_path,
        start_num=next_num, max_images=max_realestate
    )

    print(f"\n[이미지 수집 완료] 실제 이미지 {next_num - 1}장 저장됨. "
          f"Leonardo AI는 {next_num}번부터 채웁니다.")
    return next_num
