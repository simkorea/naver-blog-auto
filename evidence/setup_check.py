# -*- coding: utf-8 -*-
"""
설치 도우미 — 이 파일 하나만 실행하면 필요한 것을 알아서 깔아준다.

    python evidence/setup_check.py            설치 상태만 점검
    python evidence/setup_check.py --install  부족한 것 설치
    python evidence/setup_check.py --models   AI 모델 미리 받아두기

왜 별도 스크립트인가
  requirements.txt 하나로는 안 되는 것들이 있다.
    · torch는 GPU 유무에 따라 받아야 할 것이 다르다 (CUDA 빌드 vs CPU 빌드)
    · Whisper·임베딩 모델은 첫 실행 때 수 GB를 받는다. 급할 때
      그 다운로드를 기다리는 것보다 미리 받아두는 편이 낫다
    · 뭐가 빠졌는지 사람이 알아보게 알려줘야 한다
"""
import argparse
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT.parent) not in sys.path:
    sys.path.insert(0, str(ROOT.parent))

# 한국어 윈도우 콘솔(cp949)에서 기호 출력에 죽지 않도록 맨 먼저 준비한다
from evidence.console import marks, setup as _console_setup

_console_setup()
M = marks()
REQ = ROOT / "requirements-evidence.txt"

# (표시 이름, import 이름, pip 이름, 없으면 무엇을 못 하는가)
PACKAGES = [
    ("화면",        "streamlit",             "streamlit>=1.40",              "프로그램 자체"),
    ("음성 인식",    "faster_whisper",        "faster-whisper>=1.1.0",        "녹음 전사"),
    ("화자 분리",    "pyannote.audio",        "pyannote.audio>=3.3.0,<4",     "누가 말했는지 구분"),
    ("의미 검색",    "sentence_transformers", "sentence-transformers>=3.0.0", "문장으로 검색"),
    ("벡터 검색",    "sqlite_vec",            "sqlite-vec>=0.1.6",            "문장으로 검색"),
    ("PDF 추출",    "pdfplumber",            "pdfplumber>=0.11.0",           "PDF 문서 읽기"),
    ("PDF 이미지",  "pypdfium2",             "pypdfium2>=4.30.0",            "스캔한 PDF 글자 읽기"),
    ("워드 문서",    "docx",                  "python-docx>=1.1.0",           "워드 읽기·제출 문서 만들기"),
    ("엑셀 문서",    "openpyxl",              "openpyxl>=3.1.0",              "엑셀 읽기·증거목록 만들기"),
    ("이미지 OCR",  "easyocr",               "easyocr>=1.7.0",               "사진·캡처 글자 읽기"),
    ("이미지 처리",  "PIL",                   "Pillow>=10.0.0",               "이미지 처리"),
    ("오디오 도구",  "imageio_ffmpeg",        "imageio-ffmpeg>=0.5.1",        "발췌본 잘라내기"),
    ("법령 조회",    "requests",              "requests>=2.31.0",             "법령·판례 받아오기"),
    ("설정 파일",    "yaml",                  "PyYAML>=6.0",                  "쟁점 사전"),
    ("환경 변수",    "dotenv",                "python-dotenv>=1.0.0",         "인증키 읽기"),
]

# 그래픽카드 세대마다 필요한 CUDA 버전이 다르다.
# RTX 50 시리즈(Blackwell)는 CUDA 12.8 이상이어야 한다. 12.4 빌드를 깔면
# 카드는 인식되는데 정작 연산에서 터진다 — 더 나쁜 실패다.
CUDA_INDEX_DEFAULT = "https://download.pytorch.org/whl/cu126"
CUDA_INDEX_BLACKWELL = "https://download.pytorch.org/whl/cu128"

# RTX 50 시리즈 · 최신 워크스테이션 카드
_BLACKWELL = ("rtx 50", "rtx50", "5050", "5060", "5070", "5080", "5090",
              "rtx pro", "b200", "gb200")

# torch 계열은 버전이 서로 묶여 있다. 하나만 따로 깔거나 지우면
# DLL 이 어긋나 "코드 실행을 계속할 수 없습니다" 시스템 오류 창이 뜬다.
# 반드시 **같은 CUDA 저장소에서 함께** 다뤄야 한다.
#
# 각각이 왜 필요한가:
#   torch        모든 것의 토대
#   torchvision  easyocr 가 요구 -> 이미지·스캔 PDF 글자 읽기
#   torchaudio   pyannote 가 요구 -> 화자 분리
#
# torchcodec 은 여기 없다. pyannote.audio **4.x** 만 이걸 요구하는데,
# 윈도우용 배포판이 아예 없다(pip 이 "from versions: none" 을 낸다).
# 게다가 우리가 쓰는 화자 분리 모델 speaker-diarization-3.1 은 원래
# pyannote.audio 3.x 용이다. 그래서 3.x 로 고정해 이 문제 자체를 없앤다.
# (requirements-evidence.txt 에 pyannote.audio<4 로 박아두었다)
TORCH_CORE = ("torch", "torchvision", "torchaudio")
TORCH_PKGS = TORCH_CORE

# 검증된 조합으로 고정한다. "최신"을 쓰면 안 되는 이유:
#   torchaudio 2.9 부터 AudioMetaData 와 info() 를 걷어냈는데,
#   pyannote.audio 3.x 가 바로 그것들을 쓴다. 최신을 깔면 화자 분리가
#   "AttributeError" 로 죽는다. 설치는 성공한 것처럼 보여서 더 헷갈린다.
#
# 2.8.0 을 고른 이유:
#   · torchaudio 에 아직 그 함수들이 있다 (pyannote 3.x 동작)
#   · cu128 빌드가 있다 (RTX 50 시리즈 지원)
#   · torchvision 0.23.0 과 짝이 맞는다 (easyocr 동작)
TORCH_PINS = {
    "torch": "2.8.0",
    "torchvision": "0.23.0",
    "torchaudio": "2.8.0",
}


