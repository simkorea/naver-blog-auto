"""
로컬 매크로 PC 전용 — 구글 시트 발행 대기열 모니터링 & 네이버 자동 업로드

사용법:
    python local_runner.py           # 30초 간격 폴링 (기본값)
    python local_runner.py --once    # 한 번만 실행 후 종료

흐름:
    구글 시트에서 status=pending 행을 읽음
    → 로컬 posts/ 폴더에서 해당 원고·이미지 찾음
    → Playwright로 네이버 블로그 업로드
    → 시트 status를 done / error 로 업데이트
"""
import sys
import time
import datetime
import os
import json
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ── 설정 ────────────────────────────────────────────────────────────────────
CHECK_INTERVAL = 30          # 폴링 간격 (초)
POSTS_DIR      = Path("posts")

# ── 구글 시트 자격증명 읽기 ─────────────────────────────────────────────────

def _load_creds() -> tuple[str, str]:
    """(creds_json 문자열, sheet_id) 반환. 실패 시 빈 문자열."""
    # 방법 1: service_account.json 파일
    sa_file = Path("service_account.json")
    if sa_file.exists():
        creds_json = sa_file.read_text(encoding="utf-8")
    else:
        creds_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")

    sheet_id = os.getenv("GOOGLE_SHEET_ID", "")
    return creds_json, sheet_id


# ── 로컬 폴더 탐색 ───────────────────────────────────────────────────────────

def _find_local_folder(local_folder: str, date: str) -> Path | None:
    """posts/{date}/{local_folder} 또는 posts/{local_folder} 를 탐색합니다."""
    candidates = [
        POSTS_DIR / date / local_folder,
        POSTS_DIR / local_folder,
    ]
    for p in candidates:
        if p.exists() and (p / "content.txt").exists():
            return p

    # 날짜 폴더 아래에서 유사 이름 탐색 (앞 10자 매칭)
    date_dir = POSTS_DIR / date
    if date_dir.exists():
        for d in sorted(date_dir.iterdir()):
            if d.is_dir() and local_folder[:10] in d.name:
                return d
    return None


# ── 단일 행 처리 ─────────────────────────────────────────────────────────────

def _process_row(row: dict, creds_json: str, sheet_id: str) -> None:
    from google_sheets import update_status

    row_id       = row.get("id", "?")
    title        = row.get("title", "")
    content      = row.get("content", "")
    date         = row.get("date", "")
    local_folder = row.get("local_folder", "")

    print(f"\n[처리 시작] id={row_id}  |  {title[:40]}")

    # 상태 → processing
    update_status(creds_json, sheet_id, row_id, "processing")

    # 로컬 폴더 탐색
    folder = _find_local_folder(local_folder, date)

    if folder:
        print(f"  폴더 발견: {folder}")
    else:
        # 폴더가 없으면 임시 생성 (이미지 없이 텍스트만 업로드)
        folder = POSTS_DIR / date / local_folder
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "content.txt").write_text(content, encoding="utf-8")
        print(f"  [경고] 로컬 폴더 없음 — {folder} 를 임시 생성했습니다.")
        print(f"  이미지를 포함하려면 ZIP을 {folder} 에 압축 해제한 후 재시도하세요.")

    # 내용이 최신 버전인지 확인 (구글 시트가 더 최신이면 덮어씀)
    local_content_path = folder / "content.txt"
    if local_content_path.exists():
        local_text = local_content_path.read_text(encoding="utf-8").strip()
        if local_text != content.strip() and content.strip():
            local_content_path.write_text(content, encoding="utf-8")
            print("  content.txt 를 구글 시트 버전으로 업데이트했습니다.")

    # 업로드 실행
    try:
        from step2_upload import upload_to_naver_blog
        upload_to_naver_blog(folder_path=str(folder), headless=False, auto_publish=False)
        update_status(creds_json, sheet_id, row_id, "done")
        print(f"  [완료] {title[:40]}")
    except Exception as e:
        update_status(creds_json, sheet_id, row_id, "error", str(e))
        print(f"  [오류] {e}")


# ── 메인 루프 ────────────────────────────────────────────────────────────────

def run_once() -> None:
    from google_sheets import get_all_rows

    creds_json, sheet_id = _load_creds()
    if not creds_json or not sheet_id:
        print("[오류] service_account.json 또는 GOOGLE_SHEET_ID 가 없습니다.")
        print("  - service_account.json 파일을 이 폴더에 넣거나")
        print("  - .env 파일에 GOOGLE_SERVICE_ACCOUNT_JSON='{...}' 와 GOOGLE_SHEET_ID=... 를 설정하세요.")
        return

    rows = get_all_rows(creds_json, sheet_id)
    pending = [r for r in rows if r.get("status") == "pending"]

    if not pending:
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        print(f"[{ts}] 대기 중인 작업 없음.")
        return

    print(f"발행 대기 {len(pending)}건 발견 — 첫 번째 항목 처리 중...")
    _process_row(pending[0], creds_json, sheet_id)


def main() -> None:
    print("=" * 50)
    print("  네이버 블로그 로컬 런너")
    print(f"  폴링 간격: {CHECK_INTERVAL}초")
    print("  종료: Ctrl+C")
    print("=" * 50)

    while True:
        try:
            run_once()
        except KeyboardInterrupt:
            print("\n종료합니다.")
            sys.exit(0)
        except Exception as e:
            print(f"[예외] {e}")
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    if "--once" in sys.argv:
        run_once()
    else:
        main()
