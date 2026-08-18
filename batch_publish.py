"""
batch_publish.py - 여러 글을 간격을 두고 순차 발행

여러 편을 한 번에 걸어두고, 각 글 사이에 간격을 두어 차례로 에디터에 올립니다.

    python batch_publish.py 1 3 5                 1·3·5번을 순서대로
    python batch_publish.py 1 3 5 --gap 10        각 글 사이 10분 간격
    python batch_publish.py 1 3 5 --gap 5-15      5~15분 사이 무작위 간격
    python batch_publish.py --all-new             아직 발행 안 한 글 전부
    python batch_publish.py 1 3 --cta "상담문의"    CTA 프리셋 지정

번호는 `python publish.py --list` 로 확인한 번호입니다.

간격을 두는 이유
----------------
글을 연달아 몰아서 올리면 네이버 쪽에서 요청이 몰려 실패하기 쉽고,
사람이 검토할 시간도 없습니다. 간격을 두면 각 글을 확인하며 진행할 수 있습니다.
(auto_publish 는 쓰지 않으므로 최종 발행은 매번 직접 누르셔야 합니다.)
"""
import random
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from publish import collect_candidates, prepare, upload, print_list, _published_titles


def _parse_gap(raw: str) -> tuple[int, int]:
    """'10' -> (10, 10),  '5-15' -> (5, 15)  (단위: 분)"""
    raw = (raw or "").strip()
    if not raw:
        return (0, 0)
    if "-" in raw:
        lo, _, hi = raw.partition("-")
        try:
            lo_i, hi_i = int(lo), int(hi)
            return (min(lo_i, hi_i), max(lo_i, hi_i))
        except ValueError:
            return (0, 0)
    try:
        v = int(raw)
        return (v, v)
    except ValueError:
        return (0, 0)


def _wait(gap: tuple[int, int]) -> None:
    lo, hi = gap
    if hi <= 0:
        return
    minutes = random.randint(lo, hi) if hi > lo else lo
    if minutes <= 0:
        return
    print(f"\n다음 글까지 {minutes}분 대기합니다... (Ctrl+C 로 중단)")
    for remaining in range(minutes, 0, -1):
        print(f"  {remaining}분 남음", end="\r", flush=True)
        time.sleep(60)
    print(" " * 30, end="\r")


def _parse_args(argv: list) -> tuple[list, tuple, str, bool]:
    """인자를 (번호목록, 간격, CTA이름, all_new) 로 분해합니다.

    --gap 10 처럼 옵션 뒤에 오는 값은 발행 번호로 오해하면 안 되므로
    옵션과 그 값을 먼저 소비한 뒤 남은 것만 번호로 봅니다.
    """
    nums, gap, cta_name, all_new = [], (0, 0), "", False
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--gap" and i + 1 < len(argv):
            gap = _parse_gap(argv[i + 1])
            i += 2
        elif a == "--cta" and i + 1 < len(argv):
            cta_name = argv[i + 1]
            i += 2
        elif a == "--all-new":
            all_new = True
            i += 1
        elif a.isdigit():
            nums.append(int(a))
            i += 1
        else:
            i += 1
    return nums, gap, cta_name, all_new


def main() -> None:
    args = sys.argv[1:]
    nums, gap, cta_name, all_new = _parse_args(args)

    items = collect_candidates()
    if not items:
        print_list(items)
        return

    # 대상 선정
    if all_new:
        done = _published_titles()
        targets = [it for it in items if it["title"] not in done]
        if not targets:
            print("아직 발행하지 않은 글이 없습니다.")
            return
    else:
        if not nums:
            print_list(items)
            print("발행할 번호를 지정하세요.  예)  python batch_publish.py 1 3 5 --gap 10")
            return
        bad = [n for n in nums if not 1 <= n <= len(items)]
        if bad:
            print(f"범위를 벗어난 번호: {bad}  (1~{len(items)})")
            return
        targets = [items[n - 1] for n in nums]

    # CTA
    from cta_presets import get_preset
    cta = get_preset(cta_name) if cta_name else None
    if cta_name and cta is None:
        print(f"[안내] '{cta_name}' CTA를 찾지 못했습니다 - CTA 없이 진행합니다.")

    # 계획 확인
    gap_note = (f"{gap[0]}분" if gap[0] == gap[1] else f"{gap[0]}~{gap[1]}분 무작위") if gap[1] > 0 else "없음"
    print(f"\n총 {len(targets)}건을 순서대로 발행합니다.  (간격: {gap_note})")
    for i, it in enumerate(targets, 1):
        mark = "  ! 이미 발행 이력 있음" if it["title"] in _published_titles() else ""
        print(f"  {i}. [{it['date'] or '날짜없음'}] {it['title'][:48]}{mark}")
    if cta:
        print(f"  CTA: {cta['name']}")
    print("\n각 글마다 브라우저가 열립니다. 최종 [발행]은 직접 눌러주세요.")

    try:
        if input("\n진행할까요? (y/N): ").strip().lower() != "y":
            print("취소했습니다.")
            return
    except EOFError:
        print("대화형 실행이 필요합니다. 터미널에서 직접 실행해주세요.")
        return

    # 실행
    ok, fail = 0, 0
    for i, it in enumerate(targets, 1):
        print(f"\n{'=' * 55}")
        print(f"[{i}/{len(targets)}] {it['title'][:48]}")
        print("=" * 55)
        try:
            folder = prepare(it)
            upload(folder, cta=cta)
            ok += 1
        except KeyboardInterrupt:
            print("\n사용자가 중단했습니다.")
            break
        except Exception as e:
            fail += 1
            print(f"[오류] {it['title'][:40]}: {e}")
            print("  -> 다음 글로 넘어갑니다.")

        if i < len(targets):
            try:
                _wait(gap)
            except KeyboardInterrupt:
                print("\n대기 중 중단했습니다.")
                break

    print(f"\n{'=' * 55}")
    print(f"완료 - 성공 {ok}건 / 실패 {fail}건")


if __name__ == "__main__":
    main()