def _pinned(pkgs) -> list[str]:
    """고정 버전을 붙인 설치 인자."""
    return [f"{p}=={TORCH_PINS[p]}" if p in TORCH_PINS else p for p in pkgs]


def pyannote_compatible() -> tuple[bool, str]:
    """
    화자 분리가 실제로 돌아갈 수 있는 조합인지 본다.

    설치 목록만 봐서는 알 수 없다. 둘 다 설치되어 있는데 서로 안 맞는
    경우가 있고, 그게 지금 문제다.
    """
    try:
        import torchaudio
    except BaseException:
        return False, "torchaudio 가 없습니다"

    missing = [n for n in ("AudioMetaData", "info") if not hasattr(torchaudio, n)]
    if missing:
        return False, (
            f"torchaudio {getattr(torchaudio, '__version__', '?')} 에서 "
            f"{', '.join(missing)} 가 사라졌습니다. 화자 분리(pyannote 3.x)가 "
            f"이것을 씁니다."
        )
    return True, ""


def cuda_index_for(gpu_name: str | None) -> str:
    """카드 이름을 보고 맞는 CUDA 빌드를 고른다."""
    name = (gpu_name or "").lower()
    if any(k in name for k in _BLACKWELL):
        return CUDA_INDEX_BLACKWELL
    return CUDA_INDEX_DEFAULT


def _run(cmd, **kw):
    return subprocess.run(cmd, **kw)


def _pip(*args, quiet=False) -> int:
    cmd = [sys.executable, "-m", "pip", "install", *args]
    if quiet:
        cmd.insert(4, "--quiet")
    print(f"    실행: {' '.join(cmd[4:])}")
    return _run(cmd).returncode


def _installed(module: str) -> tuple[bool, str]:
    """
    설치 여부. BaseException까지 잡는 이유는, 네이티브 확장이 깨져 있으면
    Exception이 아니라 인터프리터 수준 패닉이 올라오기 때문이다.
    """
    try:
        __import__(module)
        return True, ""
    except ImportError:
        return False, "미설치"
    except BaseException as e:
        return False, f"불러오기 실패 ({type(e).__name__})"


# ─────────────────────────────────────────────────────────
# GPU
# ─────────────────────────────────────────────────────────
def detect_nvidia() -> str | None:
    """nvidia-smi로 그래픽카드 이름을 확인한다."""
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None
    try:
        r = _run([exe, "--query-gpu=name", "--format=csv,noheader"],
                 capture_output=True, text=True, timeout=20)
        name = (r.stdout or "").strip().splitlines()
        return name[0] if name and name[0] else None
    except Exception:
        return None


def torch_status() -> dict:
    ok, why = _installed("torch")
    if not ok:
        return {"installed": False, "cuda": False, "reason": why}
    try:
        import torch
        return {
            "installed": True,
            "version": torch.__version__,
            "cuda": torch.cuda.is_available(),
            "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
            "is_cpu_build": "+cpu" in torch.__version__,
        }
    except BaseException as e:
        return {"installed": False, "cuda": False, "reason": str(e)}


def install_torch(force: bool = False) -> bool:
    """
    GPU가 있으면 CUDA 빌드를, 없으면 CPU 빌드를 깐다.

    이게 사람들이 가장 많이 틀리는 부분이다. 그냥 `pip install torch` 하면
    GPU가 있어도 CPU 빌드가 깔려서 전사가 10배 느린데 원인을 모른다.

    force=True 는 다른 패키지가 torch 를 CPU 빌드로 덮어쓴 뒤 되돌릴 때 쓴다.
    """
    gpu = detect_nvidia()
    st = torch_status()

    if st["installed"] and st.get("cuda") and not force and not _family_broken():
        print(f"    이미 GPU 가속으로 설치되어 있습니다 - {st['gpu']}")
        return True

    if not gpu:
        if st["installed"] and not force:
            print("    이미 설치되어 있습니다 (CPU 전용)")
            return True
        print("    그래픽카드가 없어 CPU 빌드를 설치합니다")
        print("    (녹음 전사가 느립니다. 1시간 녹음에 20~40분)")
        return _pip(*_pinned(TORCH_CORE)) == 0

    index = cuda_index_for(gpu)
    tag = index.rsplit("/", 1)[-1]

    if st["installed"] and not st.get("cuda"):
        print(f"    그래픽카드({gpu})가 있는데 CPU 전용 torch 가 깔려 있습니다.")
        print("    GPU 빌드로 다시 설치합니다 (전사 속도가 5~10배 빨라집니다).")
    else:
        print(f"    그래픽카드 감지: {gpu}")

    # 섞인 버전이 남아 있으면 DLL 이 어긋난다. 계열 전체를 먼저 걷어낸다.
    _pip("uninstall", "-y", *TORCH_PKGS)

    print(f"    {tag} 빌드를 설치합니다 (2GB 내외, 몇 분 걸립니다)")
    args = _pinned(TORCH_CORE)
    rc = _pip(*args, "--index-url", index)
    if rc != 0 and index != CUDA_INDEX_DEFAULT:
        print(f"    {tag} 설치 실패 -> 기본 CUDA 빌드로 시도합니다")
        index = CUDA_INDEX_DEFAULT
        rc = _pip(*args, "--index-url", index)
    if rc != 0:
        # 고정 버전이 이 환경에 없을 수도 있다. 버전 없이 한 번 더.
        print("    고정 버전 설치 실패 -> 버전 지정 없이 시도합니다")
        rc = _pip(*TORCH_CORE, "--index-url", index)
    if rc != 0:
        print("    CUDA 빌드 실패 -> CPU 빌드로 시도합니다")
        rc = _pip(*_pinned(TORCH_CORE))

    return rc == 0


