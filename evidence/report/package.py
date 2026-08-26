# -*- coding: utf-8 -*-
"""
제출 패키지 — 버튼 하나로 USB에 담을 폴더를 만든다.

    제출_20260825_경찰서/
    ├── 00_증거목록.xlsx        번호·해시·일시·쟁점·요지·신뢰도
    ├── 01_재생안내서.docx      어느 파일 몇 분 몇 초를 들으면 되는지
    ├── 02_녹취록발췌.docx      화자·타임코드 + AI 전사 고지문
    ├── 03_해시목록.txt         원본·발췌본 SHA-256 (등록 당시 ↔ 현재 대조)
    ├── 04_법률검토메모.docx    쟁점·근거 조문·판례 (변호사용, 선택)
    ├── 원본/                   무수정 복사본
    └── 발췌본/                 잘라낸 구간 파일

**원본 없이는 만들지 않는다.**
유리한 구간만 잘라 발췌본만 내면 "맥락을 잘라내 편집했다"는 공격을 받고
증거가치가 떨어진다. 원본과 세트로 내고 대응표를 붙여야, 발췌본이
편집물이 아니라 "여기를 들으세요"라는 안내로 기능한다.
"""
import shutil
from datetime import datetime
from pathlib import Path

from .. import basket, db, integrity
from . import clip, excel, locator, transcript


class PackageError(RuntimeError):
    pass


def preflight(conn, include_originals: bool = True) -> dict:
    """
    만들기 전에 점검한다.
    blockers 가 있으면 생성 자체를 막고, warnings 는 보여주고 진행한다.
    """
    items = basket.items(conn)
    blockers, warnings = [], []

    if not items:
        blockers.append("발췌 장바구니가 비어 있습니다. [검색] 탭에서 구간을 담으세요.")

    if not include_originals:
        blockers.append(
            "원본을 빼고는 패키지를 만들 수 없습니다.\n\n"
            "유리한 구간만 잘라 발췌본만 제출하면 '맥락을 잘라내 편집했다'는 "
            "반박을 받고 증거가치가 떨어집니다. 원본과 함께 내고 대응표를 붙이면 "
            "발췌본이 편집물이 아니라 '여기를 들으세요'라는 안내가 됩니다."
        )

    missing = [i for i in items if not Path(i["path"]).exists()]
    if missing:
        blockers.append(
            f"원본 파일 {len(missing)}건을 찾을 수 없습니다: "
            + ", ".join(Path(m["path"]).name for m in missing[:3])
        )

    warnings.extend(basket.warnings(conn))
    return {"items": items, "blockers": blockers, "warnings": warnings}


def build(conn, out_root, target: str = "경찰서", case_name: str = "",
          extract_mode: str = clip.MODE_PCM, include_legal_memo: bool = False,
          progress=None) -> dict:
    """제출 패키지를 만든다."""
    check = preflight(conn)
    if check["blockers"]:
        raise PackageError("\n\n".join(check["blockers"]))

    items = check["items"]
    # 폴더 이름이 겹치면 기존 제출물을 덮어쓴다.
    # 이미 넘긴 자료를 말없이 지워버리는 일이 없게 고유 이름을 보장한다.
    stamp = datetime.now().strftime("%Y%m%d")
    base = f"제출_{stamp}_{target}"
    root = Path(out_root) / base
    n = 2
    while root.exists():
        root = Path(out_root) / f"{base}_{n}"
        n += 1
    orig_dir = root / "원본"
    clip_dir = root / "발췌본"
    for d in (root, orig_dir, clip_dir):
        d.mkdir(parents=True, exist_ok=True)

    def step(n, total, label):
        if progress:
            progress(n, total, label)

    TOTAL = 6
    made = {"root": root, "files": [], "clips": [], "originals": []}

    # ── 1. 원본 복사 ─────────────────────────
    step(1, TOTAL, "원본 복사")
    seen = set()
    for it in items:
        src = Path(it["path"])
        if src in seen or not src.exists():
            continue
        seen.add(src)
        dst = orig_dir / src.name
        i = 2
        while dst.exists():
            dst = orig_dir / f"{src.stem}({i}){src.suffix}"
            i += 1
        shutil.copy2(src, dst)          # 원본은 읽기만, 사본을 만든다
        made["originals"].append({
            "src": str(src), "dst": dst, "name": dst.name,
            "expected": it["sha256"],
            "actual": integrity.sha256_file(dst),
            "bytes": dst.stat().st_size,
        })

    # ── 2. 발췌본 추출 ────────────────────────
    step(2, TOTAL, "발췌본 추출")
    made["clips"] = clip.export_basket(conn, clip_dir, mode=extract_mode)

    # ── 3. 증거목록 ──────────────────────────
    step(3, TOTAL, "증거목록 작성")
    rows = locator.rows_from_basket(conn)
    made["files"].append(excel.write(
        rows, root / "00_증거목록.xlsx",
        title=f"증거목록 — {case_name}" if case_name else "증거목록"))

    # ── 4. 재생안내서 · 녹취록 ─────────────────
    step(4, TOTAL, "재생안내서 작성")
    made["files"].append(transcript.write_guide(
        rows, root / "01_재생안내서.docx", case_name))
    made["files"].append(transcript.write_transcript(
        conn, rows, root / "02_녹취록발췌.docx", case_name=case_name))

    # ── 5. 해시목록 ──────────────────────────
    step(5, TOTAL, "해시목록 작성")
    made["files"].append(_hash_manifest(root, made))

    # ── 6. 법률검토메모 (선택) ─────────────────
    step(6, TOTAL, "마무리")
    if include_legal_memo:
        try:
            from . import legal_memo
            made["files"].append(legal_memo.write(
                conn, root / "04_법률검토메모.docx", case_name))
        except Exception as e:
            made.setdefault("errors", []).append(f"법률검토메모 생성 실패: {e}")

    _readme(root, made, case_name, target, extract_mode)

    integrity.log("package_built", root=str(root), target=target,
                  originals=len(made["originals"]),
                  clips=len([c for c in made["clips"] if c.get("ok")]),
                  extract_mode=extract_mode)
    made["warnings"] = check["warnings"]
    return made


