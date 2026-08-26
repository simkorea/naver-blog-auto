# -*- coding: utf-8 -*-
"""
법제처 응답 파싱 검증.

여기가 유일하게 실제 응답으로 확인하지 못한 곳이다. 인증키가 없어
호출을 못 하고, 필드명(`법령명한글`, `조문번호`, `판시사항` …)은
문서만 보고 적었다.

그래서 응답 형태를 흉내낸 XML로 파싱을 검증하고, 필드명이 조금
다르거나 태그가 빠져도 죽지 않는지 함께 본다. 실제 응답이 예상과
다르면 결국 사용자 PC에서 드러나겠지만, 적어도 **깨진 응답에
프로그램이 멈추지는 않게** 해둔다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from conftest import Check, use_temp_db

LAW_SEARCH = """<?xml version="1.0" encoding="UTF-8"?>
<LawSearch>
  <law>
    <법령명한글>민법시행령</법령명한글>
    <법령ID>001</법령ID><법령일련번호>1001</법령일련번호>
    <시행일자>20200101</시행일자>
  </law>
  <law>
    <법령명한글>민법</법령명한글>
    <법령ID>002</법령ID><법령일련번호>1002</법령일련번호>
    <시행일자>19600101</시행일자>
  </law>
</LawSearch>"""

LAW_BODY = """<?xml version="1.0" encoding="UTF-8"?>
<법령>
  <조문>
    <조문단위>
      <조문번호>750</조문번호>
      <조문제목>불법행위의 내용</조문제목>
      <조문내용>제750조(불법행위의 내용) 고의 또는 과실로 인한 위법행위로
        타인에게 손해를 가한 자는 그 손해를 배상할 책임이 있다.</조문내용>
    </조문단위>
    <조문단위>
      <조문번호>25</조문번호>
      <조문가지번호>2</조문가지번호>
      <조문제목>확인·설명의무</조문제목>
      <조문내용>제25조의2(확인·설명의무) 개업공인중개사는 다음과 같이 한다.</조문내용>
      <항>
        <항내용>① 중개대상물의 상태를 확인하여야 한다.</항내용>
        <호>
          <호내용>1. 권리관계</호내용>
          <목><목내용>가. 소유권</목내용></목>
        </호>
      </항>
    </조문단위>
    <조문단위><조문제목>번호 없는 조문</조문제목></조문단위>
  </조문>
</법령>"""

PREC_SEARCH = """<?xml version="1.0" encoding="UTF-8"?>
<PrecSearch>
  <prec>
    <판례일련번호>77777</판례일련번호>
    <사건번호>2011다109357</사건번호>
    <사건명>손해배상(기)</사건명>
    <법원명>대법원</법원명>
    <선고일자>20120126</선고일자>
  </prec>
  <prec><사건명>사건번호 없는 항목</사건명></prec>
</PrecSearch>"""

PREC_BODY = """<?xml version="1.0" encoding="UTF-8"?>
<PrecService>
  <사건번호>2011다109357</사건번호>
  <사건명>손해배상(기)</사건명>
  <법원명>대법원</법원명>
  <선고일자>20120126</선고일자>
  <판시사항>중개업자의 확인·설명의무 위반과 손해배상책임의 범위</판시사항>
  <판결요지>중개업자는 &lt;중개대상물&gt;의 권리관계를 성실하게<br/>설명할 의무가 있다.</판결요지>
  <판례내용>【원고, 피상고인】 …</판례내용>