def fix_pyannote_version() -> bool:
    """
    화자 분리 패키지를 3.x 로 맞춘다.

    4.x 는 torchcodec 을 요구하는데 윈도우용 배포판이 없어 설치가 통째로
    실패한다. 우리가 쓰는 모델(speaker-diarization-3.1)도 3.x 용이므로
    3.x 가 맞는 선택이다.
    """
    import importlib.metadata as md

    try:
        current = md.version("pyannote.audio")
    except BaseException:
        return False

    major = current.split(".")[0]
    if major.isdigit() and int(major) >= 4:
        print(f"    화자 분리 {current} -> 3.x 로 맞춥니다")
        print("       (4.x 는 윈도우에 없는 부품을 요구합니다)")
        return _pip("pyannote.audio>=3.3,<4") == 0
    return True


def torch_family_status() -> dict:
    """
    torch 계열이 서로 맞는지 본다.

    torch 는 cu128 인데 torchvision 이 없거나 CPU 빌드면, 설치는 되어 있는데
    쓸 때 터진다. 그 상태를 사용자가 화면에서 바로 알 수 있어야 한다.
    """
    import importlib.metadata as md

    found, missing, tags = {}, [], set()
    for pkg in TORCH_PKGS:
        module = pkg.replace("-", "_")
        try:
            __import__(module)
            version = md.version(pkg)
            found[pkg] = version
            # 빌드 표시가 없는 것도 하나의 값으로 센다.
            # torch 는 +cu128 인데 torchvision 은 표시가 없다면, 그것이야말로
            # 다른 곳(PyPI CPU 빌드)에서 온 것이라 어긋난 상태다.
            # 표시가 있는 것만 모으면 이 경우를 놓친다.
            tags.add(version.split("+", 1)[1] if "+" in version else "표시없음")
        except BaseException:
            missing.append(pkg)

    core_missing = [p for p in missing if p in TORCH_CORE]
    return {
        "found": found,
        "missing": missing,
        "core_missing": core_missing,
        "tags": sorted(tags),
        "mismatched": len(tags) > 1 or bool(core_missing),
    }


def _family_broken() -> bool:
    fam = torch_family_status()
    if fam["found"] and fam["mismatched"]:
        return True
    # 버전은 서로 맞는데 화자 분리와 안 맞는 경우도 고쳐야 한다
    try:
        import pyannote.audio          # noqa: F401
    except BaseException:
        return False
    ok, _ = pyannote_compatible()
    return not ok


def check_runtime() -> list[tuple[str, bool, str]]:
    """
    설치되어 있다고 끝이 아니다. 실제로 불러봐야 안다.

    DLL 이 어긋나 있으면 import 는 되는데 쓸 때 터지거나, 파이썬을 켜는
    순간 시스템 오류 창이 뜬다. 설치 직후에 한 번씩 실제로 만들어 본다.
    """
    out = []

    try:
        from faster_whisper import WhisperModel      # noqa: F401
        out.append(("녹음 전사", True, "준비됨"))
    except BaseException as e:
        out.append(("녹음 전사", False, f"{type(e).__name__}: {e}"))

    try:
        import easyocr                                # noqa: F401
        import torchvision                            # noqa: F401
        out.append(("이미지 글자 읽기", True, "준비됨"))
    except BaseException as e:
        out.append(("이미지 글자 읽기", False, f"{type(e).__name__}: {e}"))

    try:
        from evidence.ingest import diarize as _d
        _d._ensure_hf_compat()                        # 부르기 전에 간극 메우기
        from pyannote.audio import Pipeline           # noqa: F401
        note = "준비됨 (HF_TOKEN 필요)"
        import huggingface_hub as _hub
        if getattr(getattr(_hub, "hf_hub_download", None), "_evidence_shim", False):
            note = "준비됨 (버전 차이를 자동으로 메움)"
        out.append(("화자 분리", True, note))
    except BaseException as e:
        hint = f"{type(e).__name__}: {str(e)[:120]}"
        if "torchcodec" in str(e).lower():
            hint = ('화자 분리 4.x 가 윈도우에 없는 부품을 찾고 있습니다 -> '
                    'python -m pip install "pyannote.audio>=3.3,<4"')
        else:
            compat_ok, why = pyannote_compatible()
            if not compat_ok:
                hint = f"{why} -> python evidence/setup_check.py --repair"
        out.append(("화자 분리", False, hint))

    try:
        from sentence_transformers import SentenceTransformer  # noqa: F401
        out.append(("의미 검색", True, "준비됨"))
    except BaseException as e:
        out.append(("의미 검색", False, f"{type(e).__name__}: {e}"))

    return out


