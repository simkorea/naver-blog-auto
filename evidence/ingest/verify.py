# -*- coding: utf-8 -*-
"""
이중 모델 교차 검증 — 이 프로그램에서 가장 중요한 안전장치.

왜 필요한가
  Whisper의 한국어 인식률은 영어보다 확연히 낮다. 그런데 어느 모델이
  더 나은지는 녹음마다 갈린다. 어느 하나를 믿을 근거가 없다는 뜻이다.

  그래서 두 모델로 각각 전사한 뒤 대조한다. 두 모델이 같은 말로 들었다면
  그 구간은 믿을 만하고, 갈린다면 사람이 직접 들어봐야 한다.

증거 도구에서는 "정확도"보다 "어디를 믿으면 안 되는지 아는 것"이 중요하다.
잘못 전사된 발언을 그대로 제출하면 신뢰를 통째로 잃기 때문이다.
"""
import re
from difflib import SequenceMatcher

from .. import config

SIMILARITY_THRESHOLD = 0.85     # 이 아래로 갈리면 '확인 필요'

# ─────────────────────────────────────────────────────────
# 부정어 뒤집힘 — 글자로는 비슷한데 뜻은 정반대인 경우
# ─────────────────────────────────────────────────────────
# "설명 들었어요" 와 "설명 못 들었어요" 는 글자 유사도가 0.92로 매우 높다.
# 단순 유사도만 보면 '일치'로 통과해 버리는데, 소송에서 이 둘은
# 정반대 결론으로 이어진다. 부정어 유무가 갈리면 유사도와 무관하게
# 무조건 확인 대상으로 올린다.
_NEGATION = re.compile(
    r"(못\s|못했|못한|안\s|안했|않|없|아니|불가|거부|반대|취소|미(?:이행|지급|납부))"
)
_AFFIRM = re.compile(r"(했|맞|네|예|응|그래|알겠|동의|승낙|확인|인정)")


def negation_flipped(a: str, b: str) -> bool:
    """한쪽에만 부정어가 있으면 뜻이 뒤집힌 것으로 본다."""
    return bool(_NEGATION.search(a or "")) != bool(_NEGATION.search(b or ""))


# 금액·기간·비율 표현. 한글 단위(천·백·만·억)까지 잡아야 한다 —
# "5천만원"과 "5백만원"은 글자 하나 차이지만 열 배다.
_QUANTITY = re.compile(
    r"(?:[0-9][0-9,\.]*|[일이삼사오육칠팔구십백천만억조]+)"
    r"\s*"
    r"(?:억\s*원|만\s*원|천\s*원|원|퍼센트|프로|%|개월|년|개월|일|월|명|개|평|㎡|층|동|호)"
)
_KOR_UNIT = re.compile(r"[십백천만억조]")


def _quantities(text: str) -> list[str]:
    """금액·기간 표현을 뽑아 공백을 지우고 비교 가능한 형태로."""
    return [re.sub(r"[\s,]", "", q) for q in _QUANTITY.findall(text or "")]


def _number_changed(a: str, b: str) -> bool:
    """
    금액·날짜·비율이 다르면 유사도가 높아도 확인해야 한다.

    아라비아 숫자뿐 아니라 한글 단위까지 본다. 통화 녹음에서 금액은
    거의 항상 소송의 핵심 쟁점이 되므로, 조금이라도 다르면 사람이 듣는다.
    """
    if _quantities(a) != _quantities(b):
        return True
    # 수량 표현 밖에 있는 맨 숫자도 비교 (예: "3월 14일에", 계좌번호)
    if re.findall(r"\d+", a or "") != re.findall(r"\d+", b or ""):
        return True
    # 한글 수 단위만 바뀐 경우 (예: "오천만" ↔ "오백만")
    if _KOR_UNIT.findall(a or "") != _KOR_UNIT.findall(b or ""):
        return True
    return False


def normalize(text: str) -> str:
    """
    비교용 정규화.
    구두점·공백·조사 차이로 불일치가 뜨면 확인할 게 너무 많아진다.
    실질적으로 다른 말인지만 본다.
    """
    t = (text or "").strip()
    t = re.sub(r"[.,!?~…·\"'「」『』()\[\]<>《》\-—]", "", t)
    t = re.sub(r"\s+", "", t)
    return t


