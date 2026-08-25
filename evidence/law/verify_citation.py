# -*- coding: utf-8 -*-
"""
인용 검증 게이트 — 지어낸 법을 내보내지 않기 위한 마지막 관문.

AI가 판례와 조문을 지어내는 문제는 가설이 아니다. 실제로 전 세계 법정에서
제재로 이어졌고, 준비서면 인용 63개 중 57개가 잘못됐고 그중 20개가 존재하지
않는 판례여서 변호사가 정직된 사례까지 있다. 문제는 지어낸 인용이
"전문적인 문장과 올바른 형식"을 갖춰 진짜처럼 보인다는 점이다.

그래서 여기서는 **문장을 믿지 않고 전부 다시 조회한다.**

검증 단계
  1. 코멘트가 참조한 ref_id가 DB에 실제로 있는가
  2. 그 조문·판례를 법제처 API로 재조회했을 때 실존하는가
  3. 코멘트 본문에 모델이 임의로 적어 넣은 법령명·사건번호가 있는가
     → 정규식으로 전수 추출해 하나하나 대조
  4. 하나라도 실패하면 citation_status = 'blocked'
     화면에는 코멘트 대신 차단 사유가 뜬다
"""
import re
from datetime import datetime

from .. import db, integrity
from . import client

# 본문에 몰래 끼어든 인용을 찾아낸다.
#   "민법 제750조", "공인중개사법 제25조 제1항"
# 법령명은 "민법"처럼 두 글자짜리도 있으므로 앞부분을 1글자부터 허용한다.
LAW_CITE_RE = re.compile(
    r"([가-힣]{1,19}(?:법률|시행령|시행규칙|법|규칙|령))\s*"
    r"(제\s*\d+\s*조(?:의\s*\d+)?(?:\s*제\s*\d+\s*항)?)"
)
#   "대법원 2011다109357", "2011다109357 판결"
PREC_CITE_RE = client.CASE_NO_RE


class Blocked(Exception):
    """검증에 실패해 출력을 막았다."""


# ─────────────────────────────────────────────────────────
# 개별 검증
# ─────────────────────────────────────────────────────────
def check_article_ref(conn, ref_id: int, online: bool = True) -> tuple[bool, str]:
    row = conn.execute(
        "SELECT law_name, article_no, source_url FROM law_articles WHERE id = ?",
        (ref_id,)).fetchone()
    if not row:
        return False, f"참조한 조문(id={ref_id})이 자료에 없습니다"

    if not online:
        return True, ""
    try:
        found = client.fetch_article(row["law_name"], row["article_no"])
    except client.LawApiError as e:
        # API를 못 쓰는 상황이면 '검증 못 함'이지 '통과'가 아니다
        return False, f"실존 확인 불가 ({e})"
    if not found:
        return False, f"{row['law_name']} {row['article_no']} 은(는) 현행 법령에 없습니다"
    return True, ""


def check_precedent_ref(conn, ref_id: int, online: bool = True) -> tuple[bool, str]:
    row = conn.execute(
        "SELECT case_no FROM precedents WHERE id = ?", (ref_id,)).fetchone()
    if not row:
        return False, f"참조한 판례(id={ref_id})가 자료에 없습니다"

    if not online:
        return True, ""
    try:
        if not client.exists_precedent(row["case_no"]):
            return False, f"사건번호 {row['case_no']} 판례가 실제로 존재하지 않습니다"
    except client.LawApiError as e:
        return False, f"실존 확인 불가 ({e})"
    return True, ""


def scan_text_citations(conn, text: str, online: bool = True) -> list[dict]:
    """
    코멘트 본문을 훑어 모델이 임의로 적어 넣은 인용을 찾아 검증한다.

    이게 없으면 '근거 목록'은 멀쩡한데 본문에 가짜 판례가 섞여 나가는
    구멍이 남는다. 실제 사고가 그렇게 났다.
    """
    out = []

    for law, article in LAW_CITE_RE.findall(text or ""):
        cited = re.sub(r"\s+", "", f"{law} {article}")
        article = re.sub(r"\s+", "", article)
        # 항까지 붙어 있으면 조 단위로 잘라 확인한다 (법령 API는 조 단위)
        base = re.match(r"(제\d+조(?:의\d+)?)", article)
        base_no = base.group(1) if base else article

        known = conn.execute(
            "SELECT id FROM law_articles WHERE law_name = ? "
            "AND REPLACE(article_no, ' ', '') = ?",
            (law, base_no),
        ).fetchone()

        if known:
            out.append({"kind": "article", "cited": cited, "ok": True, "reason": ""})
            continue

        # 우리가 받아둔 자료에 없는 조문이다. 실제로 있는지 직접 확인한다.
        if not online:
            out.append({"kind": "article", "cited": cited, "ok": False,
                        "reason": "인용된 조문을 확인하지 못했습니다(오프라인)"})
            continue
        try:
            found = client.fetch_article(law, base_no)
            if found is None:
                out.append({"kind": "article", "cited": cited, "ok": False,
                            "reason": f"{law} {base_no} 은(는) 현행 법령에 없습니다"})
            else:
                out.append({"kind": "article", "cited": cited, "ok": True, "reason": ""})
        except client.LawApiError as e:
            out.append({"kind": "article", "cited": cited, "ok": False,
                        "reason": f"실존 확인 불가 ({e})"})

    seen = set()
    for m in PREC_CITE_RE.finditer(text or ""):
        case_no = f"{m.group(1)}{m.group(2)}{m.group(3)}"
        if case_no in seen:
            continue
        seen.add(case_no)
        ok, why = True, ""
        if online:
            try:
                if not client.exists_precedent(case_no):
                    ok, why = False, f"사건번호 {case_no} 판례가 실제로 존재하지 않습니다"
            except client.LawApiError as e:
                ok, why = False, f"실존 확인 불가 ({e})"
        else:
            ok, why = False, "인용된 판례를 확인하지 못했습니다(오프라인)"
        out.append({"kind": "precedent", "cited": case_no,
                    "ok": ok, "reason": why})

    return out