# ─────────────────────────────────────────────────────────
# 모델 미리 받기
# ─────────────────────────────────────────────────────────
def download_models(whisper: bool = True, embed: bool = True,
                    ocr: bool = True, diarize: bool = True) -> dict:
    """
    첫 실행 때 받을 것을 미리 받아둔다.

    급할 때 다운로드를 기다리는 것만큼 답답한 일이 없다.
    한 번 받아두면 다음부터는 인터넷 없이도 동작한다.

    돌려주는 값: {모델이름: 성공여부}
    하나도 못 받았는데 "준비가 끝났습니다"라고 하면 안 된다.
    사용자가 다 됐다고 믿고 넘어가면 정작 필요할 때 멈춘다.
    """
    from evidence import config

    result = {}

    def _note(name, ok, msg=""):
        result[name] = ok
        mark = M["ok"] if ok else M["no"]
        print(f"        {mark} {msg}" if msg else f"        {mark}")

    if whisper:
        print("\n  [1/4] 음성 인식 모델")
        try:
            from faster_whisper import WhisperModel
            for name in (config.WHISPER_PRIMARY, config.WHISPER_SECONDARY):
                print(f"        {name} 받는 중... (약 1.5GB, 몇 분 걸립니다)")
                WhisperModel(name, device="cpu", compute_type="int8")
                _note(f"whisper:{name}", True, f"{name} 완료")
        except ModuleNotFoundError:
            _note("whisper", False,
                  "faster-whisper 가 설치되지 않았습니다 "
                  "-> python evidence/setup_check.py --install 을 먼저 실행하세요")
        except BaseException as e:
            _note("whisper", False, f"실패 - {type(e).__name__}: {e}")

    if embed:
        print("\n  [2/4] 의미 검색 모델")
        try:
            from sentence_transformers import SentenceTransformer
            print(f"        {config.EMBED_MODEL} 받는 중... (약 2.3GB)")
            SentenceTransformer(config.EMBED_MODEL, device="cpu")
            _note("embed", True, "완료")
        except ModuleNotFoundError:
            _note("embed", False,
                  "sentence-transformers 가 설치되지 않았습니다 "
                  "-> --install 을 먼저 실행하세요")
        except BaseException as e:
            _note("embed", False, f"실패 - {type(e).__name__}: {e}")

    if ocr:
        print("\n  [3/4] 이미지 글자 인식 모델")
        try:
            import easyocr
            print("        한국어 OCR 모델 받는 중... (약 100MB)")
            easyocr.Reader(["ko", "en"], gpu=False, verbose=False)
            _note("ocr", True, "완료")
        except ModuleNotFoundError:
            _note("ocr", False,
                  "easyocr 가 설치되지 않았습니다 -> --install 을 먼저 실행하세요")
        except BaseException as e:
            _note("ocr", False, f"실패 - {type(e).__name__}: {e}")

    if diarize:
        print("\n  [4/4] 화자 분리 모델")
        if not config.HF_TOKEN:
            _note("diarize", False,
                  ".env 에 HF_TOKEN 이 없습니다 (없어도 나머지는 동작합니다)")
        else:
            try:
                # 화자 분리를 실제로 쓰는 경로와 똑같이 부른다.
                # 여기서만 따로 호출하면 호환 처리가 빠져 "받을 때는 됐는데
                # 쓸 때 죽는" 상황이 생긴다.
                from evidence.ingest import diarize as _diarize
                print("        받는 중... (약 200MB)")
                _diarize.get_pipeline()
                _note("diarize", True, "완료")
            except ModuleNotFoundError:
                _note("diarize", False,
                      "pyannote.audio 가 설치되지 않았습니다 -> --install 을 먼저 실행하세요")
            except BaseException as e:
                _note("diarize", False, f"실패 - {str(e)[:160]}")
                for line in diarize_failure_hint(e):
                    print(f"        {line}")

    return result


def diarize_failure_hint(err: BaseException) -> list[str]:
    """
    화자 분리 실패 원인에 맞는 안내를 고른다.

    예전에는 무슨 오류든 "약관에 동의하셨는지 확인하세요" 라고 했다.
    실제로는 라이브러리 버전 문제였는데, 사용자가 이미 동의해 둔 약관 페이지를
    다시 찾아가게 만들었다. 원인을 모르겠으면 모르겠다고 하는 편이 낫다.
    """
    text = f"{type(err).__name__} {err}".lower()

    if "weights only" in text or "weights_only" in text:
        return [
            "torch 의 안전 기본값과 pyannote 체크포인트 형식이 어긋났습니다.",
            "이 프로그램의 최신본에 고쳐져 있습니다 - 최신 파일을 내려받아",
            "다시 실행해 주세요 (약관 문제가 아닙니다).",
        ]
    if "unexpected keyword argument" in text or isinstance(err, TypeError):
        return [
            "라이브러리 버전이 서로 맞지 않습니다 (약관 문제가 아닙니다).",
            "고치는 방법:",
            "    python evidence/setup_check.py --repair",
        ]
    if any(k in text for k in ("401", "403", "gated", "unauthorized",
                               "awaiting a review", "access to model")):
        return [
            "모델 접근 권한이 없습니다. 아래 **두 곳 모두** 동의해야 합니다:",
            "    huggingface.co/pyannote/speaker-diarization-3.1",
            "    huggingface.co/pyannote/segmentation-3.0",
            "동의 후에도 안 되면 토큰을 다시 발급받아 --token 으로 넣어주세요.",
        ]
    if any(k in text for k in ("proxy", "connection", "timeout", "resolve",
                               "network", "max retries")):
        return [
            "인터넷 연결 문제로 보입니다.",
            "회사망·공용 와이파이는 huggingface.co 를 막는 경우가 있습니다.",
        ]
    if "out of memory" in text or "cuda" in text:
        return ["그래픽카드 메모리가 부족합니다. 다른 프로그램을 닫고 다시 시도하세요."]
    return [
        "원인을 특정하지 못했습니다. 위 메시지를 그대로 알려주시면 도움이 됩니다.",
    ]


def _report_models(result: dict) -> None:
    """받은 결과를 정직하게 알려준다."""
    got = [k for k, ok in result.items() if ok]
    missed = [k for k, ok in result.items() if not ok]

    print()
    if not result:
        print("  받을 모델이 없었습니다.")
    elif not got:
        print(f"  {M['no']} 모델을 하나도 받지 못했습니다.")
        print()
        print("     대부분 프로그램이 아직 설치되지 않아서입니다. 먼저 이것을 실행하세요:")
        print("         python evidence/setup_check.py --install")
    elif missed:
        print(f"  {M['ok']} {len(got)}개를 받았습니다. {len(missed)}개는 받지 못했습니다.")
        print("     받지 못한 기능은 프로그램에서 그 부분만 못 쓰고, 나머지는 동작합니다.")
    else:
        print(f"  {M['ok']} 모델 준비가 끝났습니다. 이제 인터넷 없이도 동작합니다.")


