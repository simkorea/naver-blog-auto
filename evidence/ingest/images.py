# -*- coding: utf-8 -*-
"""
이미지 OCR — 카톡 캡처·계약서 스캔본을 검색 가능하게 만든다.

기존 image_fetcher.py가 이미 한국어 EasyOCR Reader를 싱글턴으로
초기화해 두었으므로 그대로 재사용한다. 모델을 두 번 올리면
메모리만 낭비된다.
"""
from pathlib import Path

_reader = None
_failed = False


def get_reader():
    """
    OCR 리더를 가져온다.
    1순위: 기존 image_fetcher의 싱글턴 (이미 떠 있으면 재사용)
    2순위: 직접 초기화
    """
    global _reader, _failed
    if _reader is not None:
        return _reader
    if _failed:
        return None

    # 기존 모듈 재사용 시도
    try:
        import sys
        root = str(Path(__file__).resolve().parents[2])
        if root not in sys.path:
            sys.path.insert(0, root)
        import image_fetcher
        r = image_fetcher._get_ocr_reader()
        if r is not None:
            _reader = r
            return _reader
    except BaseException:
        pass

    try:
        import easyocr
        _reader = easyocr.Reader(["ko", "en"], gpu=True, verbose=False)
        return _reader
    except BaseException:
        try:
            import easyocr
            _reader = easyocr.Reader(["ko", "en"], gpu=False, verbose=False)
            return _reader
        except BaseException:
            _failed = True
            print("        [안내] easyocr 미설치 → 이미지 글자 인식 건너뜀")
            print("               설치: pip install easyocr")
            return None


def ocr(path, min_confidence: float = 0.3) -> list[dict]:
    """
    이미지에서 글자를 읽는다.

    EasyOCR은 줄 단위로 인식 결과와 신뢰도를 준다. 신뢰도가 낮은 조각은
    잘못 읽었을 가능성이 크므로 걸러내되, 완전히 버리지 않고 표시만 한다
    (증거 도구에서는 임의로 버리는 것보다 표시하는 편이 안전하다).
    """
    reader = get_reader()
    if reader is None:
        return []

    results = reader.readtext(str(path), detail=1, paragraph=False)
    lines = []
    for item in results:
        try:
            box, text, conf = item[0], item[1], float(item[2])
        except (IndexError, TypeError, ValueError):
            continue
        if not text.strip():
            continue
        # 세로 위치로 정렬해 읽는 순서를 복원
        ys = [pt[1] for pt in box]
        lines.append({"text": text.strip(), "confidence": conf,
                      "y": sum(ys) / len(ys)})

    lines.sort(key=lambda x: x["y"])
    return [l for l in lines if l["confidence"] >= min_confidence or True]


def extract(conn, source_row) -> int:
    """이미지 한 장을 OCR해 DB에 넣는다."""
    from .. import db, integrity

    try:
        lines = ocr(source_row["path"])
    except Exception as e:
        db.set_status(conn, source_row["id"], "failed", str(e))
        return 0

    if not lines:
        db.set_status(conn, source_row["id"], "extracted", "인식된 글자 없음")
        return 0

    # 카톡 캡처는 줄이 많아 한 덩어리로 묶어야 맥락이 산다
    text = "\n".join(l["text"] for l in lines)
    avg_conf = sum(l["confidence"] for l in lines) / len(lines)

    segs = [{
        "seq": 1,
        "text": text,
        "confidence": round(avg_conf, 3),
        # OCR 신뢰도가 낮으면 원본 이미지를 직접 확인해야 한다
        "hallucination_risk": 1 if avg_conf < 0.6 else 0,
    }]

    db.clear_segments(conn, source_row["id"])
    n = db.add_segments(conn, source_row["id"], segs)
    db.set_status(conn, source_row["id"], "extracted",
                  f"{len(lines)}줄 인식 · 평균 신뢰도 {avg_conf:.0%}")
    integrity.log("extract_image", source_id=source_row["id"],
                  lines=len(lines), avg_confidence=round(avg_conf, 3))
    return n
