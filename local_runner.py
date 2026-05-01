"""
로컬 매크로 PC 전용 — Supabase 발행 대기열 모니터링 & 네이버 자동 업로드

사용법:
    python local_runner.py           # 30초 간격 폴링 (기본값)
    python local_runner.py --once    # 한 번만 실행 후 종료

흐름:
    Supabase post_queue 에서 status=pending 행 읽음
    → 로컬 posts/ 폴더에서 해당 원고·이미지 탐색
    → Playwright 로 네이버 블로그 업로드
    → Supabase status → done / error 업데이트
"""
import sys
import time
import datetime
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ── 설정 ────────────────────────────────────────────────────────────────────
CHECK_INTERVAL = 30
POSTS_DIR      = Path("posts")


def _creds() -> tuple[str, str]:
    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_KEY", "")
    return url, key


# ── 로컬 폴더 탐색 ───────────────────────────────────────────────────────────

def _find_folder(local_folder: str, date: str) -> Path | None:
    candidates = [
        POSTS_DIR / date / local_folder,
        POSTS_DIR / local_folder,
    ]
    for p in candidates:
        if p.exists() and (p / "content.txt").exists():
            return p

    # 날짜 폴더 아래 유사 이름 탐색
    date_dir = POSTS_DIR / date
    if date_dir.exists():
        for d in sorted(date_dir.iterdir()):
            if d.is_dir() and local_folder[:10] in d.name:
                return d
    return None


# ── 단일 행 처리 ─────────────────────────────────────────────────────────────

def _process(row: dict, url: str, key: str) -> None:
    from supabase_db import update_status

    row_id       = row["id"]
    title        = row.get("title", "")
    content      = row.get("content", "")
    date         = row.get("date", "")
    local_folder = row.get("local_folder", "")

    print(f"\n[처리 시작] {title[:50]}  (id={row_id})")
    update_status(url, key, row_id, "processing")

    folder = _find_folder(local_folder, date)

    if folder:
        print(f"  폴더 발견: {folder}")
        # 구글 시트 버전이 더 최신이면 content.txt 덮어쓰기
        local_txt = folder / "content.txt"
        if content.strip() and local_txt.exists():
            if local_txt.read_text(encoding="utf-8").strip() != content.strip():
                local_txt.write_text(content, encoding="utf-8")
                print("  content.txt → Supabase 버전으로 업데이트")
    else:
        # 폴더 없으면 텍스트만으로 임시 생성
        folder = POSTS_DIR / date / local_folder
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "content.txt").write_text(content, encoding="utf-8")
        print(f"  [경고] 로컬 폴더 없음 → {folder} 임시 생성")
        print(f"  이미지 포함 업로드를 원하면 ZIP을 {folder} 에 압축 해제 후 재시도하세요.")

    try:
        from step2_upload import upload_to_naver_blog
        upload_to_naver_blog(folder_path=str(folder), headless=False, auto_publish=False)
        update_status(url, key, row_id, "done")
        print(f"  [완료] {title[:50]}")
    except Exception as e:
        update_status(url, key, row_id, "error", str(e))
        print(f"  [오류] {e}")


# ── 메인 ─────────────────────────────────────────────────────────────────────

def run_once() -> None:
    from supabase_db import get_pending_rows

    url, key = _creds()
    if not url or not key:
        print("[오류] .env 에 SUPABASE_URL 과 SUPABASE_KEY 가 없습니다.")
        return

    pending = get_pending_rows(url, key)
    if not pending:
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        print(f"[{ts}] 대기 중인 작업 없음.")
        return

    print(f"발행 대기 {len(pending)}건 → 첫 번째 처리 시작")
    _process(pending[0], url, key)


def main() -> None:
    print("=" * 50)
    print("  네이버 블로그 로컬 런너 (Supabase)")
    print(f"  폴링 간격: {CHECK_INTERVAL}초  |  종료: Ctrl+C")
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