def finish_setup() -> int:
    """
    남은 준비를 한 번에 끝낸다 — 모델 받기 → 자체 점검.

    왜 합쳤나
      두 단계를 따로 두면 "다음에 뭘 치더라?"를 매번 물어보게 된다.
      순서가 정해져 있고 사이에 판단할 것이 없다면 하나로 묶는 게 맞다.

    음성 인식 모델을 못 받았으면 자체 점검으로 넘어가지 않는다.
    그게 없으면 점검의 대부분이 실패할 것이고, 3분을 버리게 하는 셈이다.
    """
    ensure_env()

    # 화자 분리 모델은 인증키가 있어야 받는다. 새로 받은 폴더라 인증키만
    # 두고 온 경우가 잦으므로, 받기 전에 옆 폴더를 먼저 살펴본다.
    import os
    if not os.getenv("HF_TOKEN"):
        import_previous_env(ask=True)

    result = download_models()
    _report_models(result)

    whisper_ok = any(ok for k, ok in result.items() if k.startswith("whisper"))
    if not whisper_ok:
        print()
        print(f"  {M['no']} 음성 인식 모델이 없어 자체 점검은 건너뜁니다.")
        print("     위 메시지를 그대로 알려주시면 원인을 찾아드리겠습니다.")
        return 1

    print()
    print(f"  {M['line'] * 60}")
    print("  이어서 자체 점검을 시작합니다 (약 3분).")
    print(f"  {M['line'] * 60}")

    from evidence.selftest import run as run_selftest
    return 0 if run_selftest(M) else 1


# ─────────────────────────────────────────────────────────
# .env
# ─────────────────────────────────────────────────────────
ENV_TEMPLATE = """\
# ════════════════════════════════════════════════════════
#  증거파인더 설정
#  이 파일은 절대 다른 사람에게 보내지 마세요 (인증키가 들어 있습니다).
# ════════════════════════════════════════════════════════

# 화자 분리(누가 말했는지 구분)에 필요합니다. 없으면 그 기능만 못 씁니다.
#   1) huggingface.co 가입 → Settings → Access Tokens → New token (Read)
#   2) huggingface.co/pyannote/speaker-diarization-3.1 에서 약관 동의 (필수!)
HF_TOKEN=

# 법률 코멘트에 필요합니다. 없으면 그 기능만 못 씁니다.
#   open.law.go.kr → OPEN API → 활용신청 (무료, 즉시 발급)
LAW_OC=

# ── 개인정보 보호 ────────────────────────────────
# true면 증거 내용이 외부로 나가지 않습니다. 그대로 두시길 권합니다.
OFFLINE_ONLY=true

# 법령·판례 받아오기 허용 (증거 내용을 보내지 않고 받아오기만 합니다)
ALLOW_LAW_API=true

# ── 선택 ────────────────────────────────────────
# OFFLINE_ONLY=false 로 바꿨을 때만 쓰입니다.
GEMINI_API_KEY=

# 전사 모델. 성능이 부족하면 medium 으로 낮추세요.
# WHISPER_PRIMARY=large-v3
# WHISPER_SECONDARY=large-v3-turbo

# 이중 모델 교차 검증 (끄면 전사가 두 배 빨라지지만 신뢰도 표시가 약해집니다)
# CROSS_VERIFY=true
"""


def ensure_env(quiet: bool = False) -> Path:
    """
    인증키 파일을 준비한다.

    프로그램 폴더가 아니라 홈 폴더에 만든다. 새 버전을 받을 때마다
    인증키를 다시 넣게 만들지 않기 위해서다 (config.ENV_FILE 주석 참고).
    예전 방식으로 프로그램 폴더에 이미 있으면 그것을 그대로 쓴다.
    """
    from evidence import config

    legacy = ROOT.parent / ".env"
    env = legacy if legacy.exists() else config.ENV_FILE
    env.parent.mkdir(parents=True, exist_ok=True)
    if env.exists():
        text = env.read_text(encoding="utf-8", errors="ignore")
        added = []
        for key in ("HF_TOKEN", "LAW_OC", "OFFLINE_ONLY", "ALLOW_LAW_API"):
            if key not in text:
                added.append(key)
        if added:
            with env.open("a", encoding="utf-8") as f:
                f.write("\n# 증거파인더 추가 설정\n")
                for key in added:
                    default = "true" if key in ("OFFLINE_ONLY", "ALLOW_LAW_API") else ""
                    f.write(f"{key}={default}\n")
            if not quiet:
                print(f"    기존 .env에 {', '.join(added)} 항목을 추가했습니다")
        elif not quiet:
            print("    .env 파일이 이미 있습니다")
    else:
        env.write_text(ENV_TEMPLATE, encoding="utf-8")
        if not quiet:
            print(f"    인증키 파일을 만들었습니다: {env}")
            print("    이 파일은 프로그램 새 버전을 받아도 그대로 남습니다.")
            print("    인증키를 넣으려면: python evidence/setup_check.py --token")
    return env


