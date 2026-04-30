import streamlit as st
import os
import sys
import re
import subprocess
import datetime
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


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

# ── 세션 초기화 ──
for k, v in {
    "generated_content": "",
    "last_post_dir": None,
    "generation_logs": [],
    "generation_done": False,
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
    imgs = [f for f in folder.iterdir() if f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")]
    try:
        imgs.sort(key=lambda x: int(x.stem))
    except Exception:
        imgs.sort()
    return imgs

def check_env():
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env")
    return {
        "Gemini API":    bool(os.getenv("GEMINI_API_KEY")),
        "Leonardo API":  bool(os.getenv("LEONARDO_API_KEY")),
        "Naver ID":      bool(os.getenv("NAVER_ID")),
        "Naver PW":      bool(os.getenv("NAVER_PASSWORD")),
    }

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

# ══════════════════════════════════════════
# 메인 — 탭
# ══════════════════════════════════════════
st.title("🏠 네이버 부동산 블로그 자동화")
tab_editor, tab_image, tab_posts, tab_status = st.tabs(["📝 원고 에디터", "🎨 이미지 생성", "📂 포스트 관리", "📊 시스템 상태"])

# ─────────────────────────────────────────
# Tab 1: 원고 에디터
# ─────────────────────────────────────────
with tab_editor:

    # ── 생성 버튼 ──
    st.subheader("1  AI 원고 자동 생성")
    col_btn, col_hint = st.columns([1, 2])
    with col_btn:
        go = st.button("✨ 블로그 원고 자동 생성", type="primary", use_container_width=True)
    with col_hint:
        st.info(f"모드: **{mode}**   |   어조: **{persona}**   |   약 2~5분 소요")

    if go:
        if choice in ("2", "3") and not input_data.strip():
            st.warning("키워드 또는 주제를 입력해주세요.")
        else:
            st.session_state["generation_done"] = False
            st.session_state["generation_logs"] = []
            st.session_state["last_post_dir"]   = None

            log_box  = st.empty()
            logs     = []
            done_dir = None

            extra_full = extra.strip() if extra.strip() else None

            for log_line, result_dir in run_generation(choice, input_data.strip(), persona, extra_full):
                if log_line is not None:
                    logs.append(log_line)
                    log_box.code("\n".join(logs[-35:]), language=None)
                else:
                    done_dir = result_dir

            log_box.code("\n".join(logs), language=None)

            if done_dir:
                st.session_state["last_post_dir"]   = done_dir
                st.session_state["generation_done"] = True
                st.session_state["generation_logs"] = logs

                # content.txt 로드
                content_file = Path(done_dir) / "content.txt"
                if content_file.exists():
                    raw = content_file.read_text(encoding="utf-8")
                    if cta_text.strip() and cta_text.strip() not in raw:
                        raw = raw + "\n\n" + cta_text.strip()
                    st.session_state["generated_content"] = raw

                st.success(f"✅ 완료!  저장 위치: {done_dir}")
                st.rerun()
            else:
                st.error("생성 중 오류가 발생했습니다. 위 로그를 확인해주세요.")

    # ── 생성 결과 ──
    if st.session_state["generation_done"] and st.session_state["last_post_dir"]:
        post_dir = Path(st.session_state["last_post_dir"])

        # 실시간 미리보기
        st.subheader("실시간 미리보기")
        align_css = {"좌측": "left", "중앙": "center", "양쪽": "justify"}[text_align]
        preview_html = f"""
<div style="background:#fff;color:#111;padding:28px 36px;border-radius:12px;
            box-shadow:0 2px 12px rgba(0,0,0,.12);font-size:{content_font_size}px;
            line-height:1.85;white-space:pre-wrap;text-align:{align_css};
            font-family:'Malgun Gothic',sans-serif;max-height:420px;overflow-y:auto;">
{st.session_state["generated_content"]}
</div>"""
        st.markdown(preview_html, unsafe_allow_html=True)

        # 원고 에디터
        st.subheader("2  에디터 도구")
        edited = st.text_area(
            "원고 수정 (수정 후 저장 버튼)",
            value=st.session_state["generated_content"],
            height=380,
            key="editor_area",
        )

        col_save, col_break, col_cta = st.columns(3)
        with col_save:
            if st.button("💾 수정사항 저장", use_container_width=True):
                (post_dir / "content.txt").write_text(edited, encoding="utf-8")
                st.session_state["generated_content"] = edited
                st.success("저장됐습니다.")

        with col_break:
            if st.button("↩ 마침표 기준 줄바꿈", use_container_width=True):
                result = re.sub(r"(?<![0-9])\.(\s|$)", ".\n\n", edited)
                st.session_state["generated_content"] = result
                st.rerun()

        with col_cta:
            if st.button("📌 CTA 문구 삽입", use_container_width=True):
                if cta_text.strip() not in edited:
                    st.session_state["generated_content"] = edited + "\n\n" + cta_text.strip()
                    st.rerun()

        # 이미지 갤러리
        images = get_images(post_dir)
        if images:
            st.subheader(f"3  수집된 이미지 ({len(images)}장)")
            cols = st.columns(5)
            for i, img_path in enumerate(images):
                with cols[i % 5]:
                    try:
                        st.image(str(img_path), caption=img_path.name, use_container_width=True)
                    except Exception:
                        st.caption(f"⚠ {img_path.name}")

        # 업로드
        st.divider()
        st.subheader("4  네이버 블로그 업로드")
        col_up, col_tip = st.columns([1, 2])
        with col_up:
            if st.button("📤 네이버 블로그에 업로드", type="primary", use_container_width=True):
                st.info("브라우저가 자동으로 열립니다. 최종 확인 후 [발행] 버튼을 직접 눌러주세요.")
                try:
                    from step2_upload import upload_to_naver_blog
                    upload_to_naver_blog(folder_path=str(post_dir))
                except Exception as e:
                    st.error(f"업로드 오류: {e}")
        with col_tip:
            st.caption(f"업로드 폴더: `{post_dir}`")

# ─────────────────────────────────────────
# Tab 2: 이미지 생성
# ─────────────────────────────────────────
with tab_image:
    from dotenv import load_dotenv as _ld; _ld()
    leo_key = os.getenv("LEONARDO_API_KEY", "")

    if not leo_key:
        st.error("❌ .env 파일에 LEONARDO_API_KEY가 없습니다.")
    else:
        gen_mode = st.radio(
            "생성 방식",
            ["📄 원고 프롬프트 기반 생성", "🖼️ 업로드 이미지 기반 생성"],
            horizontal=True,
        )
        st.divider()

        # ── 모드 1: 원고 프롬프트 기반 ──
        if gen_mode == "📄 원고 프롬프트 기반 생성":
            st.markdown("생성된 포스트의 프롬프트를 선택·편집하여 이미지를 (재)생성합니다.")

            posts = get_all_posts()
            if not posts:
                st.info("먼저 '원고 에디터' 탭에서 포스트를 생성해주세요.")
            else:
                labels  = [f"[{p['date']}]  {p['title']}" for p in posts]
                sel_idx = st.selectbox("포스트 선택", range(len(posts)),
                                       format_func=lambda i: labels[i], key="img_post_sel")
                post_dir     = posts[sel_idx]["dir"]
                prompts_file = post_dir / "prompts.txt"

                if not prompts_file.exists():
                    st.warning("이 포스트에 prompts.txt 파일이 없습니다.")
                else:
                    raw_prompts  = prompts_file.read_text(encoding="utf-8")
                    prompt_lines = [l.strip() for l in raw_prompts.splitlines() if l.strip()]

                    st.write(f"**총 {len(prompt_lines)}개 프롬프트** — 생성할 항목 선택 후 버튼 클릭")

                    selected = []
                    for idx, line in enumerate(prompt_lines):
                        num_match = re.match(r"^(\d+)[\.\)]\s*", line)
                        slot_num  = int(num_match.group(1)) if num_match else (idx + 1)
                        clean     = re.sub(r"^\d+[\.\)]\s*", "", line).strip()

                        existing = post_dir / f"{slot_num}.jpg"
                        badge    = "✅" if existing.exists() else "🔲"

                        col_chk, col_badge, col_txt = st.columns([1, 1, 14])
                        with col_chk:
                            checked = st.checkbox("", value=not existing.exists(),
                                                  key=f"chk_{sel_idx}_{idx}")
                        with col_badge:
                            st.write(badge)
                        with col_txt:
                            edited = st.text_input(
                                f"slot_{slot_num}",
                                value=clean,
                                key=f"prompt_{sel_idx}_{idx}",
                                label_visibility="collapsed",
                            )
                        if checked:
                            selected.append((slot_num, edited))

                    overwrite = st.checkbox("✅ 기존 이미지 덮어쓰기", value=False)

                    col_btn, col_info = st.columns([1, 2])
                    with col_btn:
                        gen_btn = st.button(
                            f"🚀  {len(selected)}개 이미지 생성",
                            type="primary",
                            disabled=(len(selected) == 0),
                            use_container_width=True,
                        )
                    with col_info:
                        st.info(f"이미지 1장당 약 30~60초 소요 · 총 {len(selected)}장")

                    if gen_btn and selected:
                        from leonardo_generator import (
                            generate_text_to_image, poll_until_complete, download_image
                        )

                        progress_bar = st.progress(0)
                        status_txt   = st.empty()
                        gallery      = st.empty()
                        done_paths   = []

                        for count, (slot, prompt) in enumerate(selected):
                            save_path = post_dir / f"{slot}.jpg"

                            if save_path.exists() and not overwrite:
                                status_txt.info(f"[{count+1}/{len(selected)}] {slot}.jpg 이미 존재 — 건너뜀")
                                done_paths.append(save_path)
                                progress_bar.progress((count + 1) / len(selected))
                                continue

                            status_txt.write(f"⏳ [{count+1}/{len(selected)}] 슬롯 {slot} 생성 요청 중...")

                            try:
                                gen_id = generate_text_to_image(prompt, leo_key)

                                tick_txt = st.empty()
                                def on_tick(elapsed, _t=tick_txt, _c=count, _n=len(selected), _s=slot):
                                    _t.caption(f"  대기 중... {elapsed}초 경과 (슬롯 {_s})")

                                urls = poll_until_complete(gen_id, leo_key, on_tick=on_tick)
                                tick_txt.empty()

                                if urls and download_image(urls[0], str(save_path)):
                                    done_paths.append(save_path)
                                    status_txt.success(f"✅ [{count+1}/{len(selected)}] {slot}.jpg 저장 완료")
                                else:
                                    status_txt.warning(f"⚠ [{count+1}/{len(selected)}] 슬롯 {slot} 생성 실패")

                            except Exception as e:
                                status_txt.error(f"[{count+1}] 오류: {e}")

                            progress_bar.progress((count + 1) / len(selected))

                        # 완료 후 갤러리 표시
                        status_txt.success(f"🎉 완료! {len(done_paths)}장 저장됨 → {post_dir}")
                        if done_paths:
                            cols = st.columns(5)
                            for i, p in enumerate(done_paths):
                                with cols[i % 5]:
                                    st.image(str(p), caption=p.name, use_container_width=True)

        # ── 모드 2: 업로드 이미지 기반 ──
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
                    "원본 이미지 영향도",
                    min_value=0.1, max_value=0.9, value=0.45, step=0.05,
                    help="낮을수록 프롬프트 중심, 높을수록 원본 이미지 유지",
                )
                st.caption(f"{'← 프롬프트 중심':<25} {'원본 유지 →':>20}")

                # 저장 위치 선택
                posts = get_all_posts()
                save_options = ["📁 새 폴더 (오늘 날짜)"] + [f"[{p['date']}] {p['title']}" for p in posts]
                save_sel = st.selectbox("저장할 포스트 폴더", save_options)

                if save_sel == "📁 새 폴더 (오늘 날짜)":
                    today = datetime.datetime.now().strftime("%Y-%m-%d")
                    save_dir = POSTS_DIR / today / "generated_images"
                else:
                    pidx = save_options.index(save_sel) - 1
                    save_dir = posts[pidx]["dir"]

                num_gen = st.number_input("생성할 이미지 수", min_value=1, max_value=4, value=1)

            # 생성 버튼
            can_generate = prompt_input.strip() != ""
            if not can_generate:
                st.warning("이미지 설명(프롬프트)을 입력해주세요.")

            if st.button(
                "🎨 이미지 생성 시작",
                type="primary",
                disabled=not can_generate,
                use_container_width=False,
            ):
                from leonardo_generator import (
                    upload_init_image,
                    generate_text_to_image,
                    generate_image_to_image,
                    poll_until_complete,
                    download_image,
                )

                save_dir.mkdir(parents=True, exist_ok=True)
                status_txt = st.empty()

                try:
                    # 이미지 업로드 (있는 경우)
                    init_image_id = None
                    if uploaded:
                        status_txt.write("☁️ 참조 이미지 Leonardo에 업로드 중...")
                        ext = uploaded.name.rsplit(".", 1)[-1].lower()
                        init_image_id = upload_init_image(uploaded.getvalue(), ext, leo_key)
                        status_txt.write("✅ 업로드 완료. 이미지 생성 요청 중...")

                    # 생성 요청
                    if init_image_id:
                        gen_id = generate_image_to_image(
                            prompt_input.strip(), init_image_id, strength, leo_key,
                            num_images=int(num_gen),
                        )
                    else:
                        gen_id = generate_text_to_image(
                            prompt_input.strip(), leo_key, num_images=int(num_gen),
                        )

                    # 폴링
                    tick_txt = st.empty()
                    def on_tick_up(elapsed, _t=tick_txt):
                        _t.caption(f"생성 중... {elapsed}초 경과")

                    status_txt.write("⏳ Leonardo가 이미지를 그리는 중...")
                    urls = poll_until_complete(gen_id, leo_key, on_tick=on_tick_up)
                    tick_txt.empty()

                    if urls:
                        ts   = datetime.datetime.now().strftime("%H%M%S")
                        cols = st.columns(len(urls))
                        for i, url in enumerate(urls):
                            fname     = f"leo_{ts}_{i+1}.jpg"
                            save_path = save_dir / fname
                            download_image(url, str(save_path))
                            with cols[i]:
                                st.image(str(save_path), caption=fname, use_container_width=True)

                        status_txt.success(f"🎉 {len(urls)}장 생성 완료! 저장 위치: {save_dir}")
                    else:
                        status_txt.error("이미지 생성에 실패했습니다. 프롬프트나 API 키를 확인해주세요.")

                except Exception as e:
                    status_txt.error(f"오류 발생: {e}")


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

        col_info, col_preview = st.columns([1, 3])

        with col_info:
            st.metric("날짜", selected["date"])
            images = get_images(post_dir)
            st.metric("이미지", f"{len(images)}장")
            st.write("**제목**")
            st.write(selected["title"])

            if st.button("📤 이 포스트 업로드", type="primary", use_container_width=True):
                st.info("브라우저가 자동으로 열립니다.")
                try:
                    from step2_upload import upload_to_naver_blog
                    upload_to_naver_blog(folder_path=str(post_dir))
                except Exception as e:
                    st.error(f"업로드 오류: {e}")

        with col_preview:
            content_path = selected["content_path"]
            content = content_path.read_text(encoding="utf-8")
            st.text_area("원고 내용", value=content, height=350, disabled=True)

        # 이미지 갤러리
        if images:
            st.write("---")
            st.write(f"**이미지 갤러리 ({len(images)}장)**")
            cols = st.columns(5)
            for i, img_path in enumerate(images):
                with cols[i % 5]:
                    try:
                        st.image(str(img_path), caption=img_path.name, use_container_width=True)
                    except Exception:
                        st.caption(f"⚠ {img_path.name}")

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
    col_a, col_b, col_c = st.columns(3)
    col_a.metric("전체 포스트", f"{len(posts)}개")
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    today_cnt = sum(1 for p in posts if p["date"] == today)
    col_b.metric("오늘 생성", f"{today_cnt}개")
    total_imgs = sum(len(get_images(p["dir"])) for p in posts)
    col_c.metric("전체 수집 이미지", f"{total_imgs}장")
