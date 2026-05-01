"""
Supabase 연동 모듈 — 발행 대기열 관리
requests 만 사용 (이미 requirements.txt에 포함)
"""
import datetime
import requests

_TABLE = "post_queue"


def _headers(key: str) -> dict:
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


def push_pending(
    url: str, key: str,
    title: str, content: str, tags: str, local_folder: str,
    scheduled_at: str = "",
) -> tuple[bool, str]:
    """post_queue 테이블에 pending 행 추가. (성공여부, id 또는 오류메시지)

    scheduled_at: ISO 8601 문자열 (예: '2026-05-02T09:00:00'). 비어 있으면 즉시 발행.
    """
    endpoint = f"{url}/rest/v1/{_TABLE}"
    payload  = {
        "date":         datetime.date.today().isoformat(),
        "title":        title,
        "content":      content,
        "tags":         tags,
        "local_folder": local_folder,
        "status":       "pending",
        "error_msg":    "",
    }
    if scheduled_at:
        payload["scheduled_at"] = scheduled_at
    try:
        resp = requests.post(endpoint, json=payload, headers=_headers(key), timeout=15)
        resp.raise_for_status()
        row = resp.json()[0]
        return True, str(row.get("id", "?"))
    except Exception as e:
        return False, str(e)


def get_all_rows(url: str, key: str) -> list[dict]:
    """전체 행을 최신순으로 반환합니다."""
    endpoint = f"{url}/rest/v1/{_TABLE}?order=created_at.desc&limit=200"
    try:
        resp = requests.get(endpoint, headers=_headers(key), timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return []


def get_pending_rows(url: str, key: str) -> list[dict]:
    """status=pending 이고 scheduled_at 이 없거나 현재 시각 이하인 행을 반환합니다."""
    now = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    # scheduled_at 컬럼이 없는 구형 테이블도 graceful하게 처리하기 위해
    # or() 조건: null 이거나 현재 시각 이하
    endpoint = (
        f"{url}/rest/v1/{_TABLE}"
        f"?status=eq.pending"
        f"&or=(scheduled_at.is.null,scheduled_at.lte.{now})"
        f"&order=created_at.asc"
    )
    try:
        resp = requests.get(endpoint, headers=_headers(key), timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        # or() 구문 미지원 구형 Supabase → 기존 방식으로 폴백
        try:
            endpoint_fallback = f"{url}/rest/v1/{_TABLE}?status=eq.pending&order=created_at.asc"
            resp2 = requests.get(endpoint_fallback, headers=_headers(key), timeout=15)
            resp2.raise_for_status()
            return resp2.json()
        except Exception:
            return []


def update_status(
    url: str, key: str,
    row_id: str, status: str, error_msg: str = "",
) -> bool:
    """특정 id 행의 status / error_msg 를 업데이트합니다."""
    endpoint = f"{url}/rest/v1/{_TABLE}?id=eq.{row_id}"
    try:
        resp = requests.patch(
            endpoint,
            json={"status": status, "error_msg": error_msg},
            headers=_headers(key),
            timeout=15,
        )
        resp.raise_for_status()
        return True
    except Exception:
        return False