# ─────────────────────────────────────────────────────────
# 점검 · 설치
# ─────────────────────────────────────────────────────────
def report() -> list:
    print("\n" + M["dline"] * 68)
    print("  증거파인더 설치 점검")
    print(M["dline"] * 68)
    print(f"  파이썬 : {sys.version.split()[0]}  ({platform.system()} {platform.machine()})")
    try:
        from evidence import config as _cfg
        print(f"  자료   : {_cfg.DB_PATH.parent}")
        print("           (증거 DB·인증키·사건 사전이 여기 있습니다. "
              "프로그램을 새로 받아도 그대로 남습니다)")
    except BaseException:
        pass

    gpu = detect_nvidia()
    st = torch_status()
    if st.get("cuda"):
        print(f"  가속   : {M['ok']} GPU 사용 - {st['gpu']}")
    elif gpu:
        print(f"  가속   : {M['no']} 그래픽카드({gpu})가 있는데 GPU 빌드가 아닙니다")
        print("           -> python evidence/setup_check.py --repair 로 고칠 수 있습니다")
    elif st["installed"]:
        print("  가속   : CPU 전용 (녹음 전사가 느립니다)")
    else:
        print(f"  가속   : {M['no']} torch 미설치 - 녹음 전사 불가")

    fam = torch_family_status()
    if fam["found"] and (fam["missing"] or len(fam["tags"]) > 1):
        if fam["missing"]:
            print(f"  부품   : {M['no']} 빠짐 - {', '.join(fam['missing'])}")
        if len(fam["tags"]) > 1:
            print(f"           {M['no']} 버전이 섞임 - {', '.join(fam['tags'])}")
        print("           -> python evidence/setup_check.py --repair 로 고칠 수 있습니다")

    print(M["line"] * 68)
    missing, broken = [], []
    for label, module, pkg, purpose in PACKAGES:
        ok, why = _installed(module)
        if ok:
            print(f"  {M['ok']} {label:11s} 설치됨")
            continue
        print(f"  {M['no']} {label:11s} -> {purpose} 불가")
        print(f"       {why}")
        # 깔려는 있는데 못 불러오는 것과, 아예 없는 것은 조치가 다르다.
        (broken if not why.startswith("미설치") else missing).append(
            (label, pkg, purpose))

    ff = shutil.which("ffmpeg")
    try:
        import imageio_ffmpeg
        ff = imageio_ffmpeg.get_ffmpeg_exe()
    except BaseException:
        pass
    print(f"  {M['ok'] if ff else M['no']} {'오디오 처리':11s} {'준비됨' if ff else '미설치':16s}")

    print(M["line"] * 68)
    if missing:
        print(f"  빠진 것 {len(missing)}개 - 아래 명령으로 설치하세요:")
        print("      python evidence/setup_check.py --install")
    if broken:
        # 깔려는 있는데 못 불러오는 것. 다시 까는 것으로는 안 고쳐진다.
        # 대개 다른 패키지와 버전이 어긋난 것이라 --repair 가 맞다.
        print(f"  깔려 있는데 못 쓰는 것 {len(broken)}개 "
              f"({', '.join(b[0] for b in broken)})")
        print("      python evidence/setup_check.py --repair")
    if not missing and not broken:
        print(f"  {M['ok']} 필요한 것이 모두 설치되어 있습니다")
    print(M["dline"] * 68 + "\n")
    return missing + broken


def install_all() -> None:
    print()
    print(M["dline"] * 68)
    print("  증거파인더 설치")
    print(M["dline"] * 68)

    print("\n  [1/4] torch (음성 인식·의미 검색의 토대)")
    install_torch()

    print("\n  [2/4] 나머지 라이브러리")
    # 요구사항 파일을 먼저 시도한다. 실패하면 하나씩 깐다.
    #
    # 하나씩 까는 것이 중요하다. 한 번에 여러 개를 요청하면 그중 하나만
    # 없어도 pip 이 전체를 취소한다 — 실제로 torchcodec(윈도우 배포판 없음)
    # 하나 때문에 torchvision 까지 함께 취소되는 일이 있었다.
    # 하나가 안 되면 그것만 못 쓰고 나머지는 살아야 한다.
    rc = _pip("-r", str(REQ)) if REQ.exists() else 1
    if rc != 0:
        if REQ.exists():
            print("    요구사항 파일로 설치하지 못했습니다. 하나씩 설치합니다.")
        failed = []
        for label, module, pkg, purpose in PACKAGES:
            ok, _ = _installed(module)
            if ok:
                continue
            if _pip(pkg, quiet=True) != 0:
                failed.append((pkg, purpose))
                print(f"    {M['no']} {pkg} 설치 실패 - {purpose} 기능을 못 씁니다")
        if not failed:
            print("    모두 설치했습니다.")

    # ── 여기가 중요하다 ──────────────────────────────
    # 위에서 깐 패키지들(pyannote 등)이 자기 버전 torch 를 끌어오면서
    # 방금 깐 CUDA 빌드를 CPU 빌드로 덮어쓴다. 그러면 그래픽카드가 있는데도
    # 전사가 10배 느려지고, 사용자는 원인을 모른다.
    # 그래서 마지막에 다시 확인하고 필요하면 되돌린다.
    print("\n  [3/4] GPU 가속·부품 정합성 확인")
    fix_pyannote_version()
    gpu = detect_nvidia()
    st = torch_status()
    fam = torch_family_status()

    need_repair = (gpu and not st.get("cuda")) or fam["core_missing"] or fam["mismatched"]
    if need_repair:
        if fam["core_missing"]:
            print(f"    빠진 부품: {', '.join(fam['core_missing'])}")
            print("    다른 패키지가 torch 계열을 흐트러뜨렸습니다. 맞춰서 다시 깝니다.")
        elif gpu and not st.get("cuda"):
            print("    다른 패키지가 torch 를 CPU 빌드로 덮어썼습니다. 되돌립니다.")
        else:
            print(f"    버전이 섞였습니다: {', '.join(fam['tags']) or '표시 없음'}")
        install_torch(force=True)
        st = torch_status()
        fam = torch_family_status()

    if st.get("cuda"):
        print(f"    {M['ok']} GPU 가속 사용 - {st['gpu']}")
    elif gpu:
        print(f"    {M['no']} GPU 가속을 켜지 못했습니다. CPU 로 동작합니다(느립니다).")
    else:
        print("    그래픽카드가 없어 CPU 로 동작합니다.")

    if fam["missing"]:
        print(f"    {M['no']} 아직 없는 부품: {', '.join(fam['missing'])}")

    print("\n  [4/4] 설정 파일")
    ensure_env()

    print("\n" + M["line"] * 68)
    print("  기능이 실제로 되는지 확인합니다")
    print("  (설치되어 있어도 부품 버전이 어긋나면 쓸 때 터집니다)")
    print()
    broken = []
    for label, ok, detail in check_runtime():
        print(f"    {M['ok'] if ok else M['no']} {label:16s} {detail}")
        if not ok:
            broken.append(label)
    if broken:
        print()
        print(f"    {M['no']} 못 쓰는 기능: {', '.join(broken)}")
        print("       고치려면: python evidence/setup_check.py --repair")

    print("\n" + M["line"] * 68)
    missing = report()
    if not missing:
        print("  다음 단계")
        print("    1) AI 모델 미리 받기 (권장):")
        print("         python evidence/setup_check.py --models")
        print("    2) 실행:")
        print("         python -m streamlit run evidence/app.py")
        print()


