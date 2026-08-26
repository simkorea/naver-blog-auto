# -*- coding: utf-8 -*-
"""
증거파인더 전역 설정.

여기서 하는 일
  1. 경로 결정 (DB, 작업 폴더, 산출물 폴더)
  2. GPU 자동 감지 → Whisper / 임베딩 모델 실행 방식 결정
  3. 오프라인 모드 스위치 (기본 켜짐 = 외부 전송 전면 차단)
  4. 사용자 편집 설정 파일(YAML) 로드 · 최초 생성

설계 원칙: 사용자가 환경을 신경 쓰지 않아도 되게 한다.
GPU가 없거나 라이브러리가 없으면 조용히 낮은 설정으로 내려간다.
"""
import os
import sys
import shutil
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:      # python-dotenv 미설치 시에도 동작
    pass

# ─────────────────────────────────────────────────────────
# 경로
# ─────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent          # .../evidence
PROJECT_DIR = BASE_DIR.parent                       # 레포 루트

DB_PATH = Path(os.getenv("EVIDENCE_DB", PROJECT_DIR / "evidence.db"))
WORK_DIR = Path(os.getenv("EVIDENCE_WORK", PROJECT_DIR / "evidence_work"))
LAW_CACHE_DIR = Path(os.getenv("LAW_CACHE", PROJECT_DIR / "law_cache"))
INGEST_LOG = WORK_DIR / "ingest_log.jsonl"

# 사용자 편집 설정 파일 (개인정보 포함 → .gitignore 대상)
CASE_TERMS_YAML = BASE_DIR / "case_terms.yaml"
KEYWORDS_YAML = BASE_DIR / "keywords.yaml"
LAW_SCOPE_YAML = BASE_DIR / "law_scope.yaml"

for _d in (WORK_DIR, LAW_CACHE_DIR):
    _d.mkdir(parents=True, exist_ok=True)


# ─────────────────────────────────────────────────────────
# 오프라인 모드 — 기본은 완전 차단
# ─────────────────────────────────────────────────────────
def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "y", "on", "예")


# True면 증거 텍스트가 외부 API로 나가지 않는다.
# 법령·판례 조회(법제처)는 증거를 보내지 않고 받아오기만 하므로 별도 스위치로 관리.
OFFLINE_ONLY = _env_bool("OFFLINE_ONLY", True)
ALLOW_LAW_API = _env_bool("ALLOW_LAW_API", True)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
HF_TOKEN = os.getenv("HF_TOKEN", "")
LAW_OC = os.getenv("LAW_OC", "")


# ─────────────────────────────────────────────────────────
# 하드웨어 감지
# ─────────────────────────────────────────────────────────
_HW = None


def hardware() -> dict:
    """GPU 사용 가능 여부를 한 번만 조사해 캐시한다."""
    global _HW
    if _HW is not None:
        return _HW

    info = {
        "device": "cpu",
        "compute_type": "int8",
        "gpu_name": None,
        "vram_gb": None,
        "torch": False,
    }
    try:
        import torch
        info["torch"] = True
        if torch.cuda.is_available():
            props = torch.cuda.get_device_properties(0)
            info.update(
                device="cuda",
                compute_type="float16",
                gpu_name=props.name,
                vram_gb=round(props.total_memory / 1024**3, 1),
            )
        elif getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            # 맥(Apple Silicon). faster-whisper는 mps를 직접 지원하지 않아 CPU로 두되
            # 임베딩 모델은 mps를 쓸 수 있게 표시만 남긴다.
            info["embed_device"] = "mps"
    except BaseException:
        pass

    info.setdefault("embed_device", info["device"])
    _HW = info
    return _HW


# ─────────────────────────────────────────────────────────
# 모델 선택
# ─────────────────────────────────────────────────────────
# 1차 전사 모델 / 2차 교차검증 모델.
# 한국어에서는 두 모델의 우열이 샘플마다 갈리므로 어느 하나를 믿지 않고 대조한다.
WHISPER_PRIMARY = os.getenv("WHISPER_PRIMARY", "large-v3")
WHISPER_SECONDARY = os.getenv("WHISPER_SECONDARY", "large-v3-turbo")
CROSS_VERIFY = _env_bool("CROSS_VERIFY", True)

EMBED_MODEL = os.getenv("EMBED_MODEL", "BAAI/bge-m3")
EMBED_DIM = 1024                                   # bge-m3 출력 차원
DIARIZE_MODEL = os.getenv("DIARIZE_MODEL", "pyannote/speaker-diarization-3.1")


def whisper_options() -> dict:
    """
    faster-whisper 전사 옵션.

    각 값의 이유:
      vad_filter               무음 구간에서 Whisper가 학습 데이터 문장을 지어낸다
                               ("시청해주셔서 감사합니다" 류). 증거 문서에 섞이면 치명적.
      condition_on_previous_text=False
                               한국어 장시간 통화에서 같은 문장이 무한 반복되는 고질 버그 차단.
      word_timestamps          발췌 구간을 단어 경계에 맞춰 자르기 위해 필요.
    """
    return {
        "language": "ko",
        "beam_size": 5,
        "word_timestamps": True,
        "condition_on_previous_text": False,
        "vad_filter": True,
        "vad_parameters": {
            "threshold": 0.5,
            "min_silence_duration_ms": 1000,
            "speech_pad_ms": 200,
        },
    }


