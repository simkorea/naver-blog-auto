"""
cta_presets.py - 글 끝에 붙일 CTA 블록 프리셋 관리

CTA 하나는 아래 요소를 자유롭게 조합합니다 (전부 선택 사항):
    text  : 문구 (여러 줄 가능)
    link  : URL - 상담 신청 페이지, 카카오톡 채널 등
    image : 이미지 파일 경로 - 배너/프로필
    map   : 주소 문자열 - 현장·홍보관 위치

프리셋은 cta_presets.json 에 저장하고, 발행할 때 그때그때 골라 씁니다.
"""
import json
from pathlib import Path

PRESET_FILE = Path("cta_presets.json")

_FIELDS = ("name", "text", "link", "image", "map")


def _empty() -> dict:
    return {k: "" for k in _FIELDS}


def load_presets(path: Path | str = PRESET_FILE) -> list:
    """저장된 CTA 프리셋 목록을 반환합니다. 파일이 없으면 빈 목록."""
    path = Path(path)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            return []
        # 누락된 키가 있어도 깨지지 않도록 기본값으로 채웁니다.
        return [{**_empty(), **{k: str(p.get(k, "")) for k in _FIELDS}}
                for p in data if isinstance(p, dict)]
    except Exception:
        return []


def save_presets(presets: list, path: Path | str = PRESET_FILE) -> None:
    path = Path(path)
    cleaned = [{k: str(p.get(k, "")).strip() for k in _FIELDS} for p in presets]
    path.write_text(json.dumps(cleaned, ensure_ascii=False, indent=2), encoding="utf-8")


def get_preset(name: str, path: Path | str = PRESET_FILE) -> dict | None:
    """이름으로 프리셋 하나를 찾습니다."""
    if not name:
        return None
    for p in load_presets(path):
        if p.get("name") == name:
            return p
    return None


def is_empty(preset: dict | None) -> bool:
    """내용이 하나도 없는 프리셋인지 확인합니다."""
    if not preset:
        return True
    return not any(str(preset.get(k, "")).strip() for k in ("text", "link", "image", "map"))


def summary(preset: dict) -> str:
    """목록에 보여줄 한 줄 요약."""
    parts = []
    if str(preset.get("text", "")).strip():
        parts.append("문구")
    if str(preset.get("link", "")).strip():
        parts.append("링크")
    if str(preset.get("image", "")).strip():
        parts.append("이미지")
    if str(preset.get("map", "")).strip():
        parts.append("지도")
    return " · ".join(parts) if parts else "비어 있음"
