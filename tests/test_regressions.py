"""
test_regressions.py - 실제로 겪었던 버그가 다시 살아나지 않는지 확인합니다.

여기 있는 테스트는 전부 '이미 한 번 터졌던 것'입니다.
새 기능을 넣다가 이 중 하나라도 빨간불이 뜨면, 예전 버그를 되살린 것입니다.

실행:
    venv\\Scripts\\python.exe -m pytest tests -q
"""
import sys
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))


# ─────────────────────────────────────────────────────────────
# 1. 이미지가 본문 앞부분에만 몰리던 버그
#    원인: 문단수 // 이미지수 는 소수점이 버려져 간격이 1이 됨
#    증상: 문단 18 / 이미지 10 이면 1~10문단에 다 쓰고 뒤 8문단이 빔
# ─────────────────────────────────────────────────────────────

def test_이미지가_본문_전체에_퍼진다():
    from step2_upload import plan_image_positions

    pos = plan_image_positions(n_paragraphs=18, n_images=10)
    placed = sorted(pos)

    assert len(placed) == 10, "이미지 10장이 모두 배치돼야 합니다"
    # 앞쪽에만 몰리면 안 됩니다 - 마지막 이미지는 본문 후반부에 있어야 합니다.
    assert placed[-1] > 12, f"뒤쪽 문단이 비었습니다: {placed}"
    # 예전 버그에서는 정확히 1~10 이었습니다.
    assert placed != list(range(1, 11)), "예전 쏠림 버그가 되살아났습니다"


def test_이미지_배치_경계값():
    from step2_upload import plan_image_positions

    assert plan_image_positions(10, 10) == {i: i - 1 for i in range(1, 11)}
    assert plan_image_positions(5, 0) == {}, "이미지가 없으면 배치도 없어야 합니다"
    assert plan_image_positions(0, 3) == {}, "문단이 없으면 배치도 없어야 합니다"

    # 이미지가 문단보다 많으면 문단 수만큼만 배치되고 예외가 없어야 합니다.
    pos = plan_image_positions(3, 10)
    assert len(pos) <= 3


# ─────────────────────────────────────────────────────────────
# 2. 대기열 값으로 posts/ 밖에 파일을 쓸 수 있던 문제 (path traversal)
# ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("evil", [
    "../../../windows/system32",
    "..\\..\\etc",
    "../../../../etc/passwd",
    "a/../../b",
])
def test_경로_탈출_문자가_제거된다(evil):
    from supabase_db import sanitize_path_component

    safe = sanitize_path_component(evil)
    assert ".." not in safe
    assert "/" not in safe and "\\" not in safe
    assert safe, "비어 있으면 안 됩니다"


def test_정상적인_한글_폴더명은_보존된다():
    from supabase_db import sanitize_path_component

    name = "2026-08-16_부동산_뉴스_8선"
    assert sanitize_path_component(name) == name


def test_빈값은_안전한_기본값이_된다():
    from supabase_db import sanitize_path_component

    assert sanitize_path_component("") == "untitled"
    assert sanitize_path_component(None) == "untitled"


# ─────────────────────────────────────────────────────────────
# 3. batch_publish 에서 --gap 값이 발행할 글 번호로 오인되던 버그
#    증상: `batch_publish.py 1 --gap 5` 가 1번과 5번 둘 다 발행하려 함
# ─────────────────────────────────────────────────────────────

def test_gap_값이_글번호로_오인되지_않는다():
    from batch_publish import _parse_args

    nums, gap, cta, all_new = _parse_args(["1", "--gap", "5"])
    assert nums == [1], f"1번만 대상이어야 하는데 {nums} 입니다"
    assert gap == (5, 5)


def test_인자_조합_파싱():
    from batch_publish import _parse_args

    nums, gap, cta, all_new = _parse_args(["1", "3", "5", "--gap", "10"])
    assert (nums, gap) == ([1, 3, 5], (10, 10))

    nums, gap, cta, all_new = _parse_args(["2", "--gap", "5-15", "--cta", "상담문의"])
    assert (nums, gap, cta) == ([2], (5, 15), "상담문의")

    nums, gap, cta, all_new = _parse_args(["--all-new", "--gap", "7"])
    assert all_new is True and nums == []


# ─────────────────────────────────────────────────────────────
# 4. 카드뉴스 원고 파싱 - 소제목이 본문과 분리돼 이미지가 끼어들던 문제
# ─────────────────────────────────────────────────────────────