def repair() -> None:
    """
    설치가 꼬였을 때 되돌린다.

    가장 흔한 경우: 다른 패키지가 torch 를 CPU 빌드로 덮어써서
    그래픽카드가 있는데도 느리거나, torchcodec DLL 오류 창이 뜬다.
    """
    print()
    print(M["dline"] * 68)
    print("  설치 고치기")
    print(M["dline"] * 68)

    fam = torch_family_status()
    if fam["missing"]:
        print(f"\n  빠진 부품: {', '.join(fam['missing'])}")
    if len(fam["tags"]) > 1:
        print(f"  섞인 버전: {', '.join(fam['tags'])}")

    print("\n  [1/2] torch 계열을 그래픽카드에 맞게 통째로 다시 설치")
    install_torch(force=True)
    fix_pyannote_version()

    print("\n  [2/2] 기능이 실제로 되는지 확인")
    broken = []
    for label, ok, detail in check_runtime():
        print(f"    {M['ok'] if ok else M['no']} {label:16s} {detail}")
        if not ok:
            broken.append(label)

    print("\n" + M["line"] * 68)
    st = torch_status()
    if st.get("cuda"):
        print(f"  {M['ok']} GPU 가속 사용 - {st['gpu']}")
    elif detect_nvidia():
        print(f"  {M['no']} 아직 GPU 가속이 켜지지 않았습니다.")
        print("     화면에 뜬 메시지를 확인해 주세요.")
    else:
        print("  그래픽카드가 없어 CPU 로 동작합니다.")

    if broken:
        print(f"  {M['no']} 아직 못 쓰는 기능: {', '.join(broken)}")
    else:
        print(f"  {M['ok']} 모든 기능이 준비되었습니다.")
    print(M["dline"] * 68 + "\n")


TOKEN_GUIDE = {
    "HF_TOKEN": {
        "label": "화자 분리 (누가 말했는지 구분)",
        "steps": [
            "1. https://huggingface.co 가입 후 로그인",
            "2. 우측 상단 프로필 -> Settings -> Access Tokens -> New token",
            "   (Type 은 Read 로)",
            "3. https://huggingface.co/pyannote/speaker-diarization-3.1 접속",
            "   -> 이용 약관에 동의  <- 이걸 빠뜨리면 토큰이 있어도 안 됩니다",
        ],
        "check": lambda v: v.startswith("hf_") and len(v) > 20,
        "hint": "보통 hf_ 로 시작합니다",
    },
    "LAW_OC": {
        "label": "법률 코멘트 (관련 조문·판례)",
        "steps": [
            "1. https://open.law.go.kr 접속 후 로그인",
            "2. OPEN API -> 활용신청 (무료, 즉시 발급)",
        ],
        "check": lambda v: len(v) >= 2,
        "hint": "보통 아이디 형태의 짧은 문자열입니다",
    },
}


def _write_env_value(key: str, value: str) -> None:
    """
    .env 의 해당 줄만 갈아끼운다.
    다른 설정은 건드리지 않는다 — 사용자가 손으로 넣어둔 값이 있을 수 있다.
    """
    env = ensure_env(quiet=True)
    lines = env.read_text(encoding="utf-8", errors="ignore").splitlines()
    done = False
    for i, line in enumerate(lines):
        if line.strip().startswith(f"{key}="):
            lines[i] = f"{key}={value}"
            done = True
            break
    if not done:
        lines.append(f"{key}={value}")
    env.write_text("\n".join(lines) + "\n", encoding="utf-8")


TOKEN_KEYS = ("HF_TOKEN", "LAW_OC")


def _read_env_values(path: Path) -> dict:
    """.env 파일에서 인증키만 뽑아 읽는다. 값이 빈 줄은 없는 것으로 본다."""
    out = {}
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return out
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key in TOKEN_KEYS and value:
            out[key] = value
    return out


def find_previous_env(limit: int = 400) -> list[tuple[Path, dict]]:
    """
    예전 폴더에 두고 온 인증키 파일을 찾는다.

    왜 필요한가
      윈도우는 같은 이름의 ZIP 을 받으면 `... (2)`, `... (3)` 처럼
      새 폴더에 푼다. 예전 버전은 인증키를 프로그램 폴더 안에 두었으므로,
      새로 받은 폴더에서는 인증키가 없어진 것처럼 보인다.
      실제로는 옆 폴더에 멀쩡히 있다. 새로 발급받게 할 이유가 없다.

    지금 폴더 · 위 폴더 · 그 위 폴더까지만 훑는다.
    더 넓게 뒤지면 남의 프로젝트 .env 까지 들여다보게 된다.
    """
    from evidence import config

    here = config.PROJECT_DIR
    current = config.ENV_FILE.resolve() if config.ENV_FILE.exists() else None

    seen, found, scanned = set(), [], 0
    for root in (here, here.parent, here.parent.parent):
        try:
            if not root.is_dir():
                continue
            candidates = [root / ".env", *root.glob("*/.env"), *root.glob("*/*/.env")]
        except OSError:
            continue
        for cand in candidates:
            scanned += 1
            if scanned > limit:
                break
            try:
                resolved = cand.resolve()
            except OSError:
                continue
            if resolved in seen or resolved == current or not cand.is_file():
                continue
            seen.add(resolved)
            values = _read_env_values(cand)
            if values:
                found.append((cand, values))
    return found


