import hashlib
import os
import re
import sys
import subprocess
import datetime
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

# ── Supabase 헬퍼 ──
def _supabase_push(
    title: str, content: str, tags: str, local_folder: str,
    scheduled_at: str = "",
    image_paths: list | None = None,
) -> tuple[bool, str]:
    url = get_secret("SUPABASE_URL")
    # post_queue 는 anon(public) 역할 접근을 막아뒀으므로 RLS를 우회하는 service_role 키를 사용합니다.
    key = get_secret("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        return False, "SUPABASE_URL 또는 SUPABASE_SERVICE_ROLE_KEY 가 secrets에 없습니다."
    try:
        from supabase_db import push_pending, upload_images_to_storage
        image_urls: list[str] = []
        if image_paths:
            image_urls = upload_images_to_storage(url, key, local_folder, image_paths)
        return push_pending(url, key, title, content, tags, local_folder,
                            scheduled_at, image_urls or None)
    except Exception as e:
        return False, str(e)

def _supabase_all_rows() -> list[dict]:
    url = get_secret("SUPABASE_URL")
    key = get_secret("SUPABASE_SERVICE_ROLE_KEY")
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


# ── 쿠키 기반 인증 유지 ──────────────────────────────────────
_COOKIE_NAME = "nba_auth_v1"

def _auth_token() -> str:
    """자격증명 + 서버 시크릿으로 만든 결정론적 토큰."""
    salt = get_secret("APP_SECRET") or "nba_default_salt_2024"
    raw  = f"{get_secret('APP_USER')}:{get_secret('APP_PASSWORD')}:{salt}"
    return hashlib.sha256(raw.encode()).hexdigest()

try:
    from streamlit_cookies_controller import CookieController as _CookieController
    _cc = _CookieController(key="__nba_cc")
    _COOKIES_OK = True
except Exception:
    _cc = None
    _COOKIES_OK = False
# ─────────────────────────────────────────────────────────────


# ZIP 묶기도 post_utils 로 옮겼습니다.
from post_utils import make_zip  # noqa: E402


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
# 전역 스타일 — dashboard_style.py 로 분리했습니다.
from dashboard_style import inject_css

inject_css()

# ══════════════════════════════════════════
# 로그인 게이트
# ══════════════════════════════════════════
if "authenticated" not in st.session_state:
    st.session_state["authenticated"] = False

# 쿠키에 유효한 토큰이 있으면 자동 복원
if not st.session_state["authenticated"] and _COOKIES_OK:
    if _cc.get(_COOKIE_NAME) == _auth_token():
        st.session_state["authenticated"] = True
        st.rerun()

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
                if _COOKIES_OK:
                    _cc.set(_COOKIE_NAME, _auth_token(), max_age=60 * 60 * 24 * 7)
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
    "mode_radio": "뉴스 자동 크롤링",
    "kw_input": "",
}.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ── 트렌드 버튼이 예약해 둔 값을 위젯 생성 '전에' 반영 ──
# Streamlit 은 위젯이 만들어진 뒤에 그 위젯 키(mode_radio 등)를 고치는 걸 막습니다.
# 그래서 트렌드 버튼은 _pending_* 에만 적어두고, 실제 반영은 사이드바 위젯이
# 만들어지기 전인 여기서 합니다.
if st.session_state.pop("_pending_mode", None):
    st.session_state["mode_radio"] = "키워드 검색 뉴스"
_pending_kw = st.session_state.pop("_pending_kw", None)
if _pending_kw:
    st.session_state["kw_input"] = _pending_kw

# ══════════════════════════════════════════
# 헬퍼 함수
# ══════════════════════════════════════════

# 포스트/이미지 헬퍼 — post_utils.py 로 분리했습니다.
from post_utils import (  # noqa: E402
    get_all_posts, get_images, load_img_order, save_img_order,
)


