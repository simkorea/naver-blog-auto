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
    ("화자 분리",    "pyannote.audio",        "pyannote.audio>=3.3.0",        "누가 말했는지 구분"),
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

CUDA_INDEX = "https://download.pytorch.org/whl/cu124"


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


def install_torch() -> bool:
    """
    GPU가 있으면 CUDA 빌드를, 없으면 CPU 빌드를 깐다.

    이게 사람들이 가장 많이 틀리는 부분이다. 그냥 `pip install torch` 하면
    GPU가 있어도 CPU 빌드가 깔려서, 전사가 10배 느린데 원인을 모른다.
    """
    gpu = detect_nvidia()
    st = torch_status()

    if st["installed"] and st.get("cuda"):
        print(f"    이미 GPU 가속으로 설치되어 있습니다 — {st['gpu']}")
        return True

    if gpu:
        if st["installed"] and st.get("is_cpu_build"):
            print(f"    그래픽카드({gpu})가 있는데 CPU 전용 torch가 깔려 있습니다.")
            print("    GPU 빌드로 다시 설치합니다 (전사 속도가 5~10배 빨라집니다).")
            _pip("uninstall", "-y", "torch")
        else:
            print(f"    그래픽카드 감지: {gpu}")
        print("    CUDA 빌드를 설치합니다 (2GB 내외, 몇 분 걸립니다)")
        rc = _pip("torch", "--index-url", CUDA_INDEX)
        if rc != 0:
            print("    CUDA 빌드 실패 → CPU 빌드로 시도합니다")
            rc = _pip("torch")
        return rc == 0

    if st["installed"]:
        print("    이미 설치되어 있습니다 (CPU 전용)")
        return True
    print("    그래픽카드가 없어 CPU 빌드를 설치합니다")
    print("    (녹음 전사가 느립니다. 1시간 녹음에 20~40분)")
    return _pip("torch") == 0


# ─────────────────────────────────────────────────────────
# 모델 미리 받기
# ─────────────────────────────────────────────────────────
def download_models(whisper: bool = True, embed: bool = True,
                    ocr: bool = True, diarize: bool = True) -> None:
    """
    첫 실행 때 받을 것을 미리 받아둔다.

    급할 때 다운로드를 기다리는 것만큼 답답한 일이 없다.
    한 번 받아두면 다음부터는 인터넷 없이도 동작한다.
    """
    sys.path.insert(0, str(ROOT.parent))
    from evidence import config

    if whisper:
        print("\n  [1/4] 음성 인식 모델")
        try:
            from faster_whisper import WhisperModel
            hw = config.hardware()
            for name in (config.WHISPER_PRIMARY, config.WHISPER_SECONDARY):
                print(f"        {name} 받는 중... (약 1.5GB, 몇 분 걸립니다)")
                WhisperModel(name, device="cpu", compute_type="int8")
                print(f"        {name} 완료")
        except BaseException as e:
            print(f"        건너뜀 — {type(e).__name__}: {e}")

    if embed:
        print("\n  [2/4] 의미 검색 모델")
        try:
            from sentence_transformers import SentenceTransformer
            print(f"        {config.EMBED_MODEL} 받는 중... (약 2.3GB)")
            SentenceTransformer(config.EMBED_MODEL, device="cpu")
            print("        완료")
        except BaseException as e:
            print(f"        건너뜀 — {type(e).__name__}: {e}")

    if ocr:
        print("\n  [3/4] 이미지 글자 인식 모델")
        try:
            import easyocr
            print("        한국어 OCR 모델 받는 중... (약 100MB)")
            easyocr.Reader(["ko", "en"], gpu=False, verbose=False)
            print("        완료")
        except BaseException as e:
            print(f"        건너뜀 — {type(e).__name__}: {e}")

    if diarize:
        print("\n  [4/4] 화자 분리 모델")
        if not config.HF_TOKEN:
            print("        건너뜀 — .env에 HF_TOKEN이 없습니다")
        else:
            try:
                from pyannote.audio import Pipeline
                print("        받는 중... (약 200MB)")
                Pipeline.from_pretrained(config.DIARIZE_MODEL,
                                         use_auth_token=config.HF_TOKEN)
                print("        완료")
            except BaseException as e:
                print(f"        실패 — {e}")
                print("        huggingface.co/pyannote/speaker-diarization-3.1 에서")
                print("        이용 약관에 동의하셨는지 확인하세요.")


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


def ensure_env() -> Path:
    env = ROOT.parent / ".env"
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
            print(f"    기존 .env에 {', '.join(added)} 항목을 추가했습니다")
        else:
            print("    .env 파일이 이미 있습니다")
    else:
        env.write_text(ENV_TEMPLATE, encoding="utf-8")
        print(f"    .env 파일을 만들었습니다: {env}")
        print("    메모장으로 열어 인증키를 넣으세요 (없어도 대부분 기능은 동작합니다)")
    return env