def import_previous_env(ask: bool = True) -> dict:
    """
    예전 폴더의 인증키를 지금 자리로 가져온다.

    이미 값이 들어 있는 항목은 건드리지 않는다 —
    사용자가 방금 넣은 새 키를 옛 키로 덮어쓰면 안 된다.
    """
    import os

    missing = [k for k in TOKEN_KEYS if not os.getenv(k)]
    if not missing:
        return {}

    found = find_previous_env()
    usable = [(p, {k: v for k, v in vals.items() if k in missing})
              for p, vals in found]
    usable = [(p, vals) for p, vals in usable if vals]
    if not usable:
        return {}

    path, values = usable[0]
    print()
    print(f"  {M['ok']} 예전 폴더에서 인증키를 찾았습니다.")
    print(f"     {path}")
    for key in values:
        print(f"     - {key}")
    print("     새로 발급받지 않아도 됩니다.")

    if ask:
        print()
        try:
            answer = input("  가져올까요? (Y/n): ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return {}
        if answer in ("n", "no", "아니오", "아니"):
            print("  가져오지 않았습니다.")
            return {}

    for key, value in values.items():
        _apply_token(key, value)
    print(f"  {M['ok']} {', '.join(values)} 을(를) 가져왔습니다.")
    return values


def _apply_token(key: str, value: str) -> None:
    """
    인증키를 저장하고 **지금 실행 중인 과정에도** 반영한다.

    config 는 불러올 때 한 번만 값을 읽는다. 파일만 고치면
    같은 실행 안에서 이어지는 단계(--go 의 모델 받기)는 여전히
    "인증키가 없다"고 판단한다. 실제로 그렇게 어긋난 적이 있다.
    """
    import os

    _write_env_value(key, value)
    os.environ[key] = value
    try:
        from evidence import config
        if hasattr(config, key):
            setattr(config, key, value)
    except BaseException:
        pass


def setup_tokens() -> None:
    """인증키를 물어보고 .env 에 대신 써준다."""
    print()
    print(M["dline"] * 68)
    print("  인증키 입력")
    print(M["dline"] * 68)

    # 새로 발급받게 하기 전에, 예전 폴더에 두고 온 것이 없는지 먼저 본다
    import_previous_env(ask=True)

    print()
    print("  둘 다 무료이고, 없어도 나머지 기능은 모두 동작합니다.")
    print("  건너뛰려면 그냥 Enter 를 누르세요.")

    import os

    for key, info in TOKEN_GUIDE.items():
        current = os.getenv(key, "")
        print()
        print(M["line"] * 68)
        print(f"  {key} - {info['label']}")
        if current:
            masked = current[:6] + "..." + current[-4:] if len(current) > 12 else "설정됨"
            print(f"  이미 설정되어 있습니다: {masked}")
            print("  바꾸려면 새 값을 넣고, 그대로 두려면 Enter")
        else:
            for line in info["steps"]:
                print(f"    {line}")
        print()
        try:
            value = input(f"  {key} = ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  입력을 건너뜁니다.")
            break

        if not value:
            print("  건너뜁니다.")
            continue
        if not info["check"](value):
            print(f"  {M['no']} 형식이 이상합니다 ({info['hint']}). 그래도 저장할까요?")
            try:
                if input("     저장 (y/N): ").strip().lower() != "y":
                    print("  저장하지 않았습니다.")
                    continue
            except (EOFError, KeyboardInterrupt):
                continue

        _apply_token(key, value)
        print(f"  {M['ok']} 저장했습니다.")

    print()
    print(M["line"] * 68)
    print(f"  저장 위치: {ensure_env(quiet=True)}")
    print("  프로그램 새 버전을 받아도 이 파일은 그대로 남습니다.")
    print()
    print("  다음 단계 - 이 한 줄이면 남은 준비가 끝납니다")
    print("      python evidence/setup_check.py --go")
    print(M["dline"] * 68 + "\n")


def main():
    ap = argparse.ArgumentParser(description="증거파인더 설치 도우미")
    ap.add_argument("--install", action="store_true", help="부족한 것 설치")
    ap.add_argument("--models", action="store_true", help="AI 모델 미리 받기")
    ap.add_argument("--env", action="store_true", help=".env 파일만 만들기")
    ap.add_argument("--ask-models", action="store_true",
                    help="모델을 미리 받을지 물어본 뒤 받기")
    ap.add_argument("--repair", action="store_true",
                    help="설치가 꼬였을 때 되돌리기 (GPU 가속·DLL 오류)")
    ap.add_argument("--token", action="store_true",
                    help="인증키를 물어보고 .env 에 저장")
    ap.add_argument("--selftest", action="store_true",
                    help="가짜 사건으로 전 과정을 한 번 돌려본다")
    ap.add_argument("--go", action="store_true",
                    help="남은 준비를 한 번에 (모델 받기 + 자체 점검)")
    ap.add_argument("--shortcut", action="store_true",
                    help="바탕화면 바로가기 만들기 (윈도우)")
    args = ap.parse_args()

    if args.shortcut:
        from evidence.make_shortcuts import main as make_shortcuts
        raise SystemExit(make_shortcuts())
    elif args.go:
        raise SystemExit(finish_setup())
    elif args.selftest:
        from evidence.selftest import run as run_selftest
        raise SystemExit(0 if run_selftest(M) else 1)
    elif args.token:
        setup_tokens()
    elif args.repair:
        repair()
    elif args.ask_models:
        _ask_models()
    elif args.install:
        install_all()
    elif args.models:
        ensure_env()
        _report_models(download_models())
        print()
    elif args.env:
        ensure_env()
    else:
        report()


if __name__ == "__main__":
    main()
