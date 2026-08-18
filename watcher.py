"""
사무실 PC 24시간 실행용 - Supabase post_queue 실시간 감시 & 자동 업로드

설치 (최초 1회):
    pip install supabase            ← 리얼타임 구독용 (선택)
    pip install python-dotenv requests   ← 폴링용 (필수)

사용법:
    python watcher.py           # 리얼타임 구독 + 30초 폴링 병행 (권장)
    python watcher.py --poll    # 폴링 전용 (supabase 패키지 없을 때)
"""
import os
import sys
import time
import datetime
import threading

from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL  = os.getenv("SUPABASE_URL", "")
# post_queue 는 anon(public) 역할 접근을 막아뒀으므로 RLS를 우회하는 service_role 키를 사용합니다.
# 이 키는 서버(사무실 PC)에서만 쓰고 절대 브라우저/클라이언트 코드에 노출하면 안 됩니다.
SUPABASE_KEY  = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
POLL_INTERVAL = 30   # 초 - 리얼타임 누락 보완용 폴링 간격

# 중복 처리 방지 (리얼타임 + 폴링 동시 트리거 대비)
_processing_ids: set = set()
_lock = threading.Lock()


def _now() -> str:
    return datetime.datetime.now().strftime("%H:%M:%S")


# ── 행 처리 ──────────────────────────────────────────────────────────────────

def process_row(row: dict) -> None:
    """
    pending 행 1건 처리:
        1. processing 으로 상태 변경
        2. step2_generate.upload_post() 호출
        3. done / error 로 상태 업데이트
    """
    from supabase_db import update_status

    row_id = str(row.get("id", ""))
    if not row_id:
        return

    # 같은 행이 이미 처리 중이면 건너뜀
    with _lock:
        if row_id in _processing_ids:
            return
        _processing_ids.add(row_id)

    title = row.get("title", "")
    print(f"\n[{_now()}] 처리 시작: {title[:50]}  (id={row_id})")
    update_status(SUPABASE_URL, SUPABASE_KEY, row_id, "processing")

    try:
        from step2_generate import upload_post
        upload_post(row)
        update_status(SUPABASE_URL, SUPABASE_KEY, row_id, "done")
        print(f"[{_now()}] 완료: {title[:50]}")
    except Exception as e:
        update_status(SUPABASE_URL, SUPABASE_KEY, row_id, "error", str(e))
        print(f"[{_now()}] 오류 ({title[:30]}): {e}")
    finally:
        with _lock:
            _processing_ids.discard(row_id)


# ── 폴링 (REST API) ────────────────────────────────────────────────────────

def poll_once() -> None:
    """pending 행이 있으면 첫 번째 1건 처리."""
    from supabase_db import get_pending_rows

    try:
        rows = get_pending_rows(SUPABASE_URL, SUPABASE_KEY)
    except Exception as e:
        print(f"[{_now()}] 폴링 오류: {e}")
        return

    if not rows:
        return

    print(f"[{_now()}] 대기 항목 {len(rows)}건 발견 -> 처리 시작")
    process_row(rows[0])


# ── 리얼타임 구독 (supabase-py) ────────────────────────────────────────────

def _realtime_thread() -> None:
    """
    supabase-py 가 설치된 경우 리얼타임 INSERT 구독을 백그라운드 스레드에서 실행.
    실패하거나 패키지가 없으면 조용히 종료 -> 폴링이 보완함.
    """
    try:
        from supabase import create_client  # type: ignore
    except ImportError:
        print(f"[{_now()}] supabase 패키지 없음 -> 폴링 전용으로 실행합니다.")
        print("         (리얼타임을 원하면: pip install supabase)")
        return

    reconnect_delay = 10   # 재연결 대기(초)

    while True:
        try:
            client = create_client(SUPABASE_URL, SUPABASE_KEY)

            def on_insert(payload: dict) -> None:
                # supabase-py 버전에 따라 record 위치가 다를 수 있음
                record = (
                    payload.get("record")
                    or payload.get("new")
                    or (payload.get("data") or {}).get("record")
                    or {}
                )
                if isinstance(record, dict) and record.get("status") == "pending":
                    threading.Thread(
                        target=process_row, args=(record,), daemon=True
                    ).start()

            (
                client.channel("post_queue_watch")
                .on_postgres_changes(
                    event="INSERT",
                    schema="public",
                    table="post_queue",
                    callback=on_insert,
                )
                .subscribe()
            )
            print(f"[{_now()}] 리얼타임 구독 활성화 - post_queue INSERT 감시 중")

            # 구독 유지 (내부 WebSocket 스레드가 이벤트 처리)
            while True:
                time.sleep(60)

        except Exception as e:
            print(f"[{_now()}] 리얼타임 연결 오류: {e}  -> {reconnect_delay}초 후 재연결 시도")
            time.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 2, 300)   # 최대 5분


# ── 메인 ──────────────────────────────────────────────────────────────────────

def main() -> None:
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("[오류] .env 에 SUPABASE_URL 과 SUPABASE_SERVICE_ROLE_KEY 가 없습니다.")
        sys.exit(1)

    print("=" * 55)
    print("  네이버 블로그 Watcher")
    print(f"  폴링 간격 : {POLL_INTERVAL}초  |  종료 : Ctrl+C")
    print("=" * 55)

    # 리얼타임 구독 (--poll 플래그 없을 때만)
    if "--poll" not in sys.argv:
        rt = threading.Thread(target=_realtime_thread, daemon=True)
        rt.start()
    else:
        print(f"[{_now()}] 폴링 전용 모드로 실행합니다.")

    # 시작 즉시 기존 pending 처리
    poll_once()

    # 메인 루프 - 30초마다 폴링 (리얼타임 누락 보완)
    while True:
        try:
            time.sleep(POLL_INTERVAL)
            poll_once()
        except KeyboardInterrupt:
            print("\n[watcher] 종료합니다.")
            sys.exit(0)
        except Exception as e:
            print(f"[{_now()}] 예외: {e}")


if __name__ == "__main__":
    main()
