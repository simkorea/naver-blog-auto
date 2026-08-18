"""
Supabase 연동 모듈 - 발행 대기열 + Storage 이미지 관리
requests 만 사용 (이미 requirements.txt에 포함)
"""
import json
import re
import datetime
from pathlib import Path
import requests

_TABLE  = "post_queue"
_BUCKET = "post-images"


def sanitize_path_component(value: str, fallback: str = "untitled") -> str:
    """post_queue 행에서 온 값(date, local_folder 등)을 파일 경로 조각으로 안전하게 정리합니다.

    외부(Supabase INSERT 정책이 열려 있으면 인증 없는 제3자 포함)에서 들어온 문자열이
    그대로 파일 경로에 쓰이면 path traversal(예: "../../..")에 노출되므로,
    경로 구분자·상위 디렉터리 이동·NUL 바이트를 제거하고 길이를 제한합니다.
    """
    value = (value or "").replace("\x00", "")
    value = re.sub(r"[/\\]+", "_", value)   # 경로 구분자 -> 밑줄
    value = value.replace("..", "_")        # 상위 디렉터리 이동 차단
    value = value.strip(" ._")[:100]
    return value or fallback


def _headers(key: str) -> dict:
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


# ==========================================================
# Supabase Storage - 이미지 업로드 / 다운로드
# ==========================================================

def _storage_headers(key: str, content_type: str = "application/json") -> dict:
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": content_type,
    }


def _ensure_bucket(url: str, key: str) -> None:
    """post-images 버킷이 없으면 공개 버킷으로 자동 생성합니다."""
    hdrs = _storage_headers(key)
    try:
        resp = requests.get(f"{url}/storage/v1/bucket", headers=hdrs, timeout=10)
        buckets = resp.json() if resp.ok else []
        if any(b.get("name") == _BUCKET for b in buckets):
            return
        requests.post(
            f"{url}/storage/v1/bucket",
            json={"id": _BUCKET, "name": _BUCKET, "public": True},
            headers=hdrs,
            timeout=10,
        )
    except Exception:
        pass


_EXT_CT = {
    "jpg": "image/jpeg", "jpeg": "image/jpeg",
    "png": "image/png",  "webp": "image/webp", "gif": "image/gif",
}


def upload_images_to_storage(
    url: str,
    key: str,
    folder_key: str,
    image_paths: list,
) -> list[str]:
    """이미지 파일 목록을 Supabase Storage에 업로드하고 공개 URL 목록을 반환합니다.

    folder_key : Storage 내 폴더명 (ex. "20260501_의왕화재")
    반환값     : 각 이미지의 공개 URL 리스트 (순서 유지)
    """
    _ensure_bucket(url, key)
    public_urls: list[str] = []

    for idx, img_path in enumerate(image_paths):
        p = Path(img_path)
        if not p.exists():
            print(f"  [건너뜀] 파일 없음: {p}")
            continue

        ext          = p.suffix.lower().lstrip(".")
        content_type = _EXT_CT.get(ext, "image/jpeg")
        # 순서 보존을 위해 앞에 3자리 번호 붙임: "001_1.jpg"
        storage_name = f"{idx+1:03d}_{p.name}"
        storage_path = f"{folder_key}/{storage_name}"
        endpoint     = f"{url}/storage/v1/object/{_BUCKET}/{storage_path}"

        try:
            resp = requests.post(
                endpoint,
                data=p.read_bytes(),
                headers=_storage_headers(key, content_type),
                params={"x-upsert": "true"},
                timeout=60,
            )
            resp.raise_for_status()
            public_urls.append(
                f"{url}/storage/v1/object/public/{_BUCKET}/{storage_path}"
            )
            print(f"  [cloud] Storage 업로드 완료: {storage_name}")
        except Exception as e:
            print(f"  x Storage 업로드 실패 ({p.name}): {e}")

    return public_urls


def download_images_from_storage(
    image_urls: list,
    save_dir: str,
) -> list[str]:
    """Supabase Storage에서 이미지를 로컬 폴더에 다운로드합니다.

    이미 존재하는 파일은 건너뜁니다.
    반환값: 저장된 로컬 경로 목록 (순서 유지)
    """
    save_dir_p = Path(save_dir)
    save_dir_p.mkdir(parents=True, exist_ok=True)
    saved: list[str] = []

    for img_url in image_urls:
        raw_name   = img_url.split("/")[-1]
        clean_name = re.sub(r"^\d{3}_", "", raw_name)   # "001_1.jpg" -> "1.jpg"
        save_path  = save_dir_p / clean_name

        if save_path.exists():
            saved.append(str(save_path))
            continue

        try:
            resp = requests.get(img_url, timeout=30)
            resp.raise_for_status()
            save_path.write_bytes(resp.content)
            saved.append(str(save_path))
            print(f"  [OK] 이미지 다운로드: {clean_name}")
        except Exception as e:
            print(f"  x 다운로드 실패 ({img_url}): {e}")

    return saved


def push_pending(
    url: str, key: str,
    title: str, content: str, tags: str, local_folder: str,
    scheduled_at: str = "",
    image_urls: list | None = None,
) -> tuple[bool, str]:
    """post_queue 테이블에 pending 행 추가. (성공여부, id 또는 오류메시지)

    scheduled_at: ISO 8601 문자열 (예: '2026-05-02T09:00:00'). 비어 있으면 즉시 발행.
    image_urls  : Supabase Storage 공개 URL 목록. 있으면 JSON 문자열로 저장.
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
    if image_urls:
        payload["image_urls"] = json.dumps(image_urls, ensure_ascii=False)
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
        # or() 구문 미지원 구형 Supabase -> 기존 방식으로 폴백
        try:
            endpoint_fallback = f"{url}/rest/v1/{_TABLE}?status=eq.pending&order=created_at.asc"
            resp2 = requests.get(endpoint_fallback, headers=_headers(key), timeout=15)
            resp2.raise_for_status()
            return resp2.json()
        except Exception:
            return []


def delete_row(url: str, key: str, row_id: str) -> bool:
    """대기열에서 행 하나를 삭제합니다."""
    endpoint = f"{url}/rest/v1/{_TABLE}?id=eq.{row_id}"
    try:
        resp = requests.delete(endpoint, headers=_headers(key), timeout=15)
        resp.raise_for_status()
        return True
    except Exception:
        return False


def delete_rows_by_status(url: str, key: str, statuses: list) -> int:
    """지정한 상태의 행을 모두 삭제하고 삭제 건수를 반환합니다."""
    rows = get_all_rows(url, key)
    targets = [r for r in rows if r.get("status") in statuses]
    return sum(1 for r in targets if delete_row(url, key, r.get("id")))


def reset_stuck_rows(url: str, key: str, row_ids: list) -> int:
    """멈춘 행을 다시 pending 으로 되돌립니다.

    업로드 중 브라우저가 죽으면 status 가 processing 에 남아 영원히 처리되지
    않는데, 이 함수로 되돌려야 watcher 가 다시 집어갑니다.
    """
    n = 0
    for rid in row_ids:
        if update_status(url, key, rid, "pending", ""):
            n += 1
    return n


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
