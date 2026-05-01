import io
import os
import re
import sys
import subprocess
import datetime
import zipfile
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

# ── Supabase 헬퍼 ──
def _supabase_push(
    title: str, content: str, tags: str, local_folder: str,
    scheduled_at: str = "",
) -> tuple[bool, str]:
    url = get_secret("SUPABASE_URL")
    key = get_secret("SUPABASE_KEY")
    if not url or not key:
        return False, "SUPABASE_URL 또는 SUPABASE_KEY 가 secrets에 없습니다."
    try:
        from supabase_db import push_pending
        return push_pending(url, key, title, content, tags, local_folder, scheduled_at)
    except Exception as e:
        return False, str(e)

def _supabase_all_rows() -> list[dict]:
    url = get_secret("SUPABASE_URL")
    key = get_secret("SUPABASE_KEY")
    if not url or not key:
        return []
    try:
        from supabase_db import get_all_rows
        return get_all_rows(url, key)
    except Exception:
        return []

def _extract_tags(content: str) -> str:
    return " ".join(re.findall(r"#\S+", content))

load_dotenv()

# ── 클라우드 / 로컬 감지 ──
import importlib.util

IS_CLOUD = not Path(".env").exists()

# 클라우드 환경이면 playwright chromium 브라우저 자동 설치
if IS_CLOUD and importlib.util.find_spec("playwright") is not None:
    import subprocess as _sp
    _cache = Path.home() / ".cache" / "ms-playwright"
    if not _cache.exists():
        _sp.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            capture_output=True, timeout=300,
        )

PLAYWRIGHT_OK = importlib.util.find_spec("playwright") is not None


def get_secret(key: str) -> str:
    """로컬 .env → Streamlit Secrets 순서로 키를 읽습니다."""
    val = os.getenv(key, "")
    if val:
        return val
    try:
        return st.secrets.get(key, "")
    except Exception:
        return ""


def make_zip(post_dir: Path) -> bytes:
    """포스트 폴더 전체를 ZIP으로 묶어 bytes로 반환합니다."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(post_dir.iterdir()):
            if f.is_file():
                zf.write(f, f.name)
    return buf.getvalue()


# ── 경로 설정 ──
BASE_DIR  = Path(__file__).parent
POSTS_DIR = BASE_DIR / "posts"
sys.path.insert(0, str(BASE_DIR))

# ── 페이지 설정 ──
st.set_page_config(
    page_title="네이버 부동산 블로그 자동화",
    page_icon="🏠",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ══════════════════════════════════════════
# GLOBAL CSS — B2B SaaS 스타일 (Crypee급)
# ══════════════════════════════════════════
st.markdown("""
<style>
/* ─── 0. Pretendard 웹폰트 ─── */
@import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.min.css');

/*
 * ── 폰트 전략 ──────────────────────────────────────────
 *  1. html/body 에 Pretendard 기본값 (느슨하게: !important 없음)
 *     → 대부분의 텍스트는 여기서 상속
 *  2. 확실히 텍스트만 담는 요소에만 !important 사용
 *     → span / label / a / button 전체 타겟 절대 금지
 *        (Material Symbols ligature 스팬이 포함되기 때문)
 *  3. 아이콘 요소에는 실제 폰트명을 명시적으로 복원
 *     → inherit 금지 (부모가 이미 Pretendard면 무의미)
 * ────────────────────────────────────────────────────── */
html, body {
  font-family: 'Pretendard', -apple-system, BlinkMacSystemFont,
               'Apple SD Gothic Neo', 'Noto Sans KR', sans-serif;
}

/* 순수 텍스트 컨테이너에만 !important */
input, textarea, select,
p, h1, h2, h3, h4, h5, h6,
li, td, th, caption,
div[data-testid="stMarkdownContainer"],
div[data-testid="stText"],
button[data-baseweb="tab"] {
  font-family: 'Pretendard', -apple-system, BlinkMacSystemFont,
               'Apple SD Gothic Neo', 'Noto Sans KR', sans-serif !important;
}

/* ── 아이콘 폰트 명시적 복원 ───────────────────────────
 * Streamlit 1.28+ : Material Symbols Rounded
 * 구버전           : Material Icons
 * inherit 사용 금지 → 부모가 Pretendard면 그대로 상속됨
 * ─────────────────────────────────────────────────── */
i,
[aria-hidden="true"],
span[class*="material"],
span[class*="symbol"],
section[data-testid="stSidebar"] button span,
section[data-testid="stSidebar"] summary > span,
details > summary > span:first-child,
details > summary > span:last-child,
button[data-testid="baseButton-headerNoPadding"] span,
button[data-testid="collapsedControl"] span,
button[data-testid="expandedControl"] span {
  font-family: 'Material Symbols Rounded', 'Material Icons',
               'Material Icons Outlined', 'Material Symbols Outlined',
               serif !important;
}

/* ─── 1. Streamlit 브랜딩 완전 제거 ─── */
#MainMenu                                    { display: none !important; }
header[data-testid="stHeader"]               { display: none !important; }
footer                                       { display: none !important; }
div[data-testid="stToolbar"]                 { display: none !important; }
div[data-testid="stBottom"]                  { display: none !important; }
button[data-testid="baseButton-header"]      { display: none !important; }
.stDeployButton                              { display: none !important; }
div[data-testid="stDecoration"]              { display: none !important; }

/* ─── 2. 앱 배경 ─── */
div[data-testid="stAppViewContainer"] {
  background: #f0f2f8 !important;
}
div[data-testid="block-container"] {
  padding: 2rem 2.5rem 3rem !important;
  max-width: 1440px !important;
}