</PrecService>"""

BROKEN = ["", "not xml at all", "<html><body>서비스 점검중</body></html>",
          "<?xml version='1.0'?><LawSearch></LawSearch>"]


def run(tmp_path) -> bool:
    config = use_temp_db(tmp_path)
    from evidence.law import client

    c = Check("법제처 응답 파싱")

    # 실제 호출 대신 준비한 응답을 돌려준다
    responses = {}

    def fake_request(url, params, cache_kind=None, cache_key=None, force=False):
        target = params.get("target")
        if target == "law":
            return responses["law_body" if "MST" in params else "law_search"]
        if target == "prec":
            return responses["prec_body" if "ID" in params else "prec_search"]
        return ""

    client._request = fake_request
    responses.update(law_search=LAW_SEARCH, law_body=LAW_BODY,
                     prec_search=PREC_SEARCH, prec_body=PREC_BODY)

    # ── 법령 찾기 ────────────────────────────
    found = client.find_law("민법")
    c.eq(found["name"], "민법",
         "이름이 정확히 같은 법령을 고른다 (민법시행령이 먼저 와도)")
    c.eq(found["mst"], "1002", "법령일련번호를 뽑는다")

    # ── 조문 ────────────────────────────────
    arts = client.fetch_articles("민법")
    c.eq(len(arts), 2, "번호 없는 조문은 건너뛴다")

    a750 = next(a for a in arts if a["article_no"] == "제750조")
    c.eq(a750["article_title"], "불법행위의 내용", "조문 제목을 뽑는다")
    c.ok("손해를 배상할 책임" in a750["body"], "조문 본문을 뽑는다")

    a25 = next(a for a in arts if "제25조" in a["article_no"])
    c.eq(a25["article_no"], "제25조의2", "가지번호를 조문번호에 반영한다")
    for label, needle in (("항", "중개대상물의 상태"), ("호", "권리관계"),
                          ("목", "소유권")):
        c.ok(needle in a25["body"], f"{label}까지 본문에 담는다")

    c.ok(a750["source_url"].endswith("제750조"), "출처 주소를 만든다")

    # ── 판례 ────────────────────────────────
    precs = client.search_precedents("확인설명의무")
    c.eq(len(precs), 1, "사건번호 없는 항목은 건너뛴다")
    c.eq(precs[0]["case_no"], "2011다109357", "사건번호를 뽑는다")

    detail = client.fetch_precedent(prec_id="77777")
    c.eq(detail["court"], "대법원", "법원명을 뽑는다")
    c.ok("손해배상책임의 범위" in detail["holding"], "판시사항을 뽑는다")
    c.ok("<중개대상물>" in detail["summary"], "HTML 개체를 되돌린다")
    c.ok("\n" in detail["summary"], "<br>을 줄바꿈으로 바꾼다")
    c.ok("<br" not in detail["summary"], "태그가 남지 않는다")

    # 사건번호만 알고 있을 때
    by_no = client.fetch_precedent(case_no="대법원 2011. 7. 14. 선고 2011다109357 판결")
    c.ok(by_no is not None, "법원명·선고일이 붙은 사건번호로도 찾는다")

    c.eq(client.exists_precedent("2011다109357"), True, "실존 판례를 확인한다")
    c.eq(client.exists_precedent("2099다999999"), False,
         "없는 판례는 없다고 답한다")

    # ── 깨진 응답 ────────────────────────────
    for i, bad in enumerate(BROKEN):
        responses.update(law_search=bad, law_body=bad,
                         prec_search=bad, prec_body=bad)
        label = (bad[:24] + "…") if len(bad) > 24 else (bad or "(빈 응답)")

        try:
            got = client.find_law("민법")
            c.ok(got is None, f"깨진 응답 {i+1}: 법령 검색이 조용히 실패한다",
                 f"{label} → {got}")
        except client.LawApiError:
            c.ok(True, f"깨진 응답 {i+1}: 법령 검색이 안내를 남기고 실패한다")
        except Exception as e:
            c.ok(False, f"깨진 응답 {i+1}: 법령 검색",
                 f"{label} → 예상 못 한 {type(e).__name__}: {e}")

        try:
            client.search_precedents("아무거나")
            c.ok(True, f"깨진 응답 {i+1}: 판례 검색이 죽지 않는다")
        except client.LawApiError:
            c.ok(True, f"깨진 응답 {i+1}: 판례 검색이 안내를 남기고 실패한다")
        except Exception as e:
            c.ok(False, f"깨진 응답 {i+1}: 판례 검색",
                 f"{label} → 예상 못 한 {type(e).__name__}: {e}")

        try:
            got = client.fetch_precedent(prec_id="1")
            c.ok(got is None, f"깨진 응답 {i+1}: 판례 본문이 None을 돌려준다")
        except client.LawApiError:
            c.ok(True, f"깨진 응답 {i+1}: 판례 본문이 안내를 남기고 실패한다")
        except Exception as e:
            c.ok(False, f"깨진 응답 {i+1}: 판례 본문",
                 f"{label} → 예상 못 한 {type(e).__name__}: {e}")

    return c.report()


if __name__ == "__main__":
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        sys.exit(0 if run(Path(d)) else 1)