# ─────────────────────────────────────────────────────────
# 파일 종류 판별
# ─────────────────────────────────────────────────────────
AUDIO_EXT = {".m4a", ".mp3", ".wav", ".aac", ".flac", ".ogg", ".wma", ".amr", ".3gp"}
VIDEO_EXT = {".mp4", ".mov", ".avi", ".mkv", ".wmv"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp", ".tif", ".tiff"}
DOC_EXT = {".pdf", ".docx", ".doc", ".xlsx", ".xls", ".hwp", ".hwpx", ".txt", ".md", ".eml", ".rtf"}

KIND_AUDIO, KIND_IMAGE, KIND_DOC, KIND_KAKAO, KIND_EMAIL = (
    "audio", "image", "document", "kakao", "email",
)


def classify(path) -> str | None:
    """확장자로 파일 종류를 정한다. 모르는 형식은 None (건너뜀)."""
    p = Path(path)
    ext = p.suffix.lower()
    if ext in AUDIO_EXT or ext in VIDEO_EXT:
        return KIND_AUDIO
    if ext in IMAGE_EXT:
        return KIND_IMAGE
    if ext == ".eml":
        return KIND_EMAIL
    if ext == ".txt":
        # 카카오톡 내보내기인지 내용 앞부분으로 판별
        try:
            head = p.open("r", encoding="utf-8", errors="ignore").read(2000)
            if ("님과 카카오톡 대화" in head or "저장한 날짜" in head
                    or "카카오톡 대화" in head):
                return KIND_KAKAO
        except OSError:
            pass
        return KIND_DOC
    if ext in DOC_EXT:
        return KIND_DOC
    return None


# ─────────────────────────────────────────────────────────
# ffmpeg 위치
# ─────────────────────────────────────────────────────────
def ffmpeg_path() -> str | None:
    """
    imageio-ffmpeg가 함께 설치하는 바이너리를 우선 사용한다.
    (윈도우에서 사용자가 ffmpeg을 따로 설치할 필요가 없게 하기 위함)
    """
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except BaseException:
        return shutil.which("ffmpeg")


# ─────────────────────────────────────────────────────────
# 진단
# ─────────────────────────────────────────────────────────
def diagnose() -> list[tuple[str, bool, str]]:
    """설치 상태 점검. (항목, 정상여부, 메시지) 목록을 돌려준다."""
    out = []
    hw = hardware()

    if hw["device"] == "cuda":
        out.append(("GPU", True, f"{hw['gpu_name']} (VRAM {hw['vram_gb']}GB) — CUDA 가속 사용"))
    elif hw["torch"]:
        out.append(("GPU", False, "GPU 미감지 → CPU로 동작 (전사 속도가 크게 느려집니다)"))
    else:
        out.append(("GPU", False, "torch 미설치 → 음성 전사 불가"))

    checks = [
        ("음성 인식", "faster_whisper", "faster-whisper"),
        ("화자 분리", "pyannote.audio", "pyannote.audio"),
        ("의미 검색", "sentence_transformers", "sentence-transformers"),
        ("벡터 검색", "sqlite_vec", "sqlite-vec"),
        ("PDF 추출", "pdfplumber", "pdfplumber"),
        ("워드 추출", "docx", "python-docx"),
        ("엑셀 추출", "openpyxl", "openpyxl"),
        ("이미지 OCR", "easyocr", "easyocr"),
    ]
    for label, module, pkg in checks:
        # BaseException까지 잡는다. 네이티브 확장이 깨져 있으면 Exception이 아니라
        # 인터프리터 수준 패닉(pyo3 PanicException 등)이 올라오는데, 그것 하나 때문에
        # 프로그램 전체가 죽어서는 안 된다.
        try:
            __import__(module)
            out.append((label, True, "설치됨"))
        except ImportError:
            out.append((label, False, f"미설치 → pip install {pkg}"))
        except BaseException as e:
            out.append((label, False, f"설치되었으나 불러오지 못함 ({type(e).__name__}) "
                                      f"→ pip install --force-reinstall {pkg}"))

    out.append(("ffmpeg", bool(ffmpeg_path()),
                ffmpeg_path() or "미설치 → pip install imageio-ffmpeg"))
    out.append(("화자분리 토큰", bool(HF_TOKEN),
                "설정됨" if HF_TOKEN else ".env에 HF_TOKEN 필요 (huggingface.co에서 무료 발급)"))
    out.append(("법령 API 키", bool(LAW_OC),
                "설정됨" if LAW_OC else ".env에 LAW_OC 필요 (open.law.go.kr에서 무료 발급)"))
    out.append(("오프라인 모드", OFFLINE_ONLY,
                "켜짐 — 증거 텍스트가 외부로 나가지 않습니다"
                if OFFLINE_ONLY else "꺼짐 — 외부 LLM API 사용이 허용된 상태입니다"))
    return out


if __name__ == "__main__":
    from evidence.console import marks, setup as _console_setup
    _console_setup()
    _m = marks()
    print("증거파인더 환경 점검\n" + _m["line"] * 60)
    for label, ok, msg in diagnose():
        print(f"  {_m['ok'] if ok else _m['no']}  {label:12s} {msg}")
    print(_m["line"] * 60)
    print(f"  DB      : {DB_PATH}")
    print(f"  작업폴더 : {WORK_DIR}")
    sys.exit(0)
