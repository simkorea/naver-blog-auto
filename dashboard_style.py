"""
dashboard_style.py — 대시보드 전역 CSS

web_dashboard.py 에 인라인으로 있던 스타일 블록을 분리했습니다.
색상·타이포·컴포넌트 스타일만 담고 로직은 없습니다.

주의: 본문 영역 배경을 흰색으로 칠하므로, .streamlit/config.toml 의
theme.base 는 반드시 "light" 여야 합니다. "dark" 로 두면 기본 글자색이
거의 흰색이라 흰 배경 위에서 글자가 보이지 않습니다.
"""
import streamlit as st

CSS = """\n<style>
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

/* ─── 2. 앱 배경 & 여백 ─── */
div[data-testid="stAppViewContainer"] {
  background: #f0f2f8 !important;
}
div[data-testid="block-container"] {
  padding: 2.75rem 2.5rem 3.5rem !important;
  max-width: 1440px !important;
}
/* 페이지 타이틀 아래 여백 */
div[data-testid="block-container"] h1:first-of-type {
  margin-bottom: 1.25rem !important;
}
/* 안내 박스(info/warning) 아래 여백 */
div[data-testid="stAlert"] {
  margin-bottom: 1.5rem !important;
}

/* ─── 3. 사이드바 — 다크 네이비 ─── */
section[data-testid="stSidebar"] {
  background: linear-gradient(180deg, #0f172a 0%, #1e293b 100%) !important;
  border-right: 1px solid rgba(255,255,255,0.06) !important;
}
section[data-testid="stSidebar"] > div:first-child {
  padding-top: 1.5rem !important;
}

/* 사이드바 기본 텍스트 — p는 서브텍스트, h는 섹션 타이틀 */
section[data-testid="stSidebar"] p             { color: #94a3b8 !important; }
section[data-testid="stSidebar"] h1,
section[data-testid="stSidebar"] h2,
section[data-testid="stSidebar"] h3            { color: #F8F9FA !important; }
section[data-testid="stSidebar"] hr            { border-color: rgba(255,255,255,0.1) !important; }

/* 사이드바 Expander */
section[data-testid="stSidebar"] div[data-testid="stExpander"] {
  background: transparent !important;
  border: 1px solid rgba(255,255,255,0.1) !important;
  box-shadow: none !important;
  border-radius: 8px !important;
}
section[data-testid="stSidebar"] div[data-testid="stExpander"] summary {
  color: #F8F9FA !important;
  padding: 0.6rem 0.9rem !important;
  background: transparent !important;
}
section[data-testid="stSidebar"] div[data-testid="stExpander"] summary:hover {
  background: rgba(255,255,255,0.06) !important;
}
section[data-testid="stSidebar"] div[data-testid="stExpander"] p {
  color: #94a3b8 !important;
}

/* ─── 3-b. 사이드바 입력 위젯 — 가독성 수정 ─── */

/* ① 위젯 라벨 → 밝은 흰색 (#F8F9FA) */
section[data-testid="stSidebar"] div[data-testid="stTextInput"] > label,
section[data-testid="stSidebar"] div[data-testid="stTextArea"] > label,
section[data-testid="stSidebar"] div[data-testid="stSelectbox"] > label,
section[data-testid="stSidebar"] div[data-testid="stNumberInput"] > label,
section[data-testid="stSidebar"] div[data-testid="stSlider"] > label,
section[data-testid="stSidebar"] div[data-testid="stMultiSelect"] > label,
section[data-testid="stSidebar"] div[data-testid="stDateInput"] > label,
section[data-testid="stSidebar"] div[data-testid="stTimeInput"] > label {
  color: #F8F9FA !important;
  font-size: 0.82rem !important;
  font-weight: 600 !important;
  letter-spacing: 0.03em !important;
  text-transform: none !important;
}

/* ② 입력창 컨테이너 → 흰 배경 (가독성 최우선) */
section[data-testid="stSidebar"] div[data-testid="stTextInput"] > div > div,
section[data-testid="stSidebar"] div[data-testid="stTextArea"] > div > div,
section[data-testid="stSidebar"] div[data-testid="stNumberInput"] > div > div {
  background: #ffffff !important;
  border: 1.5px solid rgba(255,255,255,0.25) !important;
  border-radius: 8px !important;
  box-shadow: 0 2px 10px rgba(0,0,0,0.3) !important;
  transition: border-color 0.2s, box-shadow 0.2s !important;
}
section[data-testid="stSidebar"] div[data-testid="stTextInput"] > div > div:focus-within,
section[data-testid="stSidebar"] div[data-testid="stTextArea"] > div > div:focus-within,
section[data-testid="stSidebar"] div[data-testid="stNumberInput"] > div > div:focus-within {
  border-color: #7c3aed !important;
  box-shadow: 0 0 0 3px rgba(124,58,237,0.25) !important;
}

/* ③ 입력 텍스트 → 진한 흑회색 (#333333), 높은 명시도 셀렉터로 우선순위 확보 */
section[data-testid="stSidebar"] div[data-testid="stTextInput"] > div > div input,
section[data-testid="stSidebar"] div[data-testid="stTextArea"] > div > div textarea,
section[data-testid="stSidebar"] div[data-testid="stNumberInput"] > div > div input {
  color: #333333 !important;
  background: transparent !important;
  caret-color: #7c3aed !important;
}

/* ④ Placeholder → 중간 회색 (#888888) */
section[data-testid="stSidebar"] div[data-testid="stTextInput"] > div > div input::placeholder,
section[data-testid="stSidebar"] div[data-testid="stTextArea"] > div > div textarea::placeholder {
  color: #888888 !important;
}

/* ⑤ Selectbox → 흰 배경 + 진한 텍스트 */
section[data-testid="stSidebar"] div[data-baseweb="select"] > div:first-child {
  background: #ffffff !important;
  border: 1.5px solid rgba(255,255,255,0.25) !important;
  border-radius: 8px !important;
  box-shadow: 0 2px 10px rgba(0,0,0,0.25) !important;
}
section[data-testid="stSidebar"] div[data-baseweb="select"] span {
  color: #333333 !important;
}

/* ⑥ 라디오 버튼 */
section[data-testid="stSidebar"] div[data-testid="stRadio"] label {
  border-radius: 8px !important;
  padding: 0.45rem 0.75rem !important;
  transition: background 0.15s !important;
  color: #cbd5e1 !important;
}
section[data-testid="stSidebar"] div[data-testid="stRadio"] label:hover {
  background: rgba(255,255,255,0.08) !important;
  color: #F8F9FA !important;
}

/* ⑦ 체크박스 label */
section[data-testid="stSidebar"] div[data-testid="stCheckbox"] label {
  color: #cbd5e1 !important;
}
section[data-testid="stSidebar"] div[data-testid="stCheckbox"] label:hover {
  color: #F8F9FA !important;
}

/* ⑧ Caption */
section[data-testid="stSidebar"] div[data-testid="stCaptionContainer"] p,
section[data-testid="stSidebar"] small {
  color: #94a3b8 !important;
}

/* ⑧-1 본문 영역 기본 글자색 — 테마 기본값에 기대지 않고 직접 지정합니다.
   (배경을 흰색으로 덮어쓰기 때문에, 색을 지정하지 않은 글자가 흰 글씨로
    남으면 그대로 안 보이게 됩니다.) */
section.main div[data-testid="stCaptionContainer"] p,
div[data-testid="stAppViewContainer"] div[data-testid="stCaptionContainer"] p,
div[data-testid="stAppViewContainer"] small {
  color: #64748b !important;
}
div[data-testid="stAppViewContainer"] div[data-testid="stMarkdownContainer"] p,
div[data-testid="stAppViewContainer"] div[data-testid="stMarkdownContainer"] li,
div[data-testid="stAppViewContainer"] div[data-testid="stText"] {
  color: #1e293b;
}
/* 사이드바는 위 규칙보다 뒤에 와서 다시 밝은색을 되찾도록 */
section[data-testid="stSidebar"] div[data-testid="stMarkdownContainer"] p,
section[data-testid="stSidebar"] div[data-testid="stMarkdownContainer"] li {
  color: #e2e8f0 !important;
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
/* 메인 영역 input/textarea 텍스트 — 사이드바 제외 */
div[data-testid="stAppViewContainer"] div[data-testid="stTextInput"] input,
div[data-testid="stAppViewContainer"] div[data-testid="stTextArea"] textarea,
div[data-testid="stAppViewContainer"] div[data-testid="stNumberInput"] input {
  color: #1e293b !important;
  font-size: 0.9rem !important;
  background: transparent !important;
}
div[data-testid="stAppViewContainer"] div[data-testid="stTextInput"] input::placeholder,
div[data-testid="stAppViewContainer"] div[data-testid="stTextArea"] textarea::placeholder {
  color: #9ca3af !important;
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

/* ─── 8. Metric — 통합 카드 (구분선 포함) ─── */
/*
 * :has() 로 metric-container 를 직접 자식으로 가진
 * stHorizontalBlock 을 하나의 카드로 묶는다.
 * Chrome 105+, Firefox 121+, Safari 15.4+ 지원.
 */
div[data-testid="block-container"]
  div[data-testid="stHorizontalBlock"]:has(
    > div[data-testid="stColumn"] > div[data-testid="metric-container"]
  ) {
  background: #ffffff !important;
  border-radius: 16px !important;
  border: 1px solid #e2e8f0 !important;
  box-shadow: 0 4px 20px rgba(0,0,0,0.07) !important;
  padding: 0.25rem 0 !important;
  margin-bottom: 1.75rem !important;
  overflow: hidden !important;
}

/* 개별 metric-container: 카드 배경 제거, 우측 구분선 추가 */
div[data-testid="block-container"]
  div[data-testid="stHorizontalBlock"]:has(
    > div[data-testid="stColumn"] > div[data-testid="metric-container"]
  )
  div[data-testid="metric-container"] {
  background: transparent !important;
  border: none !important;
  border-right: 1px solid #e2e8f0 !important;
  border-radius: 0 !important;
  box-shadow: none !important;
  padding: 1.1rem 1.5rem !important;
}
/* 마지막 컬럼 구분선 제거 */
div[data-testid="block-container"]
  div[data-testid="stHorizontalBlock"]:has(
    > div[data-testid="stColumn"] > div[data-testid="metric-container"]
  )
  > div[data-testid="stColumn"]:last-child div[data-testid="metric-container"] {
  border-right: none !important;
}

div[data-testid="stMetricValue"] > div {
  font-size: 1.8rem !important;
  font-weight: 800 !important;
  color: #0f172a !important;
  letter-spacing: -0.02em !important;
}
div[data-testid="stMetricLabel"] > div {
  font-size: 0.75rem !important;
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
  margin-bottom: 1.5rem !important;
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
"""


def inject_css() -> None:
    """전역 스타일을 페이지에 주입합니다."""
    st.markdown(CSS, unsafe_allow_html=True)
