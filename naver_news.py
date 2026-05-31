import re
import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

def _fetch_article(news_url):
    """기사 URL에서 제목, 본문, BeautifulSoup 객체를 반환합니다."""
    news_resp = requests.get(news_url, headers=HEADERS)
    news_resp.raise_for_status()
    news_soup = BeautifulSoup(news_resp.text, 'html.parser')

    title_el = news_soup.select_one('#title_area') or news_soup.select_one('.media_end_head_title')
    title = title_el.get_text(strip=True) if title_el else "제목 없음"

    body_el = news_soup.select_one('#dic_area') or news_soup.select_one('#newsct_article')
    body = body_el.get_text(strip=True) if body_el else "본문 없음"

    news_content = f"기사 제목: {title}\n\n기사 본문:\n{body}"
    return title, news_content, news_url


def get_top_real_estate_news():
    """
    네이버 뉴스 경제 섹션(sectionId=101) 많이 본 뉴스 중
    부동산 관련 기사를 찾아 (title, content, url) 로 반환합니다.
    해당 기사가 없으면 키워드 검색으로 폴백합니다.
    """
    REALESTATE_KEYWORDS = [
        "아파트", "부동산", "청약", "분양", "주택", "전세", "월세",
        "재건축", "재개발", "임대", "매매", "공급", "입주", "단지"
    ]

    ranking_url = "https://news.naver.com/main/ranking/popularDay.naver?sectionId=101"

    print("[시스템] 네이버 뉴스 경제 섹션 랭킹 페이지 접속 중...")
    try:
        response = requests.get(ranking_url, headers=HEADERS)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')

        article_links = soup.select('.rankingnews_list .list_content a')
        if not article_links:
            print("[시스템] 경제 섹션 랭킹에서 링크를 찾지 못했습니다. 키워드 검색으로 전환합니다.")
            return get_news_by_keyword("아파트 청약 분양")

        news_url = None
        for link in article_links:
            candidate_title = link.get_text(strip=True)
            if any(kw in candidate_title for kw in REALESTATE_KEYWORDS):
                news_url = link['href']
                print(f"[시스템] 부동산 관련 뉴스 발견: {candidate_title}")
                break

        if not news_url:
            print("[시스템] 경제 섹션 상위 뉴스에 부동산 관련 기사가 없습니다. 키워드 검색으로 전환합니다.")
            return get_news_by_keyword("아파트 청약 분양")

        print(f"[시스템] 선택된 뉴스 URL: {news_url}")
        return _fetch_article(news_url)

    except Exception as e:
        print(f"[오류] 뉴스 크롤링 중 문제 발생: {e}")
        return None, None, None


def get_news_by_keyword(keyword):
    """
    네이버 뉴스 검색으로 키워드 관련 최상단 기사를 가져옵니다.
    (title, content, url) 로 반환합니다.
    """
    search_url = f"https://search.naver.com/search.naver?where=news&query={keyword}"

    print(f"[시스템] '{keyword}' 관련 네이버 뉴스를 검색 중...")
    try:
        response = requests.get(search_url, headers=HEADERS)
        response.raise_for_status()

        links = re.findall(r'href="(https://n\.news\.naver\.com/mnews/article/[^"]+)"', response.text)
        if not links:
            return None, "관련된 네이버 뉴스 링크를 찾을 수 없습니다.", None

        news_url = links[0].replace("&amp;", "&")
        print(f"[시스템] 최상단 뉴스 발견: {news_url}")
        return _fetch_article(news_url)

    except Exception as e:
        print(f"[오류] 뉴스 검색 중 문제 발생: {e}")
        return None, None, None


def get_trending_realestate_topics(n=6):
    """
    네이버 뉴스 경제 섹션 랭킹에서 부동산 관련 인기 뉴스 제목 목록을 반환합니다.
    Returns: list of dict {title, url}
    """
    REALESTATE_KW = [
        "아파트", "부동산", "청약", "분양", "주택", "전세", "월세",
        "재건축", "재개발", "임대", "매매", "공급", "입주", "단지",
        "금리", "대출", "규제", "상가", "오피스텔",
    ]
    results = []

    try:
        resp = requests.get(
            "https://news.naver.com/main/ranking/popularDay.naver?sectionId=101",
            headers=HEADERS, timeout=10,
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for link in soup.select(".rankingnews_list .list_content a"):
            title = link.get_text(strip=True)
            if title and any(kw in title for kw in REALESTATE_KW):
                results.append({"title": title, "url": link.get("href", "")})
            if len(results) >= n:
                break
    except Exception:
        pass

    search_queries = ["아파트 청약", "부동산 전세", "재건축 분양", "주택 대출"]
    for q in search_queries:
        if len(results) >= n:
            break
        try:
            resp = requests.get(
                f"https://search.naver.com/search.naver?where=news&query={q}&sort=1",
                headers=HEADERS, timeout=10,
            )
            for m in re.finditer(r'class="news_tit"[^>]*title="([^"]+)"', resp.text):
                title = m.group(1).strip()
                if title and any(kw in title for kw in REALESTATE_KW):
                    if not any(r["title"] == title for r in results):
                        results.append({"title": title, "url": ""})
                if len(results) >= n:
                    break
        except Exception:
            continue

    return results[:n]


if __name__ == "__main__":
    title, content, url = get_top_real_estate_news()
    if title:
        print(f"\n[성공] 크롤링된 뉴스 제목: {title}")
        print(f"URL: {url}")
        print(f"본문 미리보기: {content[:200]}...")