# ─────────────────────────────────────────────────────────
# 점검 · 설치
# ─────────────────────────────────────────────────────────
def report() -> list:
    print("\n" + M["dline"] * 68)
    print("  증거파인더 설치 점검")
    print(M["dline"] * 68)
    print(f"  파이썬 : {sys.version.split()[0]}  ({platform.system()} {platform.machine()})")

    gpu = detect_nvidia()
    st = torch_status()
    if st.get("cuda"):
        print(f"  가속   : {M['ok']} GPU 사용 - {st['gpu']}")
    elif gpu:
        print(f"  가속   : {M['no']} 그래픽카드({gpu})가 있는데 GPU 빌드가 아닙니다")
        print("           → python evidence/setup_check.py --install 로 고칠 수 있습니다")
    elif st["installed"]:
        print("  가속   : CPU 전용 (녹음 전사가 느립니다)")
    else:
        print(f"  가속   : {M['no']} torch 미설치 - 녹음 전사 불가")

    print(M["line"] * 68)
    missing = []
    for label, module, pkg, purpose in PACKAGES:
        ok, why = _installed(module)
        mark = M["ok"] if ok else M["no"]
        note = "" if ok else f"-> {purpose} 불가"
        print(f"  {mark} {label:11s} {why if not ok else '설치됨':16s} {note}")
        if not ok:
            missing.append((label, pkg, purpose))

    ff = shutil.which("ffmpeg")
    try:
        import imageio_ffmpeg
        ff = imageio_ffmpeg.get_ffmpeg_exe()
    except BaseException:
        pass
    print(f"  {M['ok'] if ff else M['no']} {'오디오 처리':11s} {'준비됨' if ff else '미설치':16s}")

    print(M["line"] * 68)
    if missing:
        print(f"  빠진 것 {len(missing)}개 — 아래 명령으로 설치하세요:")
        print("      python evidence/setup_check.py --install")
    else:
        print(f"  {M['ok']} 필요한 것이 모두 설치되어 있습니다")
    print(M["dline"] * 68 + "\n")
    return missing


def install_all() -> None:
    print("\n" + M["dline"] * 68)
    print("  증거파인더 설치")
    print(M["dline"] * 68)

    print("\n  [1/3] torch (음성 인식·의미 검색의 토대)")
    install_torch()

    print("\n  [2/3] 나머지 라이브러리")
    if REQ.exists():
        _pip("-r", str(REQ))
    else:
        for _, _, pkg, _ in PACKAGES:
            _pip(pkg, quiet=True)

    print("\n  [3/3] 설정 파일")
    ensure_env()

    print("\n" + M["line"] * 68)
    missing = report()
    if not missing:
        print("  다음 단계")
        print("    1) AI 모델 미리 받기 (권장):")
        print("         python evidence/setup_check.py --models")
        print("    2) 실행:")
        print("         streamlit run evidence/app.py")
        print()


def _ask_models() -> None:
    """
    모델을 미리 받을지 물어본다.

    한글 안내를 배치 파일이 아니라 여기서 출력하는 이유:
    배치 파일에 한글을 넣으면 chcp 전환 시점 때문에 글자가 깨지거나
    cmd가 파일 안에서 위치를 잃는 문제가 있다. 파이썬이 출력하면 안전하다.
    """
    print()
    print(M["dline"] * 68)
    print("  AI 모델을 미리 받아둘까요?")
    print(M["dline"] * 68)
    print()
    print("  약 4GB를 내려받습니다. 시간이 걸리지만 한 번 받아두면")
    print("  이후에는 인터넷 없이도 동작하고, 급할 때 기다리지 않아도 됩니다.")
    print()
    try:
        ans = input("  지금 받을까요? (Y/N): ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        ans = "n"

    if ans in ("y", "ㅛ", "예", "네"):
        ensure_env()
        download_models()
        print()
        print("  모델 준비가 끝났습니다. 이제 인터넷 없이도 동작합니다.")
    else:
        print()
        print("  건너뛰었습니다. 나중에 받으려면:")
        print("      python evidence/setup_check.py --models")

    print()
    print(M["dline"] * 68)
    print("  설치가 끝났습니다.")
    print()
    print('  실행하려면 evidence 폴더의 "실행.bat" 을 더블클릭하세요.')
    print(M["dline"] * 68)
    print()


def main():
    ap = argparse.ArgumentParser(description="증거파인더 설치 도우미")
    ap.add_argument("--install", action="store_true", help="부족한 것 설치")
    ap.add_argument("--models", action="store_true", help="AI 모델 미리 받기")
    ap.add_argument("--env", action="store_true", help=".env 파일만 만들기")
    ap.add_argument("--ask-models", action="store_true",
                    help="모델을 미리 받을지 물어본 뒤 받기")
    args = ap.parse_args()

    if args.ask_models:
        _ask_models()
    elif args.install:
        install_all()
    elif args.models:
        ensure_env()
        download_models()
        print("\n  모델 준비가 끝났습니다. 이제 인터넷 없이도 동작합니다.\n")
    elif args.env:
        ensure_env()
    else:
        report()


if __name__ == "__main__":
    main()