def check_env():
    return {
        "Gemini API":       bool(get_secret("GEMINI_API_KEY")),
        "Leonardo API":     bool(get_secret("LEONARDO_API_KEY")),
        "Naver ID":         bool(get_secret("NAVER_ID")),
        "Naver PW":         bool(get_secret("NAVER_PASSWORD")),
        "Supabase Service Key": bool(get_secret("SUPABASE_SERVICE_ROLE_KEY")),
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

@st.cache_data(ttl=1800)
def _fetch_trends():
    try:
        from naver_news import get_trending_realestate_topics
        return get_trending_realestate_topics(n=6)
    except Exception:
        return []

# ══════════════════════════════════════════
# 사이드바 — 마케팅 & 스타일 설정
# ══════════════════════════════════════════
with st.sidebar:
    st.header("⚙️ 마케팅 & 스타일 설정")

    with st.expander("📂 1. 글쓰기 모드", expanded=True):
        mode = st.radio(
            "모드 선택",
            ["뉴스 자동 크롤링", "키워드 검색 뉴스", "자유 주제 기획"],
            key="mode_radio",
        )
        input_data = ""
        if mode == "키워드 검색 뉴스":
            input_data = st.text_input("검색 키워드", key="kw_input", placeholder="예: 마포 아파트 청약")
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
        if _COOKIES_OK:
            _cc.remove(_COOKIE_NAME)
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

# 대기열 행은 홈 화면과 시스템 상태 탭에서 함께 씁니다 (조회 1회로 공유).
_q_rows = (_supabase_all_rows()
           if get_secret("SUPABASE_URL") and get_secret("SUPABASE_SERVICE_ROLE_KEY")
           else [])

tab_home, tab_editor, tab_image, tab_posts, tab_status = st.tabs(
    ["🏠 홈", "📝 원고 에디터", "🎨 이미지 생성", "📂 포스트 관리", "📊 시스템 상태"]
)

# ─────────────────────────────────────────
# Tab 0: 홈 — 지금 뭘 해야 하는지 한눈에
# ─────────────────────────────────────────
with tab_home:
    from home_status import build_summary, next_action

    _sm = build_summary(_q_rows)
    _act_title, _act_desc = next_action(_sm)

    # ── 지금 할 일 배너 ──
    if _sm["stuck"]:
        st.error(f"### ⚠️ {_act_title}\n{_act_desc}")
    elif _sm["published_today"] > 0:
        st.success(f"### ✅ {_act_title}\n{_act_desc}")
    else:
        st.info(f"### 👉 {_act_title}\n{_act_desc}")

    # ── 핵심 지표 ──
    _h1, _h2, _h3, _h4 = st.columns(4)
    _h1.metric("📤 오늘 발행", f"{_sm['published_today']}건")
    _h2.metric("📝 발행 대기 원고", f"{_sm['ready_posts']}건")
    _h3.metric("📦 새 카드뉴스", f"{_sm['new_zips']}건",
               help="아직 포스트로 등록하지 않은 카드뉴스 ZIP")
    _h4.metric("🗂️ 누적 발행", f"{_sm['total_published']}건")

    st.divider()

    # ── 바로 가기 ──
    st.markdown("##### 바로 시작하기")
    _b1, _b2, _b3 = st.columns(3)
    with _b1:
        st.markdown(
            "**✍️ 새 원고 쓰기**  \n뉴스·키워드·자유주제로 AI 원고를 만듭니다."
        )
        st.caption("→ 위의 **원고 에디터** 탭")
    with _b2:
        st.markdown(
            "**📦 카드뉴스 가져오기**  \n만들어둔 ZIP을 원고+이미지로 등록합니다."
        )
        st.caption("→ 위의 **포스트 관리** 탭")
    with _b3:
        st.markdown(
            "**📤 네이버에 올리기**  \n등록된 원고를 골라 블로그에 올립니다."
        )
        st.caption("→ 위의 **포스트 관리** 탭")

    st.divider()

    # ── 최근 발행 이력 ──
    _rc1, _rc2 = st.columns([3, 2])

    with _rc1:
        st.markdown("##### 🕘 최근 발행")
        if not _sm["recent"]:
            st.caption("아직 발행 이력이 없습니다. 첫 글을 올려보세요.")
        else:
            for _r in _sm["recent"]:
                _when = str(_r.get("at", "")).replace("T", " ")[:16]
                _ttl  = _r.get("title", "")[:44]
                st.markdown(
                    f"<div style='padding:.45rem 0;border-bottom:1px solid #e2e8f0;'>"
                    f"<span style='color:#64748b;font-size:.8rem;'>{_when}</span><br>"
                    f"<span style='color:#1e293b;'>{_ttl}</span> "
                    f"<span style='color:#94a3b8;font-size:.78rem;'>"
                    f"· 이미지 {_r.get('images', 0)}장 · 태그 {len(_r.get('tags', []))}개</span>"
                    f"</div>",
                    unsafe_allow_html=True,
                )

    with _rc2:
        st.markdown("##### 📋 발행 대기열")
        if not _q_rows:
            st.caption("대기열이 비어 있습니다.")
        else:
            _qp = sum(1 for r in _q_rows if r.get("status") == "pending")
            _qc = sum(1 for r in _q_rows if r.get("status") == "processing")
            _qd = sum(1 for r in _q_rows if r.get("status") == "done")
            _qe = sum(1 for r in _q_rows if r.get("status") == "error")
            st.markdown(
                f"- 🟡 대기 중 **{_qp}**건\n"
                f"- 🔵 처리 중 **{_qc}**건\n"
                f"- 🟢 완료 **{_qd}**건\n"
                f"- 🔴 오류 **{_qe}**건"
            )
            if _sm["stuck"]:
                st.warning(f"멈춘 작업 {len(_sm['stuck'])}건 — 시스템 상태 탭에서 정리")

# ─────────────────────────────────────────
# Tab 1: 원고 에디터
# ─────────────────────────────────────────
with tab_editor:

    # ══ 섹션 0: 트렌드 추천 ══
    with st.expander("📈 오늘의 부동산 트렌드 — 클릭하면 자동 적용", expanded=True):
        c_ref, c_cap = st.columns([1, 4])
        with c_ref:
            if st.button("🔄 새로고침", key="refresh_trends"):
                _fetch_trends.clear()
                st.rerun()
        with c_cap:
            st.caption("네이버 부동산 인기 뉴스 기반 · 30분 자동 갱신 · 클릭 시 키워드 자동 입력")

        trends = _fetch_trends()
        if trends:
            cols = st.columns(3)
            for i, t in enumerate(trends):
                with cols[i % 3]:
                    label = t["title"]
                    display = label[:28] + "…" if len(label) > 28 else label
                    if st.button(
                        f"📌 {display}",
                        key=f"trend_btn_{i}",
                        use_container_width=True,
                        help=label,
                    ):
                        # 위젯 키를 직접 고치면 StreamlitAPIException 이 납니다.
                        # 예약만 해두고, 다음 실행 시작 지점에서 반영합니다.
                        st.session_state["_pending_mode"] = True
                        st.session_state["_pending_kw"] = label[:60]
                        st.rerun()
        else:
            st.info("트렌드를 불러올 수 없습니다. 🔄 새로고침을 눌러주세요.")

    st.divider()

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
                done_path = Path(done_dir)
                if done_path.exists() and done_path.is_dir():
                    raw = ""
                    cf = done_path / "content.txt"
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
                        "img_order":       load_img_order(done_path),
                    })
                    st.success(f"✅ 완료!  저장 위치: {done_dir}")
                    st.rerun()
                else:
                    st.error(f"생성된 경로를 찾을 수 없습니다: {done_dir}")
                    st.error("생성 중 오류가 발생했습니다. 생성 경로가 유효한지 확인해주세요.")
            else:
                st.error("생성 중 오류가 발생했습니다. 위 로그를 확인해주세요.")

    # ══ 원고가 없을 때 — 빈 화면 대신 최근 포스트를 바로 열 수 있게 ══
    if not (st.session_state["generation_done"] and st.session_state["last_post_dir"]):
        _recent_posts = get_all_posts()[:6]
        if _recent_posts:
            st.divider()
            st.subheader("이어서 작업하기")
            st.caption("최근 만든 원고입니다. 눌러서 바로 편집·발행 단계로 이동합니다.")

            for _row_start in range(0, len(_recent_posts), 3):
                _pcols = st.columns(3)
                for _off, _p in enumerate(_recent_posts[_row_start:_row_start + 3]):
                    with _pcols[_off]:
                        _imgs_n = len(get_images(_p["dir"]))
                        try:
                            _chars = len(_p["content_path"].read_text(encoding="utf-8"))
                        except Exception:
                            _chars = 0
                        st.markdown(
                            f"<div style='border:1px solid #e2e8f0;border-radius:10px;"
                            f"padding:.7rem .8rem;margin-bottom:.5rem;min-height:5.2rem;'>"
                            f"<div style='color:#64748b;font-size:.75rem;'>{_p['date']}</div>"
                            f"<div style='color:#1e293b;font-weight:600;font-size:.9rem;"
                            f"margin:.2rem 0;'>{_p['title'][:34]}</div>"
                            f"<div style='color:#94a3b8;font-size:.75rem;'>"
                            f"이미지 {_imgs_n}장 · {_chars:,}자</div></div>",
                            unsafe_allow_html=True,
                        )
                        if st.button("✏️ 이어서 편집", key=f"resume_{_row_start}_{_off}",
                                     use_container_width=True):
                            st.session_state["last_post_dir"]   = str(_p["dir"])
                            st.session_state["generation_done"] = True
                            st.session_state["editor_post_key"] = ""   # 아래에서 다시 로드
                            st.rerun()
        else:
            st.divider()
            st.info(
                "아직 만든 원고가 없습니다. 위에서 **블로그 원고 자동 생성**을 눌러 첫 글을 만들거나, "
                "**포스트 관리** 탭에서 카드뉴스 ZIP을 가져오세요."
            )

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
        supabase_ok = bool(get_secret("SUPABASE_URL") and get_secret("SUPABASE_SERVICE_ROLE_KEY"))
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

                with st.spinner("Supabase에 등록 중... (이미지가 있으면 Storage 업로드 포함)"):
                    ok, msg = _supabase_push(
                        post_title, content_now, tags, post_dir.name,
                        scheduled_at=scheduled_at_val,
                        image_paths=st.session_state.get("img_order") or [],
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
            st.caption("시스템 상태 탭에서 SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY 설정을 확인하세요.")

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
            # 발행 옵션 (포스트 관리 탭과 동일하게 제공)
            from cta_presets import load_presets as _load_cta, summary as _cta_sum

            _ed_presets = _load_cta()
            _eo1, _eo2, _eo3 = st.columns(3)
            with _eo1:
                _ed_cta_pick = st.selectbox(
                    "📣 CTA 블록", ["(사용 안 함)"] + [p["name"] for p in _ed_presets],
                    key="ed_cta_pick",
                    help="글 끝에 붙일 CTA를 고르세요. 포스트 관리 탭의 'CTA 관리'에서 추가합니다.",
                )
                if _ed_cta_pick != "(사용 안 함)":
                    _p = next((p for p in _ed_presets if p["name"] == _ed_cta_pick), None)
                    if _p:
                        st.caption(f"구성: {_cta_sum(_p)}")
            with _eo2:
                _ed_category = st.text_input("📁 카테고리", key="ed_category",
                                             placeholder="비우면 기본값")
            with _eo3:
                _ed_visibility = st.selectbox(
                    "🔓 공개 설정",
                    ["(기본값)", "전체공개", "이웃공개", "서로이웃공개", "비공개"],
                    key="ed_visibility",
                )

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
                        _ed_cta_obj = (
                            next((p for p in _ed_presets if p["name"] == _ed_cta_pick), None)
                            if _ed_cta_pick != "(사용 안 함)" else None
                        )
                        upload_to_naver_blog(
                            folder_path=str(post_dir),
                            headless=False,
                            auto_publish=False,
                            cta=_ed_cta_obj,
                            category=_ed_category.strip(),
                            visibility="" if _ed_visibility == "(기본값)" else _ed_visibility,
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
    gen_mode = st.radio(
        "방식 선택",
        ["🤖 AI 이미지 생성 (Pollinations · 무료)", "📰 뉴스·URL에서 이미지 수집",
         "🖼️ 업로드 이미지 기반 생성", "📁 이미지 직접 업로드"],
        horizontal=True,
    )
    st.divider()

    # ══ 모드 1: AI 이미지 생성 (Pollinations) ══
    if gen_mode == "🤖 AI 이미지 생성 (Pollinations · 무료)":
        import urllib.parse as _urlparse
        import warnings as _warnings
        _warnings.filterwarnings("ignore")

        posts = get_all_posts()
        if not posts:
            st.info("먼저 '원고 에디터' 탭에서 포스트를 생성해주세요.")
        else:
            col_sel, col_over = st.columns([4, 1])
            with col_sel:
                labels  = [f"[{p['date']}]  {p['title']}" for p in posts]
                sel_idx = st.selectbox("포스트 선택", range(len(posts)),
                                       format_func=lambda i: labels[i], key="img_post_sel")
            with col_over:
                overwrite = st.checkbox("기존 덮어쓰기", value=False)

            post_dir     = posts[sel_idx]["dir"]
            prompts_file = post_dir / "prompts.txt"

            default_prompts = prompts_file.read_text(encoding="utf-8").strip() \
                              if prompts_file.exists() else ""

            prompt_key = f"img_prompts_{sel_idx}"
            if prompt_key not in st.session_state:
                st.session_state[prompt_key] = default_prompts

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

            col_btn, col_info = st.columns([1, 2])
            with col_btn:
                gen_btn = st.button(
                    f"🚀 이미지 생성 ({len(prompt_lines)}장)",
                    type="primary",
                    disabled=(len(prompt_lines) == 0),
                    use_container_width=True,
                    key="poll_gen_btn",
                )
            with col_info:
                st.info(f"프롬프트 **{len(prompt_lines)}개** = **{len(prompt_lines)}장**  ·  장당 약 10~30초  🆓 API 키 불필요")

            if gen_btn and prompt_lines:
                progress_bar = st.progress(0)
                status_txt   = st.empty()
                done_paths: list = []

                existing_nums = [int(f.stem) for f in post_dir.iterdir()
                                 if f.is_file() and f.stem.isdigit()
                                 and f.suffix.lower() in (".jpg", ".png", ".jpeg", ".webp")]
                next_slot = max(existing_nums, default=0) + 1

                _headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

                for count, raw_line in enumerate(prompt_lines):
                    num_match = re.match(r"^(\d+)[\.\)]\s*", raw_line)
                    if num_match:
                        slot = int(num_match.group(1))
                        clean_prompt = re.sub(r"^\d+[\.\)]\s*", "", raw_line).strip()
                    else:
                        slot = next_slot + count
                        clean_prompt = raw_line

                    sp = post_dir / f"{slot}.jpg"
                    if sp.exists() and not overwrite:
                        status_txt.info(f"⏭ [{count+1}/{len(prompt_lines)}] 슬롯 {slot} 이미 존재 — 건너뜀")
                        progress_bar.progress((count + 1) / len(prompt_lines))
                        continue

                    status_txt.write(f"⏳ [{count+1}/{len(prompt_lines)}] 슬롯 {slot} 생성 중...")
                    try:
                        encoded = _urlparse.quote(clean_prompt)
                        url = (
                            f"https://image.pollinations.ai/prompt/{encoded}"
                            f"?width=1024&height=1024&nologo=true&model=flux-realism&seed={slot}"
                        )
                        resp = requests.get(url, timeout=90, headers=_headers)
                        resp.raise_for_status()
                        sp.write_bytes(resp.content)
                        done_paths.append(str(sp))
                        status_txt.success(f"✅ [{count+1}/{len(prompt_lines)}] 슬롯 {slot} 저장")
                    except Exception as e:
                        status_txt.error(f"[{count+1}] 오류: {e}")

                    progress_bar.progress((count + 1) / len(prompt_lines))

                status_txt.success(f"🎉 완료! {len(done_paths)}장 저장됨 → {post_dir}")
                st.session_state[f"poll_gallery_{sel_idx}"] = done_paths
                st.rerun()

            # ── 생성된 이미지 갤러리 ──
            gallery_key = f"poll_gallery_{sel_idx}"
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
    elif gen_mode == "🖼️ 업로드 이미지 기반 생성":
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

    # ══ 모드 4: 이미지 직접 업로드 ══
    elif gen_mode == "📁 이미지 직접 업로드":

        # ── 드래그&드롭 업로드 영역 CSS ──
        st.markdown("""
<style>
/* 업로드 드롭존 강조 */
section[data-testid="stFileUploadDropzone"] {
  border: 2.5px dashed #7c3aed !important;
  border-radius: 16px !important;
  background: linear-gradient(135deg, rgba(124,58,237,0.04) 0%, rgba(79,70,229,0.04) 100%) !important;
  padding: 2rem 1.5rem !important;
  transition: border-color 0.2s, background 0.2s !important;
  min-height: 160px !important;
}
section[data-testid="stFileUploadDropzone"]:hover,
section[data-testid="stFileUploadDropzone"]:focus-within {
  border-color: #4f46e5 !important;
  background: rgba(124,58,237,0.08) !important;
}
section[data-testid="stFileUploadDropzone"] span {
  font-size: 0.95rem !important;
  color: #6d28d9 !important;
  font-weight: 600 !important;
}
</style>
""", unsafe_allow_html=True)

        st.markdown("""
<div style="margin-bottom:0.75rem;">
  <span style="font-size:1.05rem; font-weight:700; color:#1e293b;">이미지를 드래그하거나 클릭해서 선택하세요</span><br>
  <span style="font-size:0.82rem; color:#64748b;">JPG · PNG · WEBP · GIF · 여러 파일 동시 선택 가능</span>
</div>
""", unsafe_allow_html=True)

        # ── 포스트 폴더 & 옵션 선택 ──
        col_dst, col_opt = st.columns([3, 1])
        with col_dst:
            posts_d   = get_all_posts()
            save_opts_d = ["📁 새 폴더 (오늘 날짜)"] + [f"[{p['date']}] {p['title']}" for p in posts_d]
            save_sel_d  = st.selectbox("저장할 포스트 폴더", save_opts_d, key="direct_save_sel")
        with col_opt:
            start_num_d = st.number_input(
                "시작 번호",
                min_value=1, max_value=999, value=1,
                help="자동 번호 매기기의 시작 번호 (기존 이미지가 있으면 자동으로 이어받음)",
                key="direct_start_num",
            )

        if save_sel_d == "📁 새 폴더 (오늘 날짜)":
            td_d       = datetime.datetime.now().strftime("%Y-%m-%d")
            save_dir_d = POSTS_DIR / td_d / "direct_upload"
        else:
            pidx_d     = save_opts_d.index(save_sel_d) - 1
            save_dir_d = posts_d[pidx_d]["dir"]

        # 기존 이미지 번호 자동 감지
        existing_d = sorted(
            [int(f.stem) for f in save_dir_d.iterdir()
             if save_dir_d.exists() and f.is_file()
             and f.stem.isdigit() and f.suffix.lower() in (".jpg", ".png", ".jpeg", ".webp", ".gif")],
        ) if save_dir_d.exists() else []
        auto_next = max(existing_d, default=0) + 1
        if auto_next > start_num_d:
            st.caption(f"ℹ️ 폴더에 이미 {len(existing_d)}장 있음 → **{auto_next}번**부터 저장됩니다.")
            effective_start = auto_next
        else:
            effective_start = int(start_num_d)

        # ── 다중 파일 업로더 (드래그&드롭 지원) ──
        uploaded_files = st.file_uploader(
            "이미지 파일 선택 (여러 개 가능 · 드래그&드롭 지원)",
            type=["jpg", "jpeg", "png", "webp", "gif"],
            accept_multiple_files=True,
            key="direct_multi_uploader",
        )

        if uploaded_files:
            st.markdown(f"**선택된 파일 {len(uploaded_files)}장** — 아래에서 확인 후 저장 버튼을 누르세요.")

            # ── 미리보기 그리드 ──
            PREV_COLS = 5
            for row_s in range(0, len(uploaded_files), PREV_COLS):
                row_files = uploaded_files[row_s : row_s + PREV_COLS]
                cols_p    = st.columns(PREV_COLS)
                for j, uf in enumerate(row_files):
                    with cols_p[j]:
                        try:
                            st.image(uf, use_container_width=True)
                        except Exception:
                            st.write("⚠")
                        target_num = effective_start + row_s + j
                        st.caption(f"{uf.name}\n→ **{target_num}.{uf.name.rsplit('.',1)[-1].lower()}**")

            st.divider()

            col_save_d, col_info_d = st.columns([1, 2])
            with col_info_d:
                st.info(
                    f"📁 저장 위치: `{save_dir_d}`  \n"
                    f"📷 {len(uploaded_files)}장 → **{effective_start}** ~ **{effective_start + len(uploaded_files) - 1}** 번으로 저장"
                )
            with col_save_d:
                if st.button(
                    f"💾 {len(uploaded_files)}장 저장",
                    type="primary",
                    use_container_width=True,
                    key="direct_save_btn",
                ):
                    save_dir_d.mkdir(parents=True, exist_ok=True)
                    saved_d, failed_d = [], []
                    prog_d = st.progress(0)

                    for idx_d, uf in enumerate(uploaded_files):
                        ext_d    = uf.name.rsplit(".", 1)[-1].lower()
                        fname_d  = f"{effective_start + idx_d}.{ext_d}"
                        dest_d   = save_dir_d / fname_d
                        try:
                            dest_d.write_bytes(uf.getvalue())
                            saved_d.append(fname_d)
                        except Exception as e_d:
                            failed_d.append(f"{uf.name} ({e_d})")
                        prog_d.progress((idx_d + 1) / len(uploaded_files))

                    if saved_d:
                        st.success(
                            f"✅ **{len(saved_d)}장** 저장 완료!  \n"
                            f"📁 `{save_dir_d}`  \n"
                            f"파일: {', '.join(saved_d[:8])}{'...' if len(saved_d) > 8 else ''}"
                        )
                        # image_order.txt 갱신
                        all_imgs_d = sorted(
                            [f.name for f in save_dir_d.iterdir()
                             if f.is_file() and f.suffix.lower() in (".jpg", ".png", ".jpeg", ".webp", ".gif")],
                            key=lambda n: int(n.rsplit(".", 1)[0]) if n.rsplit(".", 1)[0].isdigit() else 999,
                        )
                        (save_dir_d / "image_order.txt").write_text(
                            "\n".join(all_imgs_d), encoding="utf-8"
                        )
                    if failed_d:
                        st.error(f"❌ 실패: {', '.join(failed_d)}")

        else:
            # 업로드 전 — 현재 폴더 상황 표시
            if save_dir_d.exists() and existing_d:
                st.caption(f"현재 폴더에 이미지 {len(existing_d)}장 있음 ({existing_d[0]}번 ~ {existing_d[-1]}번)")
            else:
                st.caption("아직 이미지가 없습니다. 위 업로드 영역에 파일을 끌어다 놓거나 클릭해서 선택하세요.")


# ─────────────────────────────────────────
# Tab 3: 포스트 관리
# ─────────────────────────────────────────
with tab_posts:
    # ── 카드뉴스 ZIP 자동 스캔 ──
    with st.expander("📦 카드뉴스 ZIP 가져오기 — 폴더 자동 스캔", expanded=False):
        try:
            from publish import CARDNEWS_DIR, collect_candidates

            st.caption(f"스캔 폴더: `{CARDNEWS_DIR}`")

            if st.button("🔄 다시 스캔", key="rescan_zip_btn"):
                st.rerun()

            _cands = [c for c in collect_candidates() if c["kind"] == "zip"]
            if not _cands:
                st.info("아직 임포트하지 않은 카드뉴스 ZIP이 없습니다. (이미 등록된 건 아래 목록에 있습니다)")
            else:
                _labels = [
                    f"[{c['date'] or '날짜없음'}]  {c['title'][:50]}  ·  이미지 {c['images']}장"
                    for c in _cands
                ]
                _pick = st.selectbox(
                    "가져올 ZIP 선택 (최신순)",
                    range(len(_cands)),
                    format_func=lambda i: _labels[i],
                    key="zip_scan_pick",
                )
                if st.button("📥 가져오기", type="primary", use_container_width=True,
                             key="zip_scan_import_btn"):
                    try:
                        from zip_importer import import_cardnews_zip

                        with st.spinner("ZIP 분석 및 변환 중..."):
                            dest = import_cardnews_zip(_cands[_pick]["path"], posts_dir=POSTS_DIR)

                        n_imgs  = len(get_images(dest))
                        n_paras = len([
                            p for p in (dest / "content.txt").read_text(encoding="utf-8").split("\n\n")
                            if p.strip()
                        ]) - 1
                        _tags_p = dest / "tags.txt"
                        _tag_note = (
                            f" · 태그 {len(_tags_p.read_text(encoding='utf-8').splitlines())}개"
                            if _tags_p.exists() else ""
                        )
                        st.success(
                            f"✅ 가져오기 완료 — `{dest.name}`  \n"
                            f"문단 {n_paras}개 · 이미지 {n_imgs}장{_tag_note}  \n"
                            "아래 목록에서 선택해 업로드하세요."
                        )
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ 가져오기 실패: {e}")
        except Exception as e:
            st.warning(f"ZIP 스캔을 사용할 수 없습니다: {e}")

        st.divider()
        st.caption("스캔 폴더 밖의 ZIP은 아래에서 직접 올리세요.")
        zip_file = st.file_uploader(
            "ZIP 파일 직접 선택", type=["zip"], key="cardnews_zip_uploader"
        )
        if zip_file is not None and st.button(
            "📥 업로드한 ZIP 임포트", use_container_width=True, key="zip_import_btn"
        ):
            tmp_zip = BASE_DIR / f"_import_{zip_file.name}"
            try:
                tmp_zip.write_bytes(zip_file.getvalue())
                from zip_importer import import_cardnews_zip

                with st.spinner("ZIP 분석 및 변환 중..."):
                    dest = import_cardnews_zip(tmp_zip, posts_dir=POSTS_DIR)
                st.success(f"✅ 임포트 완료 — `{dest.name}`")
                st.rerun()
            except Exception as e:
                st.error(f"❌ 임포트 실패: {e}")
            finally:
                tmp_zip.unlink(missing_ok=True)

    # ── CTA 프리셋 관리 ──
    with st.expander("📣 CTA 관리 — 글 끝에 붙일 블록 만들기", expanded=False):
        from cta_presets import load_presets, save_presets, summary as cta_summary

        st.caption(
            "문구·링크·이미지·지도를 조합해 저장해두면, 발행할 때 그때그때 골라 쓸 수 있습니다. "
            "필요한 것만 채우고 나머지는 비워두세요."
        )

        _cta_list = load_presets()

        if _cta_list:
            st.markdown("**저장된 CTA**")
            for _i, _p in enumerate(_cta_list):
                _c1, _c2 = st.columns([5, 1])
                with _c1:
                    st.markdown(f"**{_p['name']}** — {cta_summary(_p)}")
                with _c2:
                    if st.button("삭제", key=f"cta_del_{_i}", use_container_width=True):
                        _cta_list.pop(_i)
                        save_presets(_cta_list)
                        st.rerun()
            st.divider()

        st.markdown("**새 CTA 추가 / 수정**")
        _edit_target = st.selectbox(
            "편집할 CTA",
            ["(새로 만들기)"] + [p["name"] for p in _cta_list],
            key="cta_edit_target",
        )
        _base = (next((p for p in _cta_list if p["name"] == _edit_target), None)
                 if _edit_target != "(새로 만들기)" else None) or {
            "name": "", "text": "", "link": "", "image": "", "map": ""
        }

        with st.form("cta_form"):
            _n = st.text_input("이름 *", value=_base["name"],
                               placeholder="예: 상담문의 기본 / 옥정중앙역 현장")
            _t = st.text_area("문구", value=_base["text"], height=90,
                              placeholder="더 자세한 현장 브리핑이 궁금하시다면 편하게 문의주세요.")
            _l = st.text_input("링크", value=_base["link"],
                               placeholder="https://open.kakao.com/... (상담 신청 페이지 등)")
            _im = st.text_input("이미지 파일 경로", value=_base["image"],
                                placeholder=r"D:\...\배너.jpg")
            _mp = st.text_input("지도 주소", value=_base["map"],
                                placeholder="경기 양주시 옥정동 ... (현장/홍보관 주소)")
            _saved = st.form_submit_button("💾 저장", type="primary", use_container_width=True)

        if _saved:
            if not _n.strip():
                st.error("이름은 반드시 입력해주세요.")
            else:
                _new = {"name": _n.strip(), "text": _t, "link": _l.strip(),
                        "image": _im.strip(), "map": _mp.strip()}
                _others = [p for p in _cta_list if p["name"] != _n.strip()]
                save_presets(_others + [_new])
                st.success(f"✅ '{_n.strip()}' 저장 완료")
                st.rerun()

        st.info(
            "💡 지도는 네이버 에디터 화면 구조에 따라 자동 삽입이 실패할 수 있습니다. "
            "그럴 땐 주소를 안내 메시지로 알려드리니 발행 화면에서 직접 추가해주세요."
        )

    st.subheader("생성된 포스트 목록")

    posts = get_all_posts()

    if not posts:
        st.info("아직 생성된 포스트가 없습니다. '원고 에디터' 탭에서 첫 원고를 만들어보세요.")
    else:
        # 발행 이력이 있는 글은 목록에서 바로 보이게 표시 (중복 발행 방지)
        try:
            from publish import _published_titles
            _done_titles = _published_titles()
        except Exception:
            _done_titles = set()

        def _post_first_line(p):
            try:
                txt = p["content_path"].read_text(encoding="utf-8").strip()
                return txt.split("\n\n")[0].strip()
            except Exception:
                return ""

        labels = [
            f"[{p['date']}]  {p['title']}"
            + ("   ✅ 이미 발행함" if _post_first_line(p) in _done_titles else "")
            for p in posts
        ]
        sel_idx = st.selectbox("포스트 선택", range(len(posts)), format_func=lambda i: labels[i])

        selected = posts[sel_idx]
        post_dir = selected["dir"]
        images   = get_images(post_dir)

        # ── 상단: 메타 정보 + 액션 버튼 ──
        meta_col, btn_col = st.columns([3, 1])
        with meta_col:
            st.markdown(f"📅 **{selected['date']}** &nbsp;|&nbsp; 🖼️ **{len(images)}장** &nbsp;|&nbsp; 📁 `{post_dir.name}`")
            if _post_first_line(selected) in _done_titles:
                st.warning("⚠️ 이 글은 이미 발행 이력이 있습니다 — 중복 발행에 주의하세요.")
        with btn_col:
            if IS_CLOUD:
                # 클라우드: 네이버 봇 차단 → 버튼 비활성화
                st.button("📤 로컬 PC 전용", disabled=True,
                          use_container_width=True, key="mgmt_upload_disabled")
                st.caption("원고 에디터 탭의 **대기열 등록** 을 이용하세요")

        # ── 발행 옵션 (CTA · 카테고리 · 공개설정) ──
        if not IS_CLOUD:
            from cta_presets import load_presets, summary as cta_summary

            _presets = load_presets()
            _opt1, _opt2, _opt3 = st.columns(3)

            with _opt1:
                _cta_names = ["(사용 안 함)"] + [p["name"] for p in _presets]
                _cta_pick = st.selectbox(
                    "📣 CTA 블록", _cta_names, key=f"cta_pick_{sel_idx}",
                    help="글 끝에 붙일 CTA를 그때그때 고르세요. 아래 'CTA 관리'에서 추가할 수 있습니다.",
                )
                if _cta_pick != "(사용 안 함)":
                    _sel_cta = next((p for p in _presets if p["name"] == _cta_pick), None)
                    if _sel_cta:
                        st.caption(f"구성: {cta_summary(_sel_cta)}")

            with _opt2:
                _category = st.text_input(
                    "📁 카테고리", key=f"cat_{sel_idx}",
                    placeholder="비우면 기본값",
                    help="네이버 블로그에 있는 카테고리 이름을 정확히 입력하세요.",
                )

            with _opt3:
                _visibility = st.selectbox(
                    "🔓 공개 설정",
                    ["(기본값)", "전체공개", "이웃공개", "서로이웃공개", "비공개"],
                    key=f"vis_{sel_idx}",
                )

            if st.button("📤 네이버 업로드", type="primary",
                         use_container_width=True, key="mgmt_upload"):
                st.info("브라우저가 자동으로 열립니다. 입력이 끝나면 직접 [발행]을 눌러주세요.")
                try:
                    from step2_upload import upload_to_naver_blog

                    _cta_obj = (next((p for p in _presets if p["name"] == _cta_pick), None)
                                if _cta_pick != "(사용 안 함)" else None)
                    upload_to_naver_blog(
                        folder_path=str(post_dir),
                        headless=False,
                        auto_publish=False,
                        cta=_cta_obj,
                        category=_category.strip(),
                        visibility="" if _visibility == "(기본값)" else _visibility,
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
    # 열 개수를 항목 수에 맞춰 만듭니다 (항목이 늘어도 IndexError 나지 않도록)
    cols = st.columns(max(1, len(env)))
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

    # ── 발행 이력 ──
    st.divider()
    st.subheader("🗂️ 발행 이력")

    _log_path = POSTS_DIR / "publish_log.jsonl"
    if not _log_path.exists():
        st.info("아직 발행 이력이 없습니다. 네이버 업로드를 실행하면 여기에 기록됩니다.")
    else:
        import json as _json

        _records = []
        for _line in _log_path.read_text(encoding="utf-8").splitlines():
            if _line.strip():
                try:
                    _records.append(_json.loads(_line))
                except Exception:
                    continue
        _records.reverse()   # 최신순

        if not _records:
            st.info("발행 이력이 비어 있습니다.")
        else:
            _titles = [r.get("title", "") for r in _records]
            _dupes = {t for t in _titles if _titles.count(t) > 1}
            if _dupes:
                st.warning(
                    f"⚠️ 같은 제목으로 두 번 이상 업로드된 글이 {len(_dupes)}건 있습니다 — "
                    "중복 발행 여부를 확인해보세요."
                )

            import pandas as _pd

            st.dataframe(
                _pd.DataFrame([
                    {
                        "일시":   r.get("at", "").replace("T", " "),
                        "제목":   r.get("title", "")[:45],
                        "문단":   r.get("paragraphs", 0),
                        "이미지": r.get("images", 0),
                        "태그":   len(r.get("tags", [])),
                        "자동발행": "O" if r.get("auto_published") else "-",
                    }
                    for r in _records[:50]
                ]),
                use_container_width=True,
                hide_index=True,
            )
            st.caption(f"최근 {min(len(_records), 50)}건 표시 · 전체 {len(_records)}건")

    # ── Supabase 발행 대기열 현황 ──
    st.divider()
    st.subheader("📋 Supabase 발행 대기열")

    gs_ok = bool(get_secret("SUPABASE_URL") and get_secret("SUPABASE_SERVICE_ROLE_KEY"))
    if not gs_ok:
        st.warning(
            "Supabase 미연결 — Streamlit Cloud Secrets에 아래 두 키를 추가하세요:  \n"
            "`SUPABASE_URL` · `SUPABASE_SERVICE_ROLE_KEY`"
        )
    else:
        _ref_col, _csv_col = st.columns([1, 1])
        with _ref_col:
            if st.button("🔄 대기열 새로고침", key="refresh_queue", use_container_width=True):
                st.rerun()

        with st.spinner("Supabase 조회 중..."):
            rows = _supabase_all_rows()

        # ── 멈춘 작업 복구 · 오래된 행 정리 ──
        from home_status import find_stuck_rows, STUCK_HOURS

        _stuck = find_stuck_rows(rows)
        _finished = [r for r in rows if r.get("status") in ("done", "error")]
        _sb_url = get_secret("SUPABASE_URL")
        _sb_key = get_secret("SUPABASE_SERVICE_ROLE_KEY")

        if _stuck:
            st.warning(
                f"⚠️ **멈춘 작업 {len(_stuck)}건** — {STUCK_HOURS}시간 넘게 '처리 중' 상태입니다.  \n"
                "업로드 도중 브라우저가 닫히면 이 상태로 남아 다시 처리되지 않습니다."
            )
            for _s in _stuck:
                st.caption(f"· {_s.get('title', '')[:56]}")
            _rs1, _rs2 = st.columns(2)
            with _rs1:
                if st.button("↩️ 대기 상태로 되돌리기", type="primary",
                             use_container_width=True, key="reset_stuck"):
                    from supabase_db import reset_stuck_rows
                    _n = reset_stuck_rows(_sb_url, _sb_key, [r.get("id") for r in _stuck])
                    st.success(f"✅ {_n}건을 대기 상태로 되돌렸습니다.")
                    st.rerun()
            with _rs2:
                if st.button("🗑️ 멈춘 작업 삭제", use_container_width=True, key="del_stuck"):
                    from supabase_db import delete_row
                    _n = sum(1 for r in _stuck if delete_row(_sb_url, _sb_key, r.get("id")))
                    st.success(f"✅ {_n}건 삭제했습니다.")
                    st.rerun()

        if _finished:
            with st.expander(f"🧹 완료·오류 항목 정리 ({len(_finished)}건)", expanded=False):
                st.caption(
                    "발행이 끝났거나 오류로 남은 행을 지웁니다. "
                    "지워도 로컬 포스트 폴더와 발행 이력은 그대로 남습니다."
                )
                if st.button("🗑️ 완료·오류 항목 모두 삭제",
                             use_container_width=True, key="clean_finished"):
                    from supabase_db import delete_rows_by_status
                    _n = delete_rows_by_status(_sb_url, _sb_key, ["done", "error"])
                    st.success(f"✅ {_n}건 삭제했습니다.")
                    st.rerun()

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