def _hash_manifest(root: Path, made: dict) -> Path:
    """
    원본과 발췌본의 해시 목록.

    등록 당시 해시와 지금 해시를 나란히 적어, 그사이 파일이
    변하지 않았음을 보인다.
    """
    lines = [
        "=" * 74,
        "  증거 파일 해시 목록 (SHA-256)",
        "=" * 74,
        "",
        f"  작성 일시 : {datetime.now():%Y년 %m월 %d일 %H:%M}",
        "",
        "  해시값은 파일의 '디지털 지문'입니다. 파일 내용이 1비트라도 달라지면",
        "  전혀 다른 값이 나옵니다. 제출된 파일의 해시를 다시 계산해 아래 값과",
        "  같다면, 수집 시점 이후 파일이 변경되지 않았음을 확인할 수 있습니다.",
        "",
        "  확인 방법 (윈도우 명령 프롬프트):",
        '      certutil -hashfile "파일경로" SHA256',
        "",
        "=" * 74,
        "",
        "[ 원본 파일 ]",
        "",
    ]

    for o in made["originals"]:
        match = "일치" if o["actual"] == o["expected"] else "★ 불일치 — 확인 필요"
        lines += [
            f"  파일   : 원본/{o['name']}",
            f"  크기   : {o['bytes']:,} 바이트",
            f"  수집시 : {o['expected']}",
            f"  현재   : {o['actual']}   ({match})",
            "",
        ]

    ok_clips = [c for c in made["clips"] if c.get("ok")]
    if ok_clips:
        lines += ["", "[ 발췌본 — 원본에서 잘라낸 구간 ]", ""]
        for c in ok_clips:
            lines += [
                f"  파일   : 발췌본/{c['name']}",
                f"  크기   : {c['bytes']:,} 바이트  ({c['duration_sec']}초)",
                f"  해시   : {c['sha256']}",
                f"  원본   : {Path(c['orig']).name}",
                f"  원본 내 위치 : {_tc(c['orig_start'])} ~ {_tc(c['orig_end'])}",
                f"  추출 방식 : {clip.mode_note(c['mode'])}",
            ]
            if c.get("reason"):
                lines.append(f"  제출 사유 : {c['reason']}")
            lines.append("")

    failed = [c for c in made["clips"] if not c.get("ok")]
    if failed:
        lines += ["", "[ 추출하지 못한 구간 ]", ""]
        for c in failed:
            lines += [f"  {c['name']} — {c['error']}", ""]

    lines += ["=" * 74]

    path = root / "03_해시목록.txt"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _tc(sec) -> str:
    sec = int(float(sec or 0))
    return f"{sec // 3600:02d}:{(sec % 3600) // 60:02d}:{sec % 60:02d}"


def _readme(root: Path, made: dict, case_name: str, target: str, mode: str):
    """받는 사람이 이 폴더를 어떻게 보면 되는지 알려주는 안내문."""
    ok_clips = [c for c in made["clips"] if c.get("ok")]
    text = f"""\
{'=' * 70}
  증거자료 제출 — {case_name or '자료 안내'}
{'=' * 70}

  작성 일시 : {datetime.now():%Y년 %m월 %d일 %H:%M}
  제출 대상 : {target}

{'-' * 70}
  이 폴더의 구성
{'-' * 70}

  00_증거목록.xlsx
      제출하는 증거를 표로 정리한 것입니다.
      각 항목이 어느 파일의 어느 위치에 있는지, 쟁점이 무엇인지 담겨 있습니다.

  01_재생안내서.docx
      원본 파일에서 어느 시각을 재생하면 되는지 안내합니다.
      미디어 재생기에서 표기된 시각으로 이동하시면 해당 내용을 들으실 수 있습니다.

  02_녹취록발췌.docx
      해당 구간을 앞뒤 맥락과 함께 옮겨 적은 것입니다.

  03_해시목록.txt
      각 파일의 SHA-256 해시값입니다. 파일이 변경되지 않았음을 확인하실 수 있습니다.

  원본/
      수집한 원본 파일을 수정 없이 그대로 복사한 것입니다. ({len(made['originals'])}개)

  발췌본/
      원본에서 해당 구간만 잘라낸 파일입니다. ({len(ok_clips)}개)
      각 파일이 원본의 어느 구간인지는 파일명과 03_해시목록.txt에 적혀 있습니다.

{'-' * 70}
  밝혀 둘 점
{'-' * 70}

  · 발췌본은 원본에서 해당 구간만 추출한 것으로, 내용을 편집하거나
    수정하지 않았습니다. 원본을 함께 제출하므로 전체 맥락을 확인하실 수 있습니다.

  · 추출 방식: {clip.mode_note(mode)}

  · 녹취록은 음성 인식 프로그램으로 옮겨 적은 것으로 참고용입니다.
    법원 제출용 정식 녹취록이 필요한 경우 속기사무소 작성본을 별도로 준비하겠습니다.
    '미검증'으로 표시된 구간은 원본 음성과 아직 대조하지 않은 부분입니다.

{'=' * 70}
"""
    (root / "README_먼저읽어주세요.txt").write_text(text, encoding="utf-8")