SAMPLE = """[제목]
8/16 부동산 핵심정보: 청약일정까지
(29자)

[태그]
#부동산, #청약

[본문]
도입부 문단입니다. 여러 문장이 들어갑니다.

새로운 공공분양이 온다

공공분양 시장에 변화가 있습니다. 분양가의 25%만 냅니다.

#부동산 #청약
"""


def test_소제목이_본문과_한_덩어리로_묶인다():
    from zip_importer import parse_manuscript

    title, body, tags = parse_manuscript(SAMPLE)
    blocks = [b for b in body.split("\n\n") if b.strip()]

    merged = [b for b in blocks if b.startswith("새로운 공공분양이 온다")]
    assert merged, "소제목이 본문과 합쳐지지 않았습니다"
    assert "공공분양 시장에 변화" in merged[0], "소제목 뒤 본문이 같은 블록이어야 합니다"


def test_제목에서_글자수_메모가_제거된다():
    from zip_importer import parse_manuscript

    title, _, _ = parse_manuscript(SAMPLE)
    assert title == "8/16 부동산 핵심정보: 청약일정까지"
    assert "(29자)" not in title


def test_태그가_추출된다():
    from zip_importer import normalize_tags, parse_manuscript

    _, _, raw = parse_manuscript(SAMPLE)
    assert normalize_tags(raw) == ["부동산", "청약"]


# ─────────────────────────────────────────────────────────────
# 5. 멈춘 작업 감지 - 방금 시작한 작업을 멈춤으로 오판하면 안 됨
# ─────────────────────────────────────────────────────────────

def test_방금_시작한_작업은_멈춤이_아니다():
    import datetime
    from home_status import find_stuck_rows

    now = datetime.datetime.now(datetime.timezone.utc)
    rows = [
        {"status": "processing", "title": "방금",
         "created_at": (now - datetime.timedelta(minutes=5)).isoformat()},
        {"status": "processing", "title": "오래됨",
         "created_at": (now - datetime.timedelta(hours=5)).isoformat()},
        {"status": "pending", "title": "대기중",
         "created_at": (now - datetime.timedelta(hours=9)).isoformat()},
    ]
    stuck = [r["title"] for r in find_stuck_rows(rows)]
    assert stuck == ["오래됨"], f"멈춤 판정이 잘못됐습니다: {stuck}"


def test_시각을_못_읽으면_의심대상으로_잡는다():
    from home_status import find_stuck_rows

    rows = [{"status": "processing", "title": "깨진시각", "created_at": "이상한값"}]
    assert len(find_stuck_rows(rows)) == 1


# ─────────────────────────────────────────────────────────────
# 6. CTA 프리셋 저장/불러오기
# ─────────────────────────────────────────────────────────────

def test_CTA_저장하고_다시_읽으면_같다(tmp_path):
    from cta_presets import load_presets, save_presets, get_preset, summary

    f = tmp_path / "cta.json"
    save_presets([
        {"name": "상담문의", "text": "문의주세요", "link": "https://example.com",
         "image": "", "map": ""},
    ], f)

    got = load_presets(f)
    assert len(got) == 1
    assert got[0]["name"] == "상담문의"
    assert get_preset("상담문의", f)["link"] == "https://example.com"
    assert "링크" in summary(got[0])


def test_빈_CTA는_비어있다고_판정된다():
    from cta_presets import is_empty

    assert is_empty(None)
    assert is_empty({"name": "이름만", "text": "", "link": "", "image": "", "map": ""})
    assert not is_empty({"name": "x", "text": "내용", "link": "", "image": "", "map": ""})


# ─────────────────────────────────────────────────────────────
# 7. 콘솔 인코딩(cp949) 때문에 업로드가 통째로 중단되던 문제
#    한국어 윈도우 콘솔은 cp949 라 em dash(—) 같은 문자를 print 하면 죽습니다.
# ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("filename", [
    "step2_upload.py", "publish.py", "batch_publish.py",
    "zip_importer.py", "cta_presets.py", "home_status.py",
    "post_utils.py", "menu.py", "launcher.py",
])
def test_콘솔에_출력하는_파일에_cp949_불가문자가_없다(filename):
    text = (BASE / filename).read_text(encoding="utf-8")
    bad = []
    for ch in set(text):
        try:
            ch.encode("cp949")
        except UnicodeEncodeError:
            bad.append(ch)
    assert not bad, f"{filename} 에 cp949 로 출력 못 하는 문자가 있습니다: {bad}"
