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
) -> tuple[bool, str]:
    """post_queue 테이블에 pending 행 추가. (성공여부, id 또는 오류메시지)"""
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
    """status=pending 인 행만 반환합니다."""
    endpoint = f"{url}/rest/v1/{_TABLE}?status=eq.pending&order=created_at.asc"
    try:
        resp = requests.get(endpoint, headers=_headers(key), timeout=15)
        resp.raise_for_status()
        return resp.json()
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
