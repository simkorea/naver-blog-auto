"""
leonardo_generator.py — Leonardo AI 이미지 생성 API 전담 모듈.

지원 기능:
  1. 텍스트 → 이미지 (text-to-image)
  2. 업로드 이미지 → 이미지 (image-to-image)
"""

import json
import time
import requests

LEO_API = "https://cloud.leonardo.ai/api/rest/v1"


def _json_headers(api_key: str) -> dict:
    return {
        "accept": "application/json",
        "content-type": "application/json",
        "authorization": f"Bearer {api_key}",
    }


def _get_headers(api_key: str) -> dict:
    return {
        "accept": "application/json",
        "authorization": f"Bearer {api_key}",
    }


# ─────────────────────────────────────────────
# 1. 이미지 업로드 (init-image)
# ─────────────────────────────────────────────

def upload_init_image(image_data: bytes, ext: str, api_key: str) -> str:
    """
    이미지 바이트를 Leonardo S3에 업로드하고 init_image_id를 반환합니다.
    ext: 'jpg' | 'png' | 'webp'
    """
    # 1단계: presigned URL 요청
    r = requests.post(
        f"{LEO_API}/init-image",
        json={"extension": ext.lower().replace("jpeg", "jpg")},
        headers=_json_headers(api_key),
        timeout=30,
    )
    r.raise_for_status()

    info = r.json()["uploadInitImage"]
    image_id  = info["id"]
    upload_url = info["url"]
    fields    = info["fields"]
    if isinstance(fields, str):
        fields = json.loads(fields)

    # 2단계: S3 멀티파트 업로드
    s3_resp = requests.post(
        upload_url,
        data=fields,
        files={"file": (f"image.{ext}", image_data, f"image/{ext}")},
        timeout=60,
    )
    if s3_resp.status_code not in (200, 204):
        raise RuntimeError(f"S3 업로드 실패 ({s3_resp.status_code}): {s3_resp.text[:200]}")

    return image_id


# ─────────────────────────────────────────────
# 2. 생성 요청
# ─────────────────────────────────────────────

def _request_generation(payload: dict, api_key: str) -> str:
    """공통 generation 요청. generation_id 반환."""
    r = requests.post(
        f"{LEO_API}/generations",
        json=payload,
        headers=_json_headers(api_key),
        timeout=30,
    )
    # photoReal/alchemy 권한 없으면 기본 모드 재시도
    if r.status_code == 400 and any(k in r.text for k in ["alchemy", "unauthorized", "unexpected"]):
        payload.pop("photoReal", None)
        payload.pop("alchemy", None)
        r = requests.post(
            f"{LEO_API}/generations",
            json=payload,
            headers=_json_headers(api_key),
            timeout=30,
        )
    r.raise_for_status()
    return r.json()["sdGenerationJob"]["generationId"]


def generate_text_to_image(
    prompt: str,
    api_key: str,
    num_images: int = 1,
    width: int = 1024,
    height: int = 1024,
) -> str:
    """텍스트 프롬프트로 이미지 생성 요청. generation_id 반환."""
    payload = {
        "prompt": prompt,
        "num_images": num_images,
        "width": width,
        "height": height,
        "photoReal": True,
        "alchemy": True,
    }
    return _request_generation(payload, api_key)


def generate_image_to_image(
    prompt: str,
    init_image_id: str,
    strength: float,
    api_key: str,
    num_images: int = 1,
    width: int = 1024,
    height: int = 1024,
) -> str:
    """
    업로드 이미지 기반 생성 요청. generation_id 반환.
    strength: 0.1(원본 무시) ~ 0.9(원본 최대 반영)
    """
    payload = {
        "prompt": prompt,
        "num_images": num_images,
        "width": width,
        "height": height,
        "init_image_id": init_image_id,
        "init_strength": round(max(0.1, min(0.9, strength)), 2),
    }
    return _request_generation(payload, api_key)


# ─────────────────────────────────────────────
# 3. 생성 완료 폴링
# ─────────────────────────────────────────────

def poll_until_complete(
    generation_id: str,
    api_key: str,
    max_wait: int = 150,
    on_tick=None,
) -> list:
    """
    생성 완료까지 5초 간격으로 폴링.
    완료 시 이미지 URL 목록 반환. 실패/타임아웃 시 빈 리스트.
    on_tick: 매 틱마다 호출할 콜백 (elapsed: int) - UI 업데이트용
    """
    h = _get_headers(api_key)
    elapsed = 0

    for _ in range(max_wait // 5):
        time.sleep(5)
        elapsed += 5
        if on_tick:
            on_tick(elapsed)

        try:
            r = requests.get(
                f"{LEO_API}/generations/{generation_id}",
                headers=h,
                timeout=20,
            )
            if r.status_code == 200:
                data   = r.json().get("generations_by_pk", {})
                status = data.get("status", "")
                if status == "COMPLETE":
                    return [img["url"] for img in data.get("generated_images", []) if img.get("url")]
                if status == "FAILED":
                    return []
        except Exception:
            pass

    return []


# ─────────────────────────────────────────────
# 4. 이미지 다운로드
# ─────────────────────────────────────────────

def download_image(url: str, save_path: str) -> bool:
    """URL에서 이미지를 다운로드하여 저장. 성공 시 True."""
    try:
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        with open(save_path, "wb") as f:
            f.write(r.content)
        return True
    except Exception as e:
        print(f"[경고] 이미지 다운로드 실패: {e}")
        return False
