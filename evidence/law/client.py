# -*- coding: utf-8 -*-
"""
법제처 국가법령정보 OPEN API 클라이언트.

법전을 모델에게 외우게 하는 대신, 필요한 조문과 판례를 **실제로 내려받아**
근거로 쓴다. AI가 판례를 지어내는 문제는 실제로 전 세계 법정에서 제재로
이어졌고(2026년 6월까지 집계된 환각 인용 사건만 1,598건), 그중에는
존재하지 않는 판례 20개를 인용해 정직 처분을 받은 사례도 있다.

인증키(OC)는 open.law.go.kr에서 무료로 발급받아 .env에 LAW_OC로 넣는다.

받아온 원문은 로컬에 캐시한다. 같은 조문을 반복해서 요청하면
공공 API에 부담만 주고 느려진다.
"""
import json
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from .. import config

BASE_LIST = "https://www.law.go.kr/DRF/lawSearch.do"
BASE_INFO = "https://www.law.go.kr/DRF/lawService.do"
VIEW_LAW = "https://www.law.go.kr/법령/{name}"
VIEW_PREC = "https://www.law.go.kr/판례/({case_no})"

MIN_INTERVAL = 0.4          # 요청 간 최소 간격 (공공 API 예의)
_last_call = 0.0


class LawApiError(RuntimeError):
    pass


def configured() -> tuple[bool, str]:
    if not config.LAW_OC:
        return False, (".env에 LAW_OC가 없습니다. "
                       "open.law.go.kr → OPEN API → 활용신청에서 무료로 발급받으세요.")
    if not config.ALLOW_LAW_API:
        return False, "ALLOW_LAW_API가 꺼져 있습니다."
    return True, ""


def _cache_path(kind: str, key: str) -> Path:
    safe = re.sub(r"[^\w가-힣]+", "_", key)[:120]
    d = config.LAW_CACHE_DIR / kind
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{safe}.json"


def _request(url: str, params: dict, cache_kind: str = None,
             cache_key: str = None, force: bool = False) -> str:
    """
    API 호출. 캐시가 있으면 그것을 쓴다.

    증거 분석은 같은 조문을 여러 번 들여다보므로 캐시가 크게 효과적이다.
    """
    global _last_call

    cache = _cache_path(cache_kind, cache_key) if cache_kind and cache_key else None
    if cache and cache.exists() and not force:
        try:
            return json.loads(cache.read_text(encoding="utf-8"))["body"]
        except Exception:
            pass

    ok, why = configured()
    if not ok:
        raise LawApiError(why)

    import requests

    gap = time.time() - _last_call
    if gap < MIN_INTERVAL:
        time.sleep(MIN_INTERVAL - gap)

    params = {"OC": config.LAW_OC, "type": "XML", **params}
    try:
        r = requests.get(url, params=params, timeout=30)
        _last_call = time.time()
        r.raise_for_status()
    except Exception as e:
        raise LawApiError(f"법령 API 호출 실패: {e}") from e

    body = r.text
    if cache:
        cache.write_text(
            json.dumps({"body": body, "fetched_at": time.time()}, ensure_ascii=False),
            encoding="utf-8")
    return body


def _text(node, *names) -> str:
    """XML 노드에서 첫 번째로 발견되는 값. 태그명이 버전마다 조금씩 다르다."""
    for n in names:
        el = node.find(n)
        if el is not None and (el.text or "").strip():
            return el.text.strip()
    return ""


def _clean(html: str) -> str:
    """조문 본문에 섞인 태그와 개체를 정리한다."""
    t = re.sub(r"<br\s*/?>", "\n", html or "", flags=re.I)
    t = re.sub(r"<[^>]+>", "", t)
    t = (t.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
          .replace("&quot;", '"').replace("&nbsp;", " "))
    return re.sub(r"[ \t]+", " ", t).strip()


# ─────────────────────────────────────────────────────────
# 법령 조문
# ─────────────────────────────────────────────────────────
def find_law(name: str) -> dict | None:
    """법령명으로 법령 ID를 찾는다."""
    body = _request(BASE_LIST, {"target": "law", "query": name, "display": 5},
                    "law_search", name)
    try:
        root = ET.fromstring(body)
    except ET.ParseError as e:
        raise LawApiError(f"법령 검색 응답을 해석하지 못했습니다: {e}") from e

    for item in root.findall(".//law"):
        found = _text(item, "법령명한글", "법령명")
        if not found:
            continue
        # 정확히 일치하는 것을 우선한다 ("민법"을 찾을 때 "민법시행령"이 아니라)
        if found.replace(" ", "") == name.replace(" ", ""):
            return {
                "name": found,
                "law_id": _text(item, "법령ID", "법령일련번호"),
                "mst": _text(item, "법령일련번호", "법령ID"),
                "enforce_date": _text(item, "시행일자"),
            }
    first = root.find(".//law")
    if first is None:
        return None
    return {
        "name": _text(first, "법령명한글", "법령명"),
        "law_id": _text(first, "법령ID", "법령일련번호"),
        "mst": _text(first, "법령일련번호", "법령ID"),
        "enforce_date": _text(first, "시행일자"),
    }