/* ─── 3. 사이드바 — 다크 네이비 (최소 침범) ─── */
section[data-testid="stSidebar"] {
  background: linear-gradient(180deg, #0f172a 0%, #1e293b 100%) !important;
  border-right: 1px solid rgba(255,255,255,0.06) !important;
}
section[data-testid="stSidebar"] > div:first-child {
  padding-top: 1.5rem !important;
}

/*
 * 텍스트 색상은 명시적 텍스트 요소만 타겟.
 * div / span 전체 덮어쓰기 금지 → 아이콘 색 충돌 방지
 */
section[data-testid="stSidebar"] p { color: #94a3b8 !important; }
section[data-testid="stSidebar"] h1,
section[data-testid="stSidebar"] h2,
section[data-testid="stSidebar"] h3 { color: #f1f5f9 !important; }
section[data-testid="stSidebar"] hr { border-color: rgba(255,255,255,0.1) !important; }

/* 사이드바 라디오 — label 텍스트만 */
section[data-testid="stSidebar"] div[data-testid="stRadio"] label {
  border-radius: 8px !important;
  padding: 0.45rem 0.75rem !important;
  transition: background 0.15s !important;
  color: #94a3b8 !important;
}
section[data-testid="stSidebar"] div[data-testid="stRadio"] label:hover {
  background: rgba(255,255,255,0.08) !important;
  color: #e2e8f0 !important;
}

/* 사이드바 Expander — Streamlit 기본 스타일 유지, 배경만 투명 */
section[data-testid="stSidebar"] div[data-testid="stExpander"] {
  background: transparent !important;
  border: 1px solid rgba(255,255,255,0.1) !important;
  box-shadow: none !important;
  border-radius: 8px !important;
}
section[data-testid="stSidebar"] div[data-testid="stExpander"] summary {
  color: #cbd5e1 !important;
  padding: 0.6rem 0.9rem !important;
  background: transparent !important;
}
section[data-testid="stSidebar"] div[data-testid="stExpander"] summary:hover {
  background: rgba(255,255,255,0.06) !important;
}
/* 사이드바 expander 내부 텍스트 */
section[data-testid="stSidebar"] div[data-testid="stExpander"] p,
section[data-testid="stSidebar"] div[data-testid="stExpander"] label {
  color: #94a3b8 !important;
}

/* ─── 4. 탭 ─── */
div[data-testid="stTabs"] > div:first-child {
  border-bottom: 2px solid #e2e8f0 !important;
  gap: 2px !important;
  padding-bottom: 0 !important;
}
button[data-baseweb="tab"] {
  border-radius: 8px 8px 0 0 !important;
  font-weight: 600 !important;
  font-size: 0.875rem !important;
  color: #64748b !important;
  padding: 0.6rem 1.1rem !important;
  transition: color 0.2s, background 0.2s !important;
  border-bottom: 2px solid transparent !important;
  margin-bottom: -2px !important;
}
button[data-baseweb="tab"]:hover {
  background: #f8fafc !important;
  color: #7c3aed !important;
}
button[data-baseweb="tab"][aria-selected="true"] {
  color: #7c3aed !important;
  border-bottom: 2px solid #7c3aed !important;
  font-weight: 700 !important;
  background: transparent !important;
}
div[data-testid="stTabPanel"] {
  padding-top: 1.5rem !important;
}

/* ─── 5. 입력 위젯 — 카드 스타일 ─── */
div[data-testid="stTextInput"] > label,
div[data-testid="stTextArea"] > label,
div[data-testid="stSelectbox"] > label,
div[data-testid="stNumberInput"] > label,
div[data-testid="stMultiSelect"] > label,
div[data-testid="stSlider"] > label {
  font-weight: 600 !important;
  font-size: 0.825rem !important;
  color: #374151 !important;
  letter-spacing: 0.01em !important;
  margin-bottom: 4px !important;
}
div[data-testid="stTextInput"] > div > div,
div[data-testid="stTextArea"] > div > div,
div[data-testid="stNumberInput"] > div > div {
  background: #ffffff !important;
  border-radius: 10px !important;
  border: 1.5px solid #e2e8f0 !important;
  box-shadow: 0 1px 4px rgba(0,0,0,0.05) !important;
  transition: border-color 0.2s, box-shadow 0.2s !important;
}
div[data-testid="stTextInput"] > div > div:focus-within,
div[data-testid="stTextArea"] > div > div:focus-within,
div[data-testid="stNumberInput"] > div > div:focus-within {
  border-color: #7c3aed !important;
  box-shadow: 0 0 0 3px rgba(124,58,237,0.12) !important;
}
div[data-baseweb="select"] > div:first-child {
  background: #ffffff !important;
  border-radius: 10px !important;
  border: 1.5px solid #e2e8f0 !important;
  box-shadow: 0 1px 4px rgba(0,0,0,0.05) !important;
}
input[class], textarea[class] {
  color: #1e293b !important;
  font-size: 0.9rem !important;
}

/* ─── 6. 버튼 — 킬러 스타일 ─── */
/* Primary 버튼 (그라데이션) */
div.stButton > button[kind="primary"],
div.stFormSubmitButton > button[kind="primary"],
div.stButton > button[data-testid="baseButton-primary"] {
  background: linear-gradient(135deg, #7c3aed 0%, #4f46e5 100%) !important;
  color: #ffffff !important;
  border: none !important;
  border-radius: 10px !important;
  font-weight: 700 !important;
  font-size: 0.9rem !important;
  padding: 0.65rem 1.5rem !important;
  box-shadow: 0 4px 15px rgba(124,58,237,0.4) !important;
  transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1) !important;
  letter-spacing: 0.01em !important;
}
div.stButton > button[kind="primary"]:hover,
div.stFormSubmitButton > button[kind="primary"]:hover,
div.stButton > button[data-testid="baseButton-primary"]:hover {
  background: linear-gradient(135deg, #6d28d9 0%, #4338ca 100%) !important;
  box-shadow: 0 6px 22px rgba(124,58,237,0.5) !important;
  transform: translateY(-2px) scale(1.01) !important;
}
div.stButton > button[kind="primary"]:active,
div.stFormSubmitButton > button[kind="primary"]:active {
  transform: translateY(0) scale(0.99) !important;
  box-shadow: 0 2px 8px rgba(124,58,237,0.3) !important;
}

/* Secondary 버튼 */
div.stButton > button[kind="secondary"],
div.stButton > button[data-testid="baseButton-secondary"],
div.stButton > button:not([kind]) {
  background: #ffffff !important;
  color: #374151 !important;
  border: 1.5px solid #d1d5db !important;
  border-radius: 10px !important;
  font-weight: 600 !important;
  font-size: 0.875rem !important;
  padding: 0.6rem 1.25rem !important;
  box-shadow: 0 1px 4px rgba(0,0,0,0.06) !important;
  transition: all 0.2s ease !important;
}
div.stButton > button[kind="secondary"]:hover,
div.stButton > button:not([kind]):hover {
  border-color: #7c3aed !important;
  color: #7c3aed !important;
  box-shadow: 0 3px 10px rgba(124,58,237,0.15) !important;
  transform: translateY(-1px) !important;
}

/* 다운로드 버튼 — 에메랄드 */
div.stDownloadButton > button {
  background: linear-gradient(135deg, #10b981 0%, #059669 100%) !important;
  color: #ffffff !important;
  border: none !important;
  border-radius: 10px !important;
  font-weight: 700 !important;
  font-size: 0.875rem !important;
  box-shadow: 0 4px 12px rgba(16,185,129,0.35) !important;
  transition: all 0.2s ease !important;
}
div.stDownloadButton > button:hover {
  box-shadow: 0 6px 18px rgba(16,185,129,0.45) !important;
  transform: translateY(-1px) !important;
}

/* ─── 7. Expander — 메인 영역만 카드 (사이드바 제외) ─── */
div[data-testid="stAppViewContainer"]
  div[data-testid="stExpander"]:not(
    section[data-testid="stSidebar"] div[data-testid="stExpander"]
  ) {
  background: #ffffff !important;
  border-radius: 12px !important;
  border: 1px solid #e2e8f0 !important;
  box-shadow: 0 2px 12px rgba(0,0,0,0.06) !important;
  overflow: hidden !important;
  margin-bottom: 0.75rem !important;
}
/* 메인 콘텐츠 블록 안에서만 적용 */
div[data-testid="block-container"] div[data-testid="stExpander"] {
  background: #ffffff !important;
  border-radius: 12px !important;
  border: 1px solid #e2e8f0 !important;
  box-shadow: 0 2px 12px rgba(0,0,0,0.06) !important;
  overflow: hidden !important;
  margin-bottom: 0.75rem !important;
}
div[data-testid="block-container"] div[data-testid="stExpander"] summary {
  padding: 0.9rem 1.25rem !important;
  font-weight: 600 !important;
  font-size: 0.9rem !important;
  color: #1e293b !important;
}
div[data-testid="block-container"] div[data-testid="stExpander"] summary:hover {
  background: #f8fafc !important;
}

/* ─── 8. Metric 카드 ─── */
div[data-testid="metric-container"] {
  background: #ffffff !important;
  border-radius: 14px !important;
  padding: 1.25rem 1.5rem !important;
  border: 1px solid #e2e8f0 !important;
  box-shadow: 0 2px 12px rgba(0,0,0,0.06) !important;
}
div[data-testid="stMetricValue"] > div {
  font-size: 1.8rem !important;
  font-weight: 800 !important;
  color: #0f172a !important;
  letter-spacing: -0.02em !important;
}
div[data-testid="stMetricLabel"] > div {
  font-size: 0.775rem !important;
  font-weight: 600 !important;
  color: #64748b !important;
  text-transform: uppercase !important;
  letter-spacing: 0.06em !important;
}
div[data-testid="stMetricDelta"] > div {
  font-size: 0.82rem !important;
  font-weight: 600 !important;
}

/* ─── 9. Alert / Info 박스 ─── */
div[data-testid="stAlert"] {
  border-radius: 10px !important;
  border-left-width: 4px !important;
  font-size: 0.875rem !important;
}

/* ─── 10. 데이터프레임 ─── */
div[data-testid="stDataFrame"] {
  border-radius: 12px !important;
  overflow: hidden !important;
  box-shadow: 0 2px 12px rgba(0,0,0,0.06) !important;
  border: 1px solid #e2e8f0 !important;
}

/* ─── 11. 체크박스 / 라디오 ─── */
div[data-testid="stCheckbox"] label,
div[data-testid="stRadio"] label {
  font-size: 0.875rem !important;
  font-weight: 500 !important;
  color: #374151 !important;
}

/* ─── 12. Markdown 헤딩 ─── */
div[data-testid="stMarkdownContainer"] h1 {
  font-size: 1.7rem !important;
  font-weight: 800 !important;
  color: #0f172a !important;
  letter-spacing: -0.02em !important;
}
div[data-testid="stMarkdownContainer"] h2 {
  font-size: 1.2rem !important;
  font-weight: 700 !important;
  color: #1e293b !important;
  padding-bottom: 0.4rem !important;
}
div[data-testid="stMarkdownContainer"] h3 {
  font-size: 0.975rem !important;
  font-weight: 700 !important;
  color: #374151 !important;
}
div[data-testid="stMarkdownContainer"] p {
  font-size: 0.9rem !important;
  color: #475569 !important;
  line-height: 1.7 !important;
}

/* ─── 13. 로그인 폼 카드 (스페셜) ─── */
div[data-testid="stForm"] {
  background: #ffffff !important;
  border-radius: 16px !important;
  padding: 2rem !important;
  border: 1px solid #e2e8f0 !important;
  box-shadow: 0 8px 32px rgba(0,0,0,0.1) !important;
}

/* ─── 14. 커스텀 스크롤바 ─── */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: #f1f5f9; }
::-webkit-scrollbar-thumb { background: #cbd5e1; border-radius: 6px; }
::-webkit-scrollbar-thumb:hover { background: #94a3b8; }

/* ─── 15. 이미지 갤러리 카드 ─── */
div[data-testid="stImage"] img {
  border-radius: 10px !important;
  box-shadow: 0 2px 10px rgba(0,0,0,0.1) !important;
}

/* ─── 16. st.code / st.json 박스 ─── */
div[data-testid="stCode"],
div[data-testid="stJson"] {
  border-radius: 10px !important;
  border: 1px solid #e2e8f0 !important;
  overflow: hidden !important;
}

/* ─── 17. 상태 뱃지 (st.badge) ─── */
span[data-testid="stBadge"] {
  border-radius: 20px !important;
  font-weight: 700 !important;
  font-size: 0.75rem !important;
  letter-spacing: 0.03em !important;
}
</style>
""", unsafe_allow_html=True)

# ══════════════════════════════════════════
# 로그인 게이트
# ══════════════════════════════════════════
if "authenticated" not in st.session_state:
    st.session_state["authenticated"] = False

if not st.session_state["authenticated"]:
    st.markdown("""
    <style>
    section[data-testid="stSidebar"] { display: none !important; }
    div[data-testid="stAppViewContainer"] {
      background: linear-gradient(135deg, #0f172a 0%, #1e293b 60%, #312e81 100%) !important;
    }
    div[data-testid="block-container"] {
      padding-top: 6vh !important;
      padding-bottom: 4vh !important;
    }
    </style>
    """, unsafe_allow_html=True)

    # ── 로그인 헤더 ──
    st.markdown("""
    <div style="text-align:center; margin-bottom:2.25rem;">
      <div style="display:inline-flex; align-items:center; justify-content:center;
                  background:linear-gradient(135deg,#7c3aed,#4f46e5);
                  border-radius:16px; width:64px; height:64px; font-size:1.9rem;
                  box-shadow:0 8px 24px rgba(124,58,237,0.45); margin-bottom:1rem;">
        🏠
      </div>
      <h1 style="color:#ffffff; font-size:1.85rem; font-weight:800;
                 letter-spacing:-0.02em; margin:0 0 0.4rem;">
        네이버 부동산 블로그 자동화
      </h1>
      <p style="color:#94a3b8; font-size:0.9rem; margin:0;">
        AI 원고 생성 &nbsp;·&nbsp; Leonardo 이미지 &nbsp;·&nbsp; 자동 발행 통합 플랫폼
      </p>
    </div>
    """, unsafe_allow_html=True)

    _, center, _ = st.columns([1, 1.1, 1])
    with center:
        with st.form("login_form"):
            uid = st.text_input("아이디", placeholder="아이디를 입력하세요")
            pw  = st.text_input("비밀번호", type="password", placeholder="비밀번호를 입력하세요")
            submitted = st.form_submit_button("🔐  로그인", use_container_width=True, type="primary")
        if submitted:
            if uid == get_secret("APP_USER") and pw == get_secret("APP_PASSWORD"):
                st.session_state["authenticated"] = True
                st.rerun()
            else:
                st.error("아이디 또는 비밀번호가 올바르지 않습니다.")

        st.markdown("""
        <div style="display:flex; justify-content:center; gap:1.5rem; margin-top:1.25rem;">
          <span style="color:#475569; font-size:0.78rem;">✨ Gemini AI 원고</span>
          <span style="color:#475569; font-size:0.78rem;">🎨 Leonardo 이미지</span>
          <span style="color:#475569; font-size:0.78rem;">🚀 자동 발행</span>
        </div>
        """, unsafe_allow_html=True)
    st.stop()

# ── 세션 초기화 ──
for k, v in {
    "generated_content": "",
    "last_post_dir": None,
    "generation_logs": [],
    "generation_done": False,
    "editor_post_key": "",
    "edited_content": "",
    "img_order": [],
    "last_upload_batch_id": "",
}.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ══════════════════════════════════════════
# 헬퍼 함수
# ══════════════════════════════════════════

def get_all_posts():
    """posts/ 아래 포스트를 최신순으로 반환"""
    posts = []
    if not POSTS_DIR.exists():
        return posts
    for date_dir in sorted(POSTS_DIR.iterdir(), reverse=True):
        if not date_dir.is_dir():
            continue
        for post_dir in sorted(date_dir.iterdir(), key=lambda d: d.stat().st_mtime, reverse=True):
            if not post_dir.is_dir():
                continue
            content_file = post_dir / "content.txt"
            if content_file.exists():
                posts.append({
                    "date":  date_dir.name,
                    "title": post_dir.name,
                    "dir":   post_dir,
                    "content_path": content_file,
                })
    return posts

def get_images(folder: Path):
    order_file = folder / "image_order.txt"
    all_imgs = [f for f in folder.iterdir()
                if f.is_file() and f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")]
    try:
        all_imgs.sort(key=lambda x: int(x.stem))
    except Exception:
        all_imgs.sort()

    if order_file.exists():
        img_map = {f.name: f for f in all_imgs}
        ordered, seen = [], set()
        for name in order_file.read_text(encoding="utf-8").splitlines():
            name = name.strip()
            if name in img_map and name not in seen:
                ordered.append(img_map[name])
                seen.add(name)
        for f in all_imgs:
            if f.name not in seen:
                ordered.append(f)
        return ordered
    return all_imgs


def load_img_order(post_dir: Path) -> list:
    return [str(p) for p in get_images(post_dir)]


def save_img_order(post_dir: Path, order: list):
    (post_dir / "image_order.txt").write_text(
        "\n".join(Path(p).name for p in order), encoding="utf-8"
    )

def check_env():
    return {
        "Gemini API":   bool(get_secret("GEMINI_API_KEY")),
        "Leonardo API": bool(get_secret("LEONARDO_API_KEY")),
        "Naver ID":     bool(get_secret("NAVER_ID")),
        "Naver PW":     bool(get_secret("NAVER_PASSWORD")),
    }


def _auto_generate_prompts(content: str, gemini_key: str) -> list[str]:
    """원고 본문에서 Gemini로 이미지 프롬프트 5개를 자동 생성합니다."""
    if gemini_key:
        try:
            import google.generativeai as genai
            genai.configure(api_key=gemini_key)
            model = genai.GenerativeModel("gemini-1.5-flash")
            excerpt = content[:2000]
            resp = model.generate_content(
                "다음 부동산 블로그 원고를 읽고, Leonardo AI 이미지 생성에 사용할 프롬프트를 영어로 5개 작성해주세요.\n"
                "각 프롬프트는 구체적인 장면 묘사(장소·조명·분위기 포함)여야 합니다.\n"
                "번호·기호 없이 한 줄에 하나씩만 출력하세요.\n\n"
                f"원고:\n{excerpt}"
            )
            lines = [l.strip() for l in resp.text.splitlines() if l.strip() and len(l.strip()) > 15]
            if lines:
                return lines[:7]
        except Exception:
            pass

    # Gemini 미설정 또는 실패 시 기본 부동산 프롬프트
    return [
        "Modern Korean luxury apartment complex, aerial view, blue sky, photorealistic 8K",
        "Korean apartment living room interior, minimalist design, natural sunlight",
        "Seoul cityscape with high-rise apartments, golden hour, dramatic sky",
        "New apartment construction site, crane, modern architecture, daytime",
        "Korean real estate model house, premium furniture, bright clean interior",
    ]


def render_image_manager(post_dir: Path, order_key: str, prefix: str):
    """이미지 관리 UI: 체크박스 일괄 작업 + 개별 ↑↓🗑 + 파일 추가."""

    if order_key not in st.session_state:
        st.session_state[order_key] = [str(p) for p in get_images(post_dir)]
    imgs: list = st.session_state[order_key]

    if not imgs:
        st.info("이미지가 없습니다.")
        return

    # 현재 체크된 이미지 이름 수집 (checkbox 위젯에서 읽기)
    checked_names: set = {
        Path(p).name for p in imgs
        if st.session_state.get(f"{prefix}_chk_{Path(p).name}", False)
    }

    img_col, action_col = st.columns([4, 1], gap="medium")

    # ── 오른쪽: 일괄 작업 패널 ──
    with action_col:
        st.markdown("**일괄 작업**")
        st.caption(f"{len(checked_names)} / {len(imgs)}개 선택")

        if st.button("☑ 전체 선택", use_container_width=True, key=f"{prefix}_sel_all"):
            for p in imgs:
                st.session_state[f"{prefix}_chk_{Path(p).name}"] = True
            st.rerun()

        if st.button("□ 전체 해제", use_container_width=True, key=f"{prefix}_desel_all"):
            for p in imgs:
                st.session_state[f"{prefix}_chk_{Path(p).name}"] = False
            st.rerun()

        st.divider()

        if st.button(
            f"🗑 선택 삭제\n({len(checked_names)}개)",
            use_container_width=True,
            type="primary",
            disabled=(len(checked_names) == 0),
            key=f"{prefix}_bulk_del",
        ):
            new_imgs = []
            for p in imgs:
                name = Path(p).name
                if name in checked_names:
                    Path(p).unlink(missing_ok=True)
                    st.session_state.pop(f"{prefix}_chk_{name}", None)
                else:
                    new_imgs.append(p)
            st.session_state[order_key] = new_imgs
            save_img_order(post_dir, new_imgs)
            st.rerun()

        st.divider()

        move_disabled = len(checked_names) == 0
        if st.button("↑ 위로", use_container_width=True,
                     disabled=move_disabled, key=f"{prefix}_bulk_up"):
            names = [Path(p).name for p in imgs]
            for i in range(1, len(names)):
                if names[i] in checked_names and names[i - 1] not in checked_names:
                    names[i], names[i - 1] = names[i - 1], names[i]
            nm2p = {Path(p).name: p for p in imgs}
            new_order = [nm2p[n] for n in names if n in nm2p]
            st.session_state[order_key] = new_order
            save_img_order(post_dir, new_order)
            st.rerun()

        if st.button("↓ 아래로", use_container_width=True,
                     disabled=move_disabled, key=f"{prefix}_bulk_dn"):
            names = [Path(p).name for p in imgs]
            for i in range(len(names) - 2, -1, -1):
                if names[i] in checked_names and names[i + 1] not in checked_names:
                    names[i], names[i + 1] = names[i + 1], names[i]
            nm2p = {Path(p).name: p for p in imgs}
            new_order = [nm2p[n] for n in names if n in nm2p]
            st.session_state[order_key] = new_order
            save_img_order(post_dir, new_order)
            st.rerun()

    # ── 왼쪽: 이미지 그리드 ──
    with img_col:
        COLS = 5
        for row_s in range(0, len(imgs), COLS):
            row_imgs = imgs[row_s : row_s + COLS]
            cols = st.columns(COLS)
            for j, img_path in enumerate(row_imgs):
                idx = row_s + j
                name = Path(img_path).name
                with cols[j]:
                    st.checkbox(
                        "선택",
                        key=f"{prefix}_chk_{name}",
                        label_visibility="collapsed",
                    )
                    try:
                        st.image(img_path, use_container_width=True)
                    except Exception:
                        st.write("⚠")
                    st.caption(f"**{idx+1}번** `{name}`")
                    bc1, bc2, bc3 = st.columns(3)
                    with bc1:
                        if st.button("↑", key=f"{prefix}_up_{idx}",
                                     use_container_width=True, disabled=(idx == 0)):
                            imgs[idx], imgs[idx - 1] = imgs[idx - 1], imgs[idx]
                            st.session_state[order_key] = imgs
                            save_img_order(post_dir, imgs)
                            st.rerun()
                    with bc2:
                        if st.button("↓", key=f"{prefix}_dn_{idx}",
                                     use_container_width=True,
                                     disabled=(idx == len(imgs) - 1)):
                            imgs[idx], imgs[idx + 1] = imgs[idx + 1], imgs[idx]
                            st.session_state[order_key] = imgs
                            save_img_order(post_dir, imgs)
                            st.rerun()
                    with bc3:
                        if st.button("🗑", key=f"{prefix}_del_{idx}",
                                     use_container_width=True):
                            Path(imgs[idx]).unlink(missing_ok=True)
                            imgs.pop(idx)
                            st.session_state[order_key] = imgs
                            save_img_order(post_dir, imgs)
                            st.rerun()

    # ── 이미지 추가 업로드 ──
    st.write("")
    upload_batch_key = f"{prefix}_last_upload"
    if upload_batch_key not in st.session_state:
        st.session_state[upload_batch_key] = ""

    added_files = st.file_uploader(
        "📎 이미지 추가 (여러 장 동시 선택 가능)",
        type=["jpg", "jpeg", "png", "webp"],
        accept_multiple_files=True,
        key=f"{prefix}_uploader",
    )
    if added_files:
        batch_id = "_".join(f"{f.name}_{f.size}" for f in added_files)
        if st.session_state[upload_batch_key] != batch_id:
            existing_nums = [int(Path(p).stem) for p in imgs if Path(p).stem.isdigit()]
            next_num = max(existing_nums, default=0) + 1
            added_names = []
            for uf in added_files:
                save_path = post_dir / f"{next_num}.jpg"
                save_path.write_bytes(uf.getvalue())
                imgs.append(str(save_path))
                added_names.append(save_path.name)
                next_num += 1
            st.session_state[order_key] = imgs
            save_img_order(post_dir, imgs)
            st.session_state[upload_batch_key] = batch_id
            st.success(f"✅ {len(added_names)}장 추가됨: {', '.join(added_names)}")
            st.rerun()

def run_generation(choice, input_data, persona, extra):
    """subprocess로 원고 생성 실행. 실시간 로그를 yield."""
    python_exe = sys.executable
    args = [python_exe, str(BASE_DIR / "run_generate.py"), choice]
    if input_data: args.append(input_data)
    if persona:    args.append(persona)
    if extra:      args.append(extra)

    proc = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(BASE_DIR),
    )
    result_dir = None
    for line in proc.stdout:
        line = line.rstrip()
        if line.startswith("RESULT_DIR:"):
            result_dir = line[11:]
        else:
            yield line, None
    proc.wait()
    yield None, result_dir

# ══════════════════════════════════════════
# 사이드바 — 마케팅 & 스타일 설정
# ══════════════════════════════════════════
with st.sidebar:
    st.header("⚙️ 마케팅 & 스타일 설정")

    with st.expander("📂 1. 글쓰기 모드", expanded=True):
        mode = st.radio(
            "모드 선택",
            ["뉴스 자동 크롤링", "키워드 검색 뉴스", "자유 주제 기획"],
            index=0,
        )
        input_data = ""
        if mode == "키워드 검색 뉴스":
            input_data = st.text_input("검색 키워드", placeholder="예: 마포 아파트 청약")
        elif mode == "자유 주제 기획":
            input_data = st.text_input("기획 주제", placeholder="예: 수익형 상가 투자법")

        choice_map = {"뉴스 자동 크롤링": "1", "키워드 검색 뉴스": "2", "자유 주제 기획": "3"}
        choice = choice_map[mode]

    with st.expander("📂 2. 페르소나 설정 (말투)", expanded=True):
        persona_options = [
            "신뢰도 높은 전문 브리핑",
            "친근한 이웃집 스타일",
            "냉철한 시장 분석가",
            "감성적인 스토리텔링",
            "긴박한 분양/급매 뉴스",
            "심플한 핵심 요약",
        ]
        persona = st.selectbox("블로그 작성 어조", persona_options)

    with st.expander("📂 3. 추가 지시사항", expanded=False):
        extra = st.text_area(
            "AI에게 추가로 전달할 지침",
            placeholder="예: 30대 신혼부부 타겟으로 작성\n예: 3.3㎡당 가격 비교표 반드시 포함",
            height=100,
        )

    with st.expander("📂 4. 미리보기 스타일", expanded=False):
        content_font_size = st.slider("본문 글씨 크기 (px)", 12, 24, 16)
        text_align = st.radio("정렬", ["좌측", "중앙", "양쪽"], horizontal=True)

    with st.expander("📂 5. CTA 고정 문구", expanded=False):
        cta_text = st.text_area(
            "원고 맨 뒤에 붙일 고정 문구",
            value="더 자세한 현장 브리핑이나 투자 방향이 궁금하시다면 언제든 편하게 문의주세요.\n여러분의 상황에 맞는 최적의 플랜을 함께 고민하겠습니다.",
            height=90,
        )

    st.divider()
    # API 키 상태 (사이드바 하단)
    env = check_env()
    for name, ok in env.items():
        st.markdown(f"{'🟢' if ok else '🔴'} {name}")

    st.divider()
    if st.button("🔓 로그아웃", use_container_width=True):
        st.session_state["authenticated"] = False
        st.rerun()

# ══════════════════════════════════════════
# 메인 — 탭
# ══════════════════════════════════════════
st.title("🏠 네이버 부동산 블로그 자동화")

if IS_CLOUD:
    st.info(
        "☁️ **클라우드 모드** — 원고 생성·편집·이미지 생성·미리보기를 지원합니다.  \n"
        "네이버 업로드는 **ZIP 다운로드 후 로컬**에서 `python step2_upload.py`로 실행하세요.  \n"
        "생성된 포스트는 현재 세션에서만 유지됩니다. 작업 후 ZIP을 반드시 저장하세요."
    )

# ── 발행 큐 상태 메트릭 바 (Supabase 연결 시 상시 표시) ──
if bool(get_secret("SUPABASE_URL") and get_secret("SUPABASE_KEY")):
    _q_rows = _supabase_all_rows()
    if _q_rows:
        _q_pend = sum(1 for r in _q_rows if r.get("status") == "pending")
        _q_proc = sum(1 for r in _q_rows if r.get("status") == "processing")
        _q_done = sum(1 for r in _q_rows if r.get("status") == "done")
        _q_err  = sum(1 for r in _q_rows if r.get("status") == "error")
        _qm1, _qm2, _qm3, _qm4, _qm5 = st.columns(5)
        _qm1.metric("📋 전체 요청",  len(_q_rows))
        _qm2.metric("🟡 대기 중",    _q_pend)
        _qm3.metric("🔵 처리 중",    _q_proc)
        _qm4.metric("🟢 발행 완료",  _q_done)
        _qm5.metric("🔴 오류",       _q_err,
                    delta=(f"−{_q_err}" if _q_err else None),
                    delta_color=("inverse" if _q_err else "normal"))
        st.markdown("<div style='margin-bottom:0.5rem;'></div>", unsafe_allow_html=True)

tab_editor, tab_image, tab_posts, tab_status = st.tabs(["📝 원고 에디터", "🎨 이미지 생성", "📂 포스트 관리", "📊 시스템 상태"])

# ─────────────────────────────────────────
# Tab 1: 원고 에디터
# ─────────────────────────────────────────
with tab_editor:

    # ══ 섹션 1: 원고 생성 ══
    st.subheader("1  AI 원고 자동 생성")
    col_btn, col_hint = st.columns([1, 2])
    with col_btn:
        go = st.button("✨ 블로그 원고 자동 생성", type="primary", use_container_width=True)
    with col_hint:
        st.info(f"모드: **{mode}**  |  어조: **{persona}**  |  약 2~5분 소요")

    if go:
        if choice in ("2", "3") and not input_data.strip():
            st.warning("키워드 또는 주제를 입력해주세요.")
        else:
            st.session_state.update({
                "generation_done": False,
                "generation_logs": [],
                "last_post_dir":   None,
                "editor_post_key": "",
            })
            log_box  = st.empty()
            logs, done_dir = [], None
            extra_full = extra.strip() or None

            for log_line, result_dir in run_generation(choice, input_data.strip(), persona, extra_full):
                if log_line is not None:
                    logs.append(log_line)
                    log_box.code("\n".join(logs[-35:]), language=None)
                else:
                    done_dir = result_dir

            log_box.code("\n".join(logs), language=None)

            if done_dir:
                raw = ""
                cf = Path(done_dir) / "content.txt"
                if cf.exists():
                    raw = cf.read_text(encoding="utf-8")
                    if cta_text.strip() and cta_text.strip() not in raw:
                        raw = raw + "\n\n" + cta_text.strip()

                st.session_state.update({
                    "last_post_dir":   done_dir,
                    "generation_done": True,
                    "generation_logs": logs,
                    "edited_content":  raw,
                    "editor_post_key": done_dir,
                    "img_order":       load_img_order(Path(done_dir)),
                })
                st.success(f"✅ 완료!  저장 위치: {done_dir}")
                st.rerun()
            else:
                st.error("생성 중 오류가 발생했습니다. 위 로그를 확인해주세요.")

    # ══ 섹션 2+3+4: 편집 / 미리보기 / 이미지 관리 / 업로드 ══
    if st.session_state["generation_done"] and st.session_state["last_post_dir"]:
        post_dir = Path(st.session_state["last_post_dir"])

        # 포스트가 바뀌면 세션 재초기화
        if st.session_state["editor_post_key"] != str(post_dir):
            raw = (post_dir / "content.txt").read_text(encoding="utf-8") \
                  if (post_dir / "content.txt").exists() else ""
            if cta_text.strip() and cta_text.strip() not in raw:
                raw = raw + "\n\n" + cta_text.strip()
            st.session_state["edited_content"]  = raw
            st.session_state["img_order"]       = load_img_order(post_dir)
            st.session_state["editor_post_key"] = str(post_dir)

        st.divider()

        # ── 섹션 2: 편집 ←→ 미리보기 분할 ──
        st.subheader("2  편집  &  미리보기")
        col_ed, col_pv = st.columns([1, 1], gap="large")

        # ▌왼쪽: 원고 편집기
        with col_ed:
            st.markdown("##### ✏️ 원고 편집")

            new_content = st.text_area(
                "editor",
                value=st.session_state["edited_content"],
                height=560,
                label_visibility="collapsed",
                key="main_editor",
            )
            # 내용이 바뀌면 즉시 세션 반영 (다음 rerun에서 preview도 갱신)
            if new_content != st.session_state["edited_content"]:
                st.session_state["edited_content"] = new_content

            # 글자 수 게이지
            char_cnt = len(new_content)
            badge = "🟢" if char_cnt >= 5000 else ("🟡" if char_cnt >= 3000 else "🔴")
            st.progress(min(1.0, char_cnt / 5000),
                        text=f"{badge} {char_cnt:,}자  /  목표 5,000자")

            c1, c2, c3 = st.columns(3)
            with c1:
                if st.button("💾 저장", use_container_width=True, key="ed_save"):
                    (post_dir / "content.txt").write_text(new_content, encoding="utf-8")
                    st.toast("저장됐습니다 ✅")
            with c2:
                if st.button("↩ 자동 줄바꿈", use_container_width=True, key="ed_break"):
                    st.session_state["edited_content"] = re.sub(
                        r"(?<![0-9])\.(\s|$)", ".\n\n", new_content)
                    st.rerun()
            with c3:
                if st.button("📌 CTA 삽입", use_container_width=True, key="ed_cta"):
                    if cta_text.strip() and cta_text.strip() not in new_content:
                        st.session_state["edited_content"] = new_content + "\n\n" + cta_text.strip()
                        st.rerun()

        # ▌오른쪽: 블로그 미리보기 (텍스트 + 이미지 교차)
        with col_pv:
            st.markdown("##### 👁 블로그 미리보기")

            insert_every = st.select_slider(
                "이미지 삽입 간격 (문단 수)",
                options=[1, 2, 3, 4, 5, 6, 8, 10],
                value=3,
                help="몇 문단마다 이미지 1장을 삽입할지 설정합니다",
            )

            imgs      = st.session_state["img_order"]
            paras     = [p.strip() for p in st.session_state["edited_content"].split("\n\n") if p.strip()]
            img_idx   = 0

            align_map = {"좌측": "left", "중앙": "center", "양쪽": "justify"}
            align_css = align_map.get(text_align, "left")

            # 스크롤 가능한 미리보기 컨테이너
            with st.container(border=True):
                for i, para in enumerate(paras):
                    st.markdown(
                        f"<p style='font-size:{content_font_size}px;line-height:1.9;"
                        f"text-align:{align_css};font-family:Malgun Gothic,sans-serif;"
                        f"margin:0 0 10px 0;'>{para}</p>",
                        unsafe_allow_html=True,
                    )
                    if imgs and img_idx < len(imgs) and (i + 1) % insert_every == 0:
                        try:
                            st.image(imgs[img_idx], use_container_width=True)
                        except Exception:
                            st.caption(f"⚠ {Path(imgs[img_idx]).name}")
                        img_idx += 1

                # 남은 이미지를 미리보기 맨 뒤에
                while img_idx < len(imgs):
                    try:
                        st.image(imgs[img_idx], use_container_width=True)
                    except Exception:
                        st.caption(f"⚠ {Path(imgs[img_idx]).name}")
                    img_idx += 1

        # ── 섹션 3: 이미지 관리 ──
        st.divider()
        st.subheader(f"3  이미지 관리  ({len(st.session_state['img_order'])}장)")
        st.caption("체크 후 일괄 삭제·이동 또는 개별 ↑↓🗑. 변경 즉시 미리보기에 반영됩니다.")
        render_image_manager(post_dir, "img_order", "ed")

        # ── 섹션 4: 업로드 ──
        st.divider()
        st.subheader("4  네이버 블로그 업로드")

        char_cnt = len(st.session_state["edited_content"])
        img_cnt  = len(st.session_state["img_order"])
        st.info(
            f"📄 원고 **{char_cnt:,}자**  |  🖼️ 이미지 **{img_cnt}장**  |  📁 `{post_dir.name}`"
        )

        # ── 최종 포스팅 (Supabase 대기열) ──
        supabase_ok = bool(get_secret("SUPABASE_URL") and get_secret("SUPABASE_KEY"))
        if supabase_ok:
            # 예약 발행 설정
            use_schedule = st.checkbox(
                "📅 예약 발행 설정",
                key="use_schedule_chk",
                help="체크하면 지정한 날짜/시각에 자동으로 발행됩니다. watcher.py가 실행 중이어야 합니다.",
            )
            scheduled_at_val = ""
            if use_schedule:
                _sc1, _sc2 = st.columns(2)
                with _sc1:
                    _sched_date = st.date_input(
                        "발행 날짜",
                        value=datetime.datetime.now().date() + datetime.timedelta(days=1),
                        key="sched_date",
                    )
                with _sc2:
                    _sched_time = st.time_input(
                        "발행 시각",
                        value=datetime.time(9, 0),
                        key="sched_time",
                    )
                scheduled_at_val = datetime.datetime.combine(_sched_date, _sched_time).isoformat()
                st.info(
                    f"📅 **{_sched_date}** {_sched_time.strftime('%H:%M')} 에 자동 발행 예약됩니다.  \n"
                    "로컬 PC의 `watcher.py` 가 해당 시간에 실행 중이어야 합니다."
                )

            btn_label = (
                f"📋 예약 발행 등록 ({_sched_date} {_sched_time.strftime('%H:%M')})"
                if use_schedule else "📋 즉시 발행 대기열 등록"
            )
            if st.button(btn_label, type="primary", use_container_width=True, key="final_post_btn"):
                content_now = st.session_state["edited_content"]
                paras       = [p.strip() for p in content_now.split("\n\n") if p.strip()]
                post_title  = paras[0] if paras else post_dir.name
                tags        = _extract_tags(content_now)
                (post_dir / "content.txt").write_text(content_now, encoding="utf-8")
                save_img_order(post_dir, st.session_state["img_order"])

                with st.spinner("Supabase에 등록 중..."):
                    ok, msg = _supabase_push(
                        post_title, content_now, tags, post_dir.name,
                        scheduled_at=scheduled_at_val,
                    )

                if ok:
                    if scheduled_at_val:
                        st.success(
                            f"✅ 예약 발행 등록 완료! (ID: `{msg}`)  \n"
                            f"📅 **{_sched_date} {_sched_time.strftime('%H:%M')}** 에 자동 발행됩니다."
                        )
                    else:
                        st.success(
                            f"✅ 발행 대기열에 등록됐습니다! (ID: `{msg}`)  \n"
                            "로컬 매크로 PC에서 `python watcher.py` 를 실행하면 자동 업로드됩니다."
                        )
                else:
                    st.error(f"❌ 등록 실패: {msg}")
        else:
            st.button("📋 최종 포스팅 (Supabase 미설정)", disabled=True,
                      use_container_width=True, key="final_post_disabled")
            st.caption("시스템 상태 탭에서 SUPABASE_URL / SUPABASE_KEY 설정을 확인하세요.")

        st.divider()

        if IS_CLOUD:
            # ── 클라우드: 직접 업로드 불가 안내 ──────────────────────────────
            st.markdown("""
<div style="background:#fef3c7; border:1.5px solid #f59e0b; border-radius:12px;
            padding:1.1rem 1.4rem; margin-bottom:1rem;">
  <p style="margin:0 0 0.5rem; font-weight:700; color:#92400e; font-size:0.95rem;">
    ⚠️ 클라우드 환경에서는 직접 업로드가 불가합니다
  </p>
  <p style="margin:0; color:#78350f; font-size:0.875rem; line-height:1.65;">
    네이버는 클라우드 서버 IP + 헤드리스 브라우저를 <strong>봇으로 감지하여 로그인을 차단</strong>합니다.<br>
    위의 <strong>📋 발행 대기열 등록</strong> 버튼으로 Supabase에 저장한 뒤,<br>
    로컬 PC에서 <code>python watcher.py</code> 를 실행하면 자동으로 네이버에 업로드됩니다.
  </p>
</div>
            """, unsafe_allow_html=True)
            col_save_c, col_dl_c = st.columns(2)
            with col_save_c:
                if st.button("💾 최신 상태 저장", use_container_width=True, key="save_before_zip"):
                    (post_dir / "content.txt").write_text(
                        st.session_state["edited_content"], encoding="utf-8")
                    save_img_order(post_dir, st.session_state["img_order"])
                    st.toast("저장됐습니다 ✅")
            with col_dl_c:
                zip_bytes = make_zip(post_dir)
                st.download_button(
                    label="📦 포스트 ZIP 다운로드",
                    data=zip_bytes,
                    file_name=f"{post_dir.name}.zip",
                    mime="application/zip",
                    use_container_width=True,
                    key="zip_download",
                )
        else:
            # ── 로컬 PC: 직접 Playwright 업로드 ─────────────────────────────
            col_up, col_dl = st.columns(2)
            with col_up:
                if st.button("📤 네이버 블로그에 업로드", type="primary",
                             use_container_width=True, key="upload_btn"):
                    (post_dir / "content.txt").write_text(
                        st.session_state["edited_content"], encoding="utf-8")
                    save_img_order(post_dir, st.session_state["img_order"])
                    st.info("브라우저가 자동으로 열립니다. 글 확인 후 [발행] 버튼을 직접 눌러주세요.")
                    try:
                        from step2_upload import upload_to_naver_blog
                        upload_to_naver_blog(
                            folder_path=str(post_dir),
                            headless=False,
                            auto_publish=False,
                        )
                    except Exception as e:
                        st.error(f"업로드 오류: {e}")

            with col_dl:
                if st.button("💾 최신 상태 저장", use_container_width=True, key="save_before_zip"):
                    (post_dir / "content.txt").write_text(
                        st.session_state["edited_content"], encoding="utf-8")
                    save_img_order(post_dir, st.session_state["img_order"])
                    st.toast("저장됐습니다 ✅")

                zip_bytes = make_zip(post_dir)
                st.download_button(
                    label="📦 포스트 ZIP 다운로드",
                    data=zip_bytes,
                    file_name=f"{post_dir.name}.zip",
                    mime="application/zip",
                    use_container_width=True,
                    key="zip_download",
                )

# ─────────────────────────────────────────
# Tab 2: 이미지 생성 / 수집
# ─────────────────────────────────────────
with tab_image:
    leo_key = get_secret("LEONARDO_API_KEY")

    gen_mode = st.radio(
        "방식 선택",
        ["🤖 AI 이미지 생성 (Leonardo)", "📰 뉴스·URL에서 이미지 수집", "🖼️ 업로드 이미지 기반 생성"],
        horizontal=True,
    )
    st.divider()

    # ══ 모드 1: AI 이미지 생성 ══
    if gen_mode == "🤖 AI 이미지 생성 (Leonardo)":
            if not leo_key:
                st.error("❌ LEONARDO_API_KEY가 없습니다. .env 파일 또는 Streamlit Secrets에 추가하세요.")
            else:
                posts = get_all_posts()
                if not posts:
                    st.info("먼저 '원고 에디터' 탭에서 포스트를 생성해주세요.")
                else:
                    col_sel, col_cnt, col_over = st.columns([3, 1, 1])
                    with col_sel:
                        labels  = [f"[{p['date']}]  {p['title']}" for p in posts]
                        sel_idx = st.selectbox("포스트 선택", range(len(posts)),
                                               format_func=lambda i: labels[i], key="img_post_sel")
                    with col_cnt:
                        num_per_prompt = st.number_input("장 수 (프롬프트당)", min_value=1, max_value=4, value=1,
                                                          help="프롬프트 1개당 생성할 이미지 수")
                    with col_over:
                        overwrite = st.checkbox("기존 덮어쓰기", value=False)

                    post_dir     = posts[sel_idx]["dir"]
                    prompts_file = post_dir / "prompts.txt"

                    # 기존 prompts.txt 내용 로드 (없으면 빈 문자열)
                    default_prompts = prompts_file.read_text(encoding="utf-8").strip() \
                                      if prompts_file.exists() else ""

                    prompt_key = f"img_prompts_{sel_idx}"
                    if prompt_key not in st.session_state:
                        st.session_state[prompt_key] = default_prompts

                    # 자동 추출 / 초기화 버튼
                    col_auto, col_reset = st.columns([1, 1])
                    with col_auto:
                        if st.button("🤖 원고에서 자동 추출 (Gemini)", use_container_width=True,
                                     key="auto_prompts_btn"):
                            content_file = post_dir / "content.txt"
                            if content_file.exists():
                                with st.spinner("Gemini로 이미지 프롬프트 생성 중..."):
                                    auto_p = _auto_generate_prompts(
                                        content_file.read_text(encoding="utf-8"),
                                        get_secret("GEMINI_API_KEY"),
                                    )
                                    st.session_state[prompt_key] = "\n".join(auto_p)
                                st.rerun()
                            else:
                                st.warning("content.txt 파일이 없습니다.")
                    with col_reset:
                        if st.button("↩ 원래대로", use_container_width=True, key="reset_prompts_btn"):
                            st.session_state[prompt_key] = default_prompts
                            st.rerun()

                    # 프롬프트 편집 텍스트 영역 (한 줄 = 이미지 1장)
                    st.markdown("**프롬프트 목록** — 한 줄에 하나씩 입력하세요 (한국어/영어 모두 가능)")
                    prompt_text = st.text_area(
                        "prompts",
                        value=st.session_state[prompt_key],
                        height=210,
                        label_visibility="collapsed",
                        placeholder="예시:\nModern Korean luxury apartment complex, aerial view, golden hour lighting, photorealistic\n서울 강남 아파트 단지 야경, 도심 뷰\nKorean apartment interior, minimalist living room, natural sunlight",
                        key=f"prompt_area_{sel_idx}",
                    )
                    st.session_state[prompt_key] = prompt_text

                    col_save_p, col_spacer = st.columns([1, 3])
                    with col_save_p:
                        if st.button("💾 프롬프트 저장", use_container_width=True, key="save_prompts_btn"):
                            prompts_file.write_text(prompt_text, encoding="utf-8")
                            st.toast("프롬프트 저장됐습니다 ✅")

                    prompt_lines = [l.strip() for l in prompt_text.splitlines() if l.strip()]
                    total_imgs   = len(prompt_lines) * int(num_per_prompt)

                    col_btn, col_info = st.columns([1, 2])
                    with col_btn:
                        gen_btn = st.button(
                            f"🚀 이미지 생성 ({total_imgs}장)",
                            type="primary",
                            disabled=(len(prompt_lines) == 0),
                            use_container_width=True,
                            key="leo_gen_btn",
                        )
                    with col_info:
                        st.info(f"프롬프트 **{len(prompt_lines)}개** × **{int(num_per_prompt)}장** = 총 **{total_imgs}장**  ·  장당 약 30~60초")

                    if gen_btn and prompt_lines:
                        from leonardo_generator import generate_text_to_image, poll_until_complete, download_image

                        progress_bar = st.progress(0)
                        status_txt   = st.empty()
                        done_paths: list = []

                        # 기존 이미지 번호 다음부터 슬롯 배정
                        existing_nums = [int(f.stem) for f in post_dir.iterdir()
                                         if f.is_file() and f.stem.isdigit()
                                         and f.suffix.lower() in (".jpg", ".png", ".jpeg", ".webp")]
                        next_slot = max(existing_nums, default=0) + 1

                        for count, raw_line in enumerate(prompt_lines):
                            # "N. prompt" 형식이면 N을 슬롯으로, 아니면 순서대로
                            num_match = re.match(r"^(\d+)[\.\)]\s*", raw_line)
                            if num_match:
                                slot = int(num_match.group(1))
                                clean_prompt = re.sub(r"^\d+[\.\)]\s*", "", raw_line).strip()
                            else:
                                slot = next_slot + count
                                clean_prompt = raw_line

                            status_txt.write(f"⏳ [{count+1}/{len(prompt_lines)}] 슬롯 {slot} 생성 중...")

                            try:
                                gen_id = generate_text_to_image(
                                    clean_prompt, leo_key, num_images=int(num_per_prompt)
                                )
                                tick_txt = st.empty()
                                def on_tick(elapsed, _t=tick_txt, _s=slot):
                                    _t.caption(f"  대기 중... {elapsed}초 경과 (슬롯 {_s})")
                                urls = poll_until_complete(gen_id, leo_key, on_tick=on_tick)
                                tick_txt.empty()

                                if urls:
                                    for i, url in enumerate(urls):
                                        fname = f"{slot}.jpg" if len(urls) == 1 else f"{slot}_{i+1}.jpg"
                                        sp = post_dir / fname
                                        if not sp.exists() or overwrite:
                                            if download_image(url, str(sp)):
                                                done_paths.append(sp)
                                    status_txt.success(f"✅ [{count+1}/{len(prompt_lines)}] {len(urls)}장 저장")
                                else:
                                    status_txt.warning(f"⚠ [{count+1}/{len(prompt_lines)}] 슬롯 {slot} 실패")
                            except Exception as e:
                                status_txt.error(f"[{count+1}] 오류: {e}")

                            progress_bar.progress((count + 1) / len(prompt_lines))

                        status_txt.success(f"🎉 완료! {len(done_paths)}장 저장됨 → {post_dir}")
                        st.session_state[f"leo_gallery_{sel_idx}"] = [str(p) for p in done_paths]
                        st.rerun()

                    # ── 생성된 이미지 갤러리 (삭제 버튼 포함) ──
                    gallery_key = f"leo_gallery_{sel_idx}"
                    if gallery_key in st.session_state and st.session_state[gallery_key]:
                        valid = [p for p in st.session_state[gallery_key] if Path(p).exists()]
                        if valid:
                            st.divider()
                            st.markdown(f"**방금 생성된 이미지 ({len(valid)}장)**  —  🗑 버튼으로 개별 삭제")
                            GCOLS = 5
                            for row_s in range(0, len(valid), GCOLS):
                                row_imgs = valid[row_s:row_s + GCOLS]
                                cols = st.columns(GCOLS)
                                for j, img_path in enumerate(row_imgs):
                                    with cols[j]:
                                        try:
                                            st.image(img_path, use_container_width=True)
                                        except Exception:
                                            st.write("⚠")
                                        st.caption(Path(img_path).name)
                                        if st.button("🗑", key=f"del_g_{row_s+j}",
                                                     use_container_width=True):
                                            Path(img_path).unlink(missing_ok=True)
                                            st.session_state[gallery_key].remove(img_path)
                                            st.rerun()

    # ══ 모드 2: 뉴스·URL에서 이미지 수집 ══
    elif gen_mode == "📰 뉴스·URL에서 이미지 수집":
        st.markdown("뉴스 기사 URL 또는 키워드로 이미지를 자동 수집하여 포스트 폴더에 저장합니다.")

        fetch_tab_url, fetch_tab_kw = st.tabs(["🔗 기사 URL에서 수집", "🔍 키워드 검색으로 수집"])

        def _pick_save_dir(sel_key: str) -> Path:
            posts_f = get_all_posts()
            opts    = ["📁 새 폴더 (오늘 날짜)"] + [f"[{p['date']}] {p['title']}" for p in posts_f]
            sel     = st.selectbox("저장할 포스트 폴더", opts, key=sel_key)
            if sel == "📁 새 폴더 (오늘 날짜)":
                td = datetime.datetime.now().strftime("%Y-%m-%d")
                return POSTS_DIR / td / "news_images"
            pidx = opts.index(sel) - 1
            return posts_f[pidx]["dir"]

        def _next_img_num(folder: Path) -> int:
            nums = [int(f.stem) for f in folder.iterdir()
                    if f.is_file() and f.stem.isdigit()
                    and f.suffix.lower() in (".jpg", ".png", ".jpeg", ".webp")]
            return max(nums, default=0) + 1

        with fetch_tab_url:
            col_u, col_n = st.columns([3, 1])
            with col_u:
                news_url = st.text_input("뉴스 기사 URL", placeholder="https://n.news.naver.com/...")
            with col_n:
                max_art = st.number_input("최대 이미지 수", 1, 10, 5, key="max_art")
            save_dir_url = _pick_save_dir("url_save_sel")

            if st.button("📰 이미지 수집 시작", type="primary",
                         disabled=not news_url.strip(), key="fetch_url_btn"):
                from image_fetcher import fetch_article_images
                save_dir_url.mkdir(parents=True, exist_ok=True)
                start = _next_img_num(save_dir_url)
                with st.spinner("기사에서 이미지 수집 중..."):
                    nxt = fetch_article_images(news_url.strip(), str(save_dir_url),
                                               start_num=start, max_images=int(max_art))
                collected = nxt - start
                if collected > 0:
                    st.success(f"✅ {collected}장 수집 완료!  저장 위치: {save_dir_url}")
                    imgs_new = [str(save_dir_url / f"{start+i}.jpg") for i in range(collected)
                                if (save_dir_url / f"{start+i}.jpg").exists()]
                    if imgs_new:
                        c2 = st.columns(min(5, len(imgs_new)))
                        for i, p in enumerate(imgs_new):
                            with c2[i % 5]:
                                st.image(p, caption=Path(p).name, use_container_width=True)
                else:
                    st.warning("이미지를 수집하지 못했습니다. URL을 확인해주세요.")

        with fetch_tab_kw:
            col_k, col_nk = st.columns([3, 1])
            with col_k:
                keyword = st.text_input("검색 키워드", placeholder="예: 래미안 원펜타스 조감도")
            with col_nk:
                max_kw = st.number_input("최대 이미지 수", 1, 10, 4, key="max_kw")
            save_dir_kw = _pick_save_dir("kw_save_sel")

            if st.button("🔍 키워드로 이미지 수집", type="primary",
                         disabled=not keyword.strip(), key="fetch_kw_btn"):
                from image_fetcher import _search_naver_images, _download_single
                save_dir_kw.mkdir(parents=True, exist_ok=True)
                start_k = _next_img_num(save_dir_kw)
                with st.spinner(f"'{keyword}' 이미지 검색 중..."):
                    urls_k   = _search_naver_images(keyword.strip(), max_urls=int(max_kw) * 2)
                    dl_count = 0
                    for url_k in urls_k:
                        if dl_count >= int(max_kw):
                            break
                        sp_k = save_dir_kw / f"{start_k + dl_count}.jpg"
                        if _download_single(url_k, str(sp_k)):
                            dl_count += 1
                if dl_count > 0:
                    st.success(f"✅ {dl_count}장 수집 완료!")
                    imgs_k = [str(save_dir_kw / f"{start_k+i}.jpg") for i in range(dl_count)
                              if (save_dir_kw / f"{start_k+i}.jpg").exists()]
                    if imgs_k:
                        ck = st.columns(min(5, len(imgs_k)))
                        for i, p in enumerate(imgs_k):
                            with ck[i % 5]:
                                st.image(p, caption=Path(p).name, use_container_width=True)
                else:
                    st.warning("이미지를 찾지 못했습니다. 키워드를 바꿔보세요.")

    # ══ 모드 3: 업로드 이미지 기반 생성 ══
    else:
        if not leo_key:
            st.error("❌ LEONARDO_API_KEY가 없습니다.")
        else:
            st.markdown("참조 이미지를 업로드하면 그 스타일을 반영한 새 이미지를 생성합니다.")

            col_up, col_form = st.columns([1, 2])
            with col_up:
                uploaded = st.file_uploader(
                    "참조 이미지 업로드",
                    type=["jpg", "jpeg", "png", "webp"],
                    help="조감도, 평면도, 현장 사진 등을 올리면 그 분위기를 반영합니다.",
                )
                if uploaded:
                    st.image(uploaded, caption="업로드된 참조 이미지", use_container_width=True)

            with col_form:
                prompt_input = st.text_area(
                    "이미지 설명 (영문 권장)",
                    placeholder="Modern Korean luxury apartment complex, aerial view,\n"
                                "golden hour lighting, photorealistic, 8K...",
                    height=110,
                )
                strength = st.slider(
                    "원본 이미지 영향도", min_value=0.1, max_value=0.9, value=0.45, step=0.05,
                    help="낮을수록 프롬프트 중심, 높을수록 원본 이미지 유지",
                )
                st.caption(f"{'← 프롬프트 중심':<25} {'원본 유지 →':>20}")

                posts_u   = get_all_posts()
                save_opts = ["📁 새 폴더 (오늘 날짜)"] + [f"[{p['date']}] {p['title']}" for p in posts_u]
                save_sel  = st.selectbox("저장할 포스트 폴더", save_opts, key="upload_save_sel")
                if save_sel == "📁 새 폴더 (오늘 날짜)":
                    td_u       = datetime.datetime.now().strftime("%Y-%m-%d")
                    save_dir_u = POSTS_DIR / td_u / "generated_images"
                else:
                    pidx_u     = save_opts.index(save_sel) - 1
                    save_dir_u = posts_u[pidx_u]["dir"]
                num_gen = st.number_input("생성할 이미지 수", min_value=1, max_value=4, value=1)

            can_gen = bool(prompt_input.strip())
            if not can_gen:
                st.warning("이미지 설명(프롬프트)을 입력해주세요.")

            if st.button("🎨 이미지 생성 시작", type="primary",
                         disabled=not can_gen, use_container_width=False, key="img2img_btn"):
                from leonardo_generator import (
                    upload_init_image, generate_text_to_image,
                    generate_image_to_image, poll_until_complete, download_image,
                )
                save_dir_u.mkdir(parents=True, exist_ok=True)
                status_u = st.empty()
                try:
                    init_image_id = None
                    if uploaded:
                        status_u.write("☁️ 참조 이미지 Leonardo에 업로드 중...")
                        ext = uploaded.name.rsplit(".", 1)[-1].lower()
                        init_image_id = upload_init_image(uploaded.getvalue(), ext, leo_key)
                        status_u.write("✅ 업로드 완료. 이미지 생성 요청 중...")

                    if init_image_id:
                        gen_id_u = generate_image_to_image(
                            prompt_input.strip(), init_image_id, strength, leo_key,
                            num_images=int(num_gen),
                        )
                    else:
                        gen_id_u = generate_text_to_image(
                            prompt_input.strip(), leo_key, num_images=int(num_gen),
                        )

                    tick_u = st.empty()
                    def on_tick_u(elapsed, _t=tick_u):
                        _t.caption(f"생성 중... {elapsed}초 경과")
                    status_u.write("⏳ Leonardo가 이미지를 그리는 중...")
                    urls_u = poll_until_complete(gen_id_u, leo_key, on_tick=on_tick_u)
                    tick_u.empty()

                    if urls_u:
                        start_u = max(
                            ([int(f.stem) for f in save_dir_u.iterdir()
                              if f.is_file() and f.stem.isdigit()] or [0])
                        ) + 1
                        saved_u = []
                        cols_u  = st.columns(min(5, len(urls_u)))
                        for i, url in enumerate(urls_u):
                            fname_u = f"{start_u + i}.jpg"
                            sp_u    = save_dir_u / fname_u
                            if download_image(url, str(sp_u)):
                                saved_u.append(sp_u)
                                with cols_u[i % 5]:
                                    st.image(str(sp_u), caption=fname_u, use_container_width=True)
                                    if st.button("🗑", key=f"del_u_{i}", use_container_width=True):
                                        sp_u.unlink(missing_ok=True)
                                        st.rerun()
                        status_u.success(f"🎉 {len(saved_u)}장 생성 완료!  저장: {save_dir_u}")
                    else:
                        status_u.error("이미지 생성에 실패했습니다. 프롬프트나 API 키를 확인하세요.")
                except Exception as e:
                    status_u.error(f"오류 발생: {e}")


# ─────────────────────────────────────────
# Tab 3: 포스트 관리
# ─────────────────────────────────────────
with tab_posts:
    st.subheader("생성된 포스트 목록")

    posts = get_all_posts()

    if not posts:
        st.info("아직 생성된 포스트가 없습니다. '원고 에디터' 탭에서 첫 원고를 만들어보세요.")
    else:
        labels = [f"[{p['date']}]  {p['title']}" for p in posts]
        sel_idx = st.selectbox("포스트 선택", range(len(posts)), format_func=lambda i: labels[i])

        selected = posts[sel_idx]
        post_dir = selected["dir"]
        images   = get_images(post_dir)

        # ── 상단: 메타 정보 + 액션 버튼 ──
        meta_col, btn_col = st.columns([3, 1])
        with meta_col:
            st.markdown(f"📅 **{selected['date']}** &nbsp;|&nbsp; 🖼️ **{len(images)}장** &nbsp;|&nbsp; 📁 `{post_dir.name}`")
        with btn_col:
            if IS_CLOUD:
                # 클라우드: 네이버 봇 차단 → 버튼 비활성화
                st.button("📤 로컬 PC 전용", disabled=True,
                          use_container_width=True, key="mgmt_upload_disabled")
                st.caption("원고 에디터 탭의 **대기열 등록** 을 이용하세요")
            else:
                if st.button("📤 네이버 업로드", type="primary",
                             use_container_width=True, key="mgmt_upload"):
                    st.info("브라우저가 자동으로 열립니다.")
                    try:
                        from step2_upload import upload_to_naver_blog
                        upload_to_naver_blog(
                            folder_path=str(post_dir),
                            headless=False,
                            auto_publish=False,
                        )
                    except Exception as e:
                        st.error(f"업로드 오류: {e}")

        st.divider()

        # ── 원고 편집 ──
        st.markdown("##### ✏️ 원고 편집")
        content_path = selected["content_path"]
        mgmt_content_key = f"mgmt_content_{sel_idx}"
        if mgmt_content_key not in st.session_state:
            st.session_state[mgmt_content_key] = content_path.read_text(encoding="utf-8")

        mgmt_edited = st.text_area(
            "원고",
            value=st.session_state[mgmt_content_key],
            height=320,
            label_visibility="collapsed",
            key=f"mgmt_editor_{sel_idx}",
        )
        if mgmt_edited != st.session_state[mgmt_content_key]:
            st.session_state[mgmt_content_key] = mgmt_edited

        save_col, zip_col = st.columns(2)
        with save_col:
            if st.button("💾 저장", use_container_width=True, key="mgmt_save"):
                content_path.write_text(st.session_state[mgmt_content_key], encoding="utf-8")
                st.toast("저장됐습니다 ✅")
        with zip_col:
            zip_bytes = make_zip(post_dir)
            st.download_button(
                label="📦 ZIP 다운로드",
                data=zip_bytes,
                file_name=f"{post_dir.name}.zip",
                mime="application/zip",
                use_container_width=True,
                key="mgmt_zip",
            )

        # ── 포스트 삭제 ──
        with st.expander("🗑️ 포스트 삭제", expanded=False):
            st.warning(f"**'{post_dir.name}'** 포스트 폴더 전체(원고 + 이미지)가 영구 삭제됩니다.")
            confirm_del = st.checkbox("삭제를 확인합니다", key=f"confirm_del_{sel_idx}")
            if st.button("🗑️ 포스트 삭제 실행", type="primary",
                         disabled=not confirm_del, key=f"do_del_{sel_idx}"):
                import shutil
                shutil.rmtree(str(post_dir), ignore_errors=True)
                # 해당 포스트의 세션 키 정리
                for k in list(st.session_state.keys()):
                    if f"mgmt_{sel_idx}" in k or f"mgmt_img_order_{sel_idx}" in k:
                        del st.session_state[k]
                st.success(f"✅ '{post_dir.name}' 삭제 완료")
                st.rerun()

        # ── 이미지 관리 ──
        mgmt_order_key = f"mgmt_img_order_{sel_idx}"
        if images:
            st.divider()
            n_imgs = len(st.session_state.get(mgmt_order_key, images))
            st.markdown(f"##### 🖼️ 이미지 관리 ({n_imgs}장)")
            render_image_manager(post_dir, mgmt_order_key, f"mgmt_{sel_idx}")

# ─────────────────────────────────────────
# Tab 3: 시스템 상태
# ─────────────────────────────────────────
with tab_status:
    st.subheader("API 키 설정 상태")
    env = check_env()
    cols = st.columns(4)
    for i, (name, ok) in enumerate(env.items()):
        with cols[i]:
            if ok:
                st.success(f"✅ {name}")
            else:
                st.error(f"❌ {name}")
                st.caption(".env 파일에 키를 입력해주세요.")

    st.divider()
    st.subheader("패키지 상태")
    packages = [
        ("google.generativeai", "Gemini AI"),
        ("playwright",          "Playwright (업로드)"),
        ("easyocr",             "EasyOCR (전화번호 제거)"),
        ("bs4",                 "BeautifulSoup (크롤링)"),
        ("PIL",                 "Pillow (이미지 처리)"),
        ("requests",            "Requests"),
        ("dotenv",              "python-dotenv"),
        ("streamlit",           "Streamlit"),
    ]
    pkg_cols = st.columns(4)
    for i, (pkg, label) in enumerate(packages):
        with pkg_cols[i % 4]:
            try:
                __import__(pkg.split(".")[0])
                st.success(f"✅ {label}")
            except ImportError:
                st.error(f"❌ {label}")

    st.divider()
    st.subheader("포스트 통계")
    posts = get_all_posts()
    col_a, col_b, col_c, col_d = st.columns(4)
    col_a.metric("전체 포스트", f"{len(posts)}개")
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    today_cnt = sum(1 for p in posts if p["date"] == today)
    col_b.metric("오늘 생성", f"{today_cnt}개")
    total_imgs = sum(len(get_images(p["dir"])) for p in posts)
    col_c.metric("전체 수집 이미지", f"{total_imgs}장")
    total_chars = 0
    for p in posts:
        try:
            total_chars += len(p["content_path"].read_text(encoding="utf-8"))
        except Exception:
            pass
    col_d.metric("누적 원고 글자 수", f"{total_chars:,}자")

    # ── 키워드 빈도 차트 ──
    if posts:
        st.divider()
        st.subheader("🔍 포스트 제목 키워드 빈도")
        st.caption("원고 첫 줄(제목)에서 자주 등장하는 단어 Top 15")
        _stopwords = {
            "의", "에", "이", "가", "을", "를", "은", "는", "와", "과",
            "로", "으로", "에서", "에게", "부터", "까지", "이다", "합니다",
            "있는", "있습니다", "하는", "하고", "대한", "또는", "그리고",
            "아파트", "분양", "정보", "현장", "최신",
        }
        _word_freq: dict = {}
        for _p in posts:
            try:
                _first = _p["content_path"].read_text(encoding="utf-8").split("\n")[0]
            except Exception:
                _first = _p["title"]
            for _w in re.findall(r"[가-힣]{2,6}", _first):
                if _w not in _stopwords:
                    _word_freq[_w] = _word_freq.get(_w, 0) + 1
        if _word_freq:
            import pandas as pd
            _chart_data = (
                pd.DataFrame(sorted(_word_freq.items(), key=lambda x: x[1], reverse=True)[:15],
                             columns=["키워드", "빈도"])
                .set_index("키워드")
            )
            st.bar_chart(_chart_data, color="#7c3aed")

    # ── Supabase 발행 대기열 현황 ──
    st.divider()
    st.subheader("📋 Supabase 발행 대기열")

    gs_ok = bool(get_secret("SUPABASE_URL") and get_secret("SUPABASE_KEY"))
    if not gs_ok:
        st.warning(
            "Supabase 미연결 — Streamlit Cloud Secrets에 아래 두 키를 추가하세요:  \n"
            "`SUPABASE_URL` · `SUPABASE_KEY`"
        )
    else:
        _ref_col, _csv_col = st.columns([1, 1])
        with _ref_col:
            if st.button("🔄 대기열 새로고침", key="refresh_queue", use_container_width=True):
                st.rerun()

        with st.spinner("Supabase 조회 중..."):
            rows = _supabase_all_rows()

        if not rows:
            st.info("등록된 항목이 없습니다.")
        else:
            import pandas as pd
            status_colors = {
                "pending":    "🟡",
                "processing": "🔵",
                "done":       "🟢",
                "error":      "🔴",
            }

            # 표시용 컬럼 선택 (scheduled_at 컬럼이 있을 수도 없을 수도 있음)
            _base_cols = ["id", "created_at", "title", "status", "error_msg", "local_folder"]
            _all_keys  = list(rows[0].keys()) if rows else []
            _show_cols = [c for c in (_base_cols + ["scheduled_at"]) if c in _all_keys]

            df = pd.DataFrame(rows)[_show_cols].copy()
            df["status"] = df["status"].map(lambda s: f"{status_colors.get(s,'⚪')} {s}")
            st.dataframe(df, use_container_width=True, hide_index=True)

            with _csv_col:
                _csv_full = pd.DataFrame(rows)
                _csv_bytes = _csv_full.to_csv(index=False).encode("utf-8-sig")
                st.download_button(
                    "📥 발행 이력 CSV 다운로드",
                    data=_csv_bytes,
                    file_name=f"publish_history_{datetime.datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                    mime="text/csv",
                    use_container_width=True,
                    key="csv_dl_btn",
                )

            pending_n = sum(1 for r in rows if r.get("status") == "pending")
            done_n    = sum(1 for r in rows if r.get("status") == "done")
            error_n   = sum(1 for r in rows if r.get("status") == "error")
            sched_n   = sum(1 for r in rows if r.get("scheduled_at"))
            m1, m2, m3, m4, m5 = st.columns(5)
            m1.metric("전체",      len(rows))
            m2.metric("🟡 대기",    pending_n)
            m3.metric("🟢 완료",    done_n)
            m4.metric("🔴 오류",    error_n)
            m5.metric("📅 예약",    sched_n)