# ─────────────────────────────────────────────────────────
# 코멘트 단위 검증
# ─────────────────────────────────────────────────────────
def verify_comment(conn, comment_id: int, online: bool = True) -> dict:
    """
    코멘트 하나를 검증하고 결과를 DB에 반영한다.
    통과하지 못하면 citation_status='blocked'이 되어 화면에 뜨지 않는다.
    """
    c = conn.execute("SELECT * FROM comments WHERE id = ?", (comment_id,)).fetchone()
    if not c:
        raise ValueError(f"코멘트를 찾을 수 없습니다: {comment_id}")

    problems = []
    now = datetime.now().isoformat(timespec="seconds")

    cites = conn.execute(
        "SELECT * FROM comment_citations WHERE comment_id = ?", (comment_id,)
    ).fetchall()

    if not cites:
        problems.append("근거로 든 조문·판례가 하나도 없습니다")

    for cite in cites:
        if cite["ref_type"] == "article":
            ok, why = check_article_ref(conn, cite["ref_id"], online)
        elif cite["ref_type"] == "precedent":
            ok, why = check_precedent_ref(conn, cite["ref_id"], online)
        else:
            ok, why = False, f"알 수 없는 근거 종류: {cite['ref_type']}"
        db.write(conn,
                 "UPDATE comment_citations SET verified_ok = ?, verified_at = ? "
                 "WHERE id = ?", (1 if ok else 0, now, cite["id"]))
        if not ok:
            problems.append(why)

    # 본문에 몰래 들어간 인용까지 전수 검사
    for found in scan_text_citations(conn, c["reasoning"] or "", online):
        if not found["ok"]:
            problems.append(f"본문 인용 「{found['cited']}」 — {found['reason']}")

    status = "blocked" if problems else "verified"
    db.write(conn,
             "UPDATE comments SET citation_status = ?, block_reason = ? WHERE id = ?",
             (status, " / ".join(problems) if problems else None, comment_id))

    integrity.log("citation_verified", comment_id=comment_id,
                  status=status, problems=problems)
    return {"comment_id": comment_id, "status": status, "problems": problems}


def verify_all(conn, online: bool = True, progress=None) -> dict:
    rows = conn.execute("SELECT id FROM comments ORDER BY id").fetchall()
    verified, blocked = 0, 0
    details = []
    for i, r in enumerate(rows, 1):
        if progress:
            progress(i, len(rows))
        try:
            res = verify_comment(conn, r["id"], online)
        except Exception as e:
            res = {"comment_id": r["id"], "status": "blocked",
                   "problems": [f"검증 중 오류: {e}"]}
            db.write(conn, "UPDATE comments SET citation_status='blocked', "
                           "block_reason=? WHERE id=?", (str(e), r["id"]))
        if res["status"] == "verified":
            verified += 1
        else:
            blocked += 1
            details.append(res)
    return {"total": len(rows), "verified": verified,
            "blocked": blocked, "details": details}


def _main():
    import argparse
    ap = argparse.ArgumentParser(description="법률 코멘트 인용 실존 검증")
    ap.add_argument("--all", action="store_true", help="모든 코멘트 재검증")
    ap.add_argument("--offline", action="store_true",
                    help="API 조회 없이 DB 대조만 (실존 확인은 못 함)")
    args = ap.parse_args()

    if not args.all:
        ap.print_help()
        return

    conn = db.init()
    print("법률 코멘트 인용을 검증합니다...\n")

    def show(i, total):
        print(f"  [{i}/{total}]", end="\r")

    res = verify_all(conn, online=not args.offline, progress=show)
    print(" " * 40, end="\r")
    print("─" * 60)
    print(f"  통과 {res['verified']}건 / 차단 {res['blocked']}건 / 전체 {res['total']}건")
    if res["details"]:
        print("\n  차단된 코멘트:")
        for d in res["details"]:
            print(f"    #{d['comment_id']}")
            for p in d["problems"]:
                print(f"        · {p}")
        print("\n  차단된 코멘트는 화면과 문서에 표시되지 않습니다.")
    print("─" * 60)


if __name__ == "__main__":
    _main()