def fetch_articles(law_name: str) -> list[dict]:
    """
    법령 하나의 조문을 조 단위로 모두 가져온다.

    조·항·호·목까지 원문 그대로 받아야 "제25조 제1항"처럼 정확히
    인용할 수 있다.
    """
    info = find_law(law_name)
    if not info:
        raise LawApiError(f"법령을 찾지 못했습니다: {law_name}")

    body = _request(BASE_INFO,
                    {"target": "law", "MST": info["mst"]},
                    "law_body", f"{law_name}_{info['mst']}")
    try:
        root = ET.fromstring(body)
    except ET.ParseError as e:
        raise LawApiError(f"법령 본문을 해석하지 못했습니다: {e}") from e

    out = []
    for jo in root.findall(".//조문단위"):
        no = _text(jo, "조문번호")
        if not no:
            continue
        gaji = _text(jo, "조문가지번호")
        article_no = f"제{no}조" + (f"의{gaji}" if gaji else "")

        title = _text(jo, "조문제목")
        parts = [_clean(_text(jo, "조문내용"))]

        # 항·호·목까지 붙인다
        for hang in jo.findall(".//항"):
            htxt = _clean(_text(hang, "항내용"))
            if htxt:
                parts.append(htxt)
            for ho in hang.findall(".//호"):
                otxt = _clean(_text(ho, "호내용"))
                if otxt:
                    parts.append("  " + otxt)
                for mok in ho.findall(".//목"):
                    mtxt = _clean(_text(mok, "목내용"))
                    if mtxt:
                        parts.append("    " + mtxt)

        text = "\n".join(p for p in parts if p).strip()
        if not text:
            continue
        out.append({
            "law_name": info["name"],
            "law_id": info["law_id"],
            "article_no": article_no,
            "article_title": title,
            "body": text,
            "enforce_date": info.get("enforce_date"),
            "source_url": VIEW_LAW.format(name=info["name"]) + f"/{article_no}",
        })
    return out


def fetch_article(law_name: str, article_no: str) -> dict | None:
    """
    특정 조문 하나를 확인한다. 인용 검증의 핵심 경로.
    실제로 존재하는지, 현행인지 확인한다.
    """
    want = re.sub(r"\s+", "", article_no)
    for a in fetch_articles(law_name):
        if re.sub(r"\s+", "", a["article_no"]) == want:
            return a
    return None


# ─────────────────────────────────────────────────────────
# 판례
# ─────────────────────────────────────────────────────────
def search_precedents(query: str, limit: int = 10) -> list[dict]:
    """검색어로 판례 목록을 가져온다."""
    body = _request(BASE_LIST,
                    {"target": "prec", "query": query, "display": limit},
                    "prec_search", f"{query}_{limit}")
    try:
        root = ET.fromstring(body)
    except ET.ParseError as e:
        raise LawApiError(f"판례 검색 응답을 해석하지 못했습니다: {e}") from e

    out = []
    for item in root.findall(".//prec"):
        case_no = _text(item, "사건번호")
        if not case_no:
            continue
        out.append({
            "prec_id": _text(item, "판례일련번호"),
            "case_no": case_no,
            "case_name": _text(item, "사건명"),
            "court": _text(item, "법원명"),
            "decided_on": _text(item, "선고일자"),
        })
    return out


def fetch_precedent(prec_id: str = None, case_no: str = None) -> dict | None:
    """
    판례 본문을 가져온다. 판시사항·판결요지가 인용의 근거가 된다.

    사건번호만 아는 경우(모델이 인용한 경우 등)에는 먼저 검색해
    일련번호를 찾은 뒤 본문을 받는다. 검색에서 안 나오면
    **존재하지 않는 판례**이므로 인용을 차단해야 한다.
    """
    if not prec_id:
        if not case_no:
            return None
        found = [p for p in search_precedents(case_no, limit=10)
                 if _norm_case(p["case_no"]) == _norm_case(case_no)]
        if not found:
            return None
        prec_id = found[0]["prec_id"]
        case_no = found[0]["case_no"]

    body = _request(BASE_INFO, {"target": "prec", "ID": prec_id},
                    "prec_body", str(prec_id))
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return None

    node = root.find(".//PrecService") or root
    got_case = _text(node, "사건번호") or case_no or ""
    if not got_case:
        return None

    return {
        "case_no": got_case,
        "case_name": _text(node, "사건명"),
        "court": _text(node, "법원명"),
        "decided_on": _text(node, "선고일자"),
        "holding": _clean(_text(node, "판시사항")),
        "summary": _clean(_text(node, "판결요지")),
        "body": _clean(_text(node, "판례내용")),
        "source_url": VIEW_PREC.format(case_no=got_case),
    }


# 사건번호 형태:  2011다109357 · 2020도1234 · 2019헌바12 · 2018누5678
CASE_NO_RE = re.compile(r"(\d{4})\s*([가-힣]{1,3})\s*(\d{1,6})")


def _norm_case(s: str) -> str:
    """
    사건번호만 뽑아 정규화한다.

    "대법원 2011. 7. 14. 선고 2011다109357 판결" 처럼 법원명과 선고일이
    앞뒤에 붙어 오는 경우가 많다. 번호 부분만 떼어 비교해야 대조가 된다.
    """
    m = CASE_NO_RE.search(s or "")
    if m:
        return f"{m.group(1)}{m.group(2)}{m.group(3)}"
    return re.sub(r"[\s.\-]", "", s or "")


def exists_precedent(case_no: str) -> bool:
    """
    사건번호가 실제로 존재하는지 확인한다.
    인용 검증 게이트가 쓰는 함수이며, 여기서 False면 코멘트를 막는다.
    """
    try:
        found = search_precedents(case_no, limit=10)
    except LawApiError:
        raise
    return any(_norm_case(p["case_no"]) == _norm_case(case_no) for p in found)