def similarity(a: str, b: str) -> float:
    na, nb = normalize(a), normalize(b)
    if not na and not nb:
        return 1.0
    if not na or not nb:
        return 0.0
    return SequenceMatcher(None, na, nb).ratio()


def _overlap(a_start, a_end, b_start, b_end) -> float:
    """두 구간이 시간상 겹치는 길이."""
    return max(0.0, min(a_end, b_end) - max(a_start, b_start))


def align(primary: list[dict], secondary: list[dict]) -> list[tuple]:
    """
    두 전사 결과를 시간축으로 맞춘다.

    모델마다 구간을 나누는 지점이 달라 1:1로 대응되지 않는다.
    그래서 시간이 가장 많이 겹치는 상대를 짝으로 삼는다.
    """
    pairs = []
    for p in primary:
        best, best_ov = None, 0.0
        for s in secondary:
            ov = _overlap(p["start_sec"], p["end_sec"],
                          s["start_sec"], s["end_sec"])
            if ov > best_ov:
                best, best_ov = s, ov
        # 겹침이 구간 길이의 30% 미만이면 짝이 없는 것으로 본다
        span = max(0.1, p["end_sec"] - p["start_sec"])
        pairs.append((p, best if best_ov / span >= 0.3 else None))
    return pairs


def cross_check(path, primary: list[dict], model_name: str = None,
                progress=None) -> list[dict]:
    """
    2차 모델로 다시 전사해 1차 결과와 대조한다.

    갈리는 구간에는 alt_text(2차 모델이 들은 말)와 alt_mismatch 표시가 붙고,
    신뢰도 점수도 깎인다. 화면에서는 이런 구간이 먼저 올라온다.
    """
    from . import audio

    model_name = model_name or config.WHISPER_SECONDARY
    if model_name == config.WHISPER_PRIMARY:
        return primary          # 같은 모델이면 대조 의미가 없다

    secondary = audio.transcribe(path, model_name, progress=progress)
    if not secondary:
        return primary

    out = []
    for p, s in align(primary, secondary):
        row = dict(p)
        if s is None:
            # 2차 모델은 이 구간에서 아무 말도 못 들었다 → 환청 의심
            row["alt_text"] = ""
            row["alt_mismatch"] = 1
            row["hallucination_risk"] = 1
            row["confidence"] = round((row.get("confidence") or 0.5) * 0.4, 3)
        else:
            sim = similarity(p["text"], s["text"])
            flipped = negation_flipped(p["text"], s["text"])
            num_diff = _number_changed(p["text"], s["text"])

            if flipped or num_diff or sim < SIMILARITY_THRESHOLD:
                row["alt_text"] = s["text"]
                row["alt_mismatch"] = 1
                if flipped:
                    # 뜻이 정반대다. 유사도가 아무리 높아도 가장 낮게 본다.
                    row["mismatch_kind"] = "부정어 뒤집힘"
                    row["confidence"] = 0.1
                elif num_diff:
                    row["mismatch_kind"] = "숫자 불일치"
                    row["confidence"] = round(
                        min(0.4, (row.get("confidence") or 0.5) * 0.5), 3)
                else:
                    row["mismatch_kind"] = "표현 불일치"
                    row["confidence"] = round(
                        (row.get("confidence") or 0.5) * (0.3 + 0.6 * sim), 3)
            else:
                row["alt_mismatch"] = 0
                # 두 모델이 같게 들었다면 조금 더 믿을 수 있다
                row["confidence"] = round(
                    min(1.0, (row.get("confidence") or 0.5) * 1.15), 3)
        out.append(row)
    return out


def summary(rows: list[dict]) -> dict:
    total = len(rows)
    mismatch = sum(1 for r in rows if r.get("alt_mismatch"))
    risky = sum(1 for r in rows if r.get("hallucination_risk"))
    low = sum(1 for r in rows if (r.get("confidence") or 1) < 0.6)
    return {"total": total, "mismatch": mismatch,
            "hallucination": risky, "low_confidence": low,
            "need_check": len({id(r) for r in rows
                               if r.get("alt_mismatch") or r.get("hallucination_risk")
                               or (r.get("confidence") or 1) < 0.6})}
