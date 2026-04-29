import os
import re
import time
import datetime
import requests
from PIL import Image, ImageDraw, ImageFont
import google.generativeai as genai
from dotenv import load_dotenv
from naver_news import get_top_real_estate_news, get_news_by_keyword
from image_fetcher import fetch_all_real_images

load_dotenv()

def read_expert_instruction(filepath="expert_instruction.md"):
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return "전문가 지침서가 없습니다."

def generate_blog_content(choice, input_data):
    """
    뉴스/주제를 기반으로 블로그 원고를 생성합니다.
    반환: (news_title, full_ai_text, news_url)
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY가 설정되지 않았습니다.")

    genai.configure(api_key=api_key)
    system_instruction = read_expert_instruction()

    news_url = None  # 실제 이미지 수집에 사용

    if choice == '1':
        print("\n[1] 네이버 경제 섹션 부동산 뉴스를 크롤링합니다...")
        news_title, data_content, news_url = get_top_real_estate_news()
        if not data_content:
            data_content = "금리 인하로 인한 부동산 시장 반등 조짐"
            news_title = "부동산 이슈 분석"

    elif choice == '2':
        print(f"\n[1] '{input_data}' 관련 뉴스를 검색하고 크롤링합니다...")
        news_title, data_content, news_url = get_news_by_keyword(input_data)
        if not data_content:
            data_content = f"'{input_data}' 관련 시장 동향 데이터"
            news_title = f"{input_data} 집중 분석"

    elif choice == '3':
        print(f"\n[1] 자유 기획 주제 '{input_data}'(으)로 작성을 준비합니다...")
        news_title = input_data
        news_url = None  # 자유 주제는 참조 기사 없음
        data_content = (
            f"이 내용은 뉴스 크롤링 데이터가 아닙니다. "
            f"사용자가 요청한 자유 기획 주제입니다. "
            f"다음 주제에 대해 전문가적 지식을 바탕으로 심층적인 블로그 원고를 작성해주세요: {input_data}"
        )

    prompt = f"""
오늘의 작성 기반 데이터(또는 기획 주제)입니다.
<data>
{data_content}
</data>
"""
    print("\n[2] Gemini API로 5000자 원고 및 15장의 영문 사진 프롬프트를 생성 중입니다... (약 30~60초 소요)")
    model = genai.GenerativeModel(
        model_name="gemini-2.5-flash-lite",
        system_instruction=system_instruction,
        generation_config={
            "temperature": 0.7,
            "max_output_tokens": 8192,
        }
    )

    response = model.generate_content(prompt)
    return news_title, response.text, news_url


def make_card_news(image_path, card_data):
    if not card_data:
        return
    try:
        img = Image.open(image_path).convert("RGBA")
        width, height = img.size

        overlay = Image.new('RGBA', img.size, (0, 0, 0, 160))
        img = Image.alpha_composite(img, overlay)
        draw = ImageDraw.Draw(img)

        try:
            font_title = ImageFont.truetype("C:/Windows/Fonts/malgunbd.ttf", 225)
            font_sub   = ImageFont.truetype("C:/Windows/Fonts/malgun.ttf",   120)
            font_point = ImageFont.truetype("C:/Windows/Fonts/malgunbd.ttf", 105)
        except Exception:
            print("     [경고] 맑은 고딕 폰트를 찾을 수 없어 기본 폰트를 사용합니다.")
            font_title = font_sub = font_point = ImageFont.load_default()

        title    = card_data.get("TITLE",    "부동산 핵심 브리핑")
        subtitle = card_data.get("SUBTITLE", "오늘 알아야 할 주요 변화")
        points   = [card_data.get(f"POINT{i}", "") for i in range(1, 4)]
        points   = [p for p in points if p]

        cx = width / 2
        max_text_width = width - 100

        def wrap_text(text, font, max_w):
            lines, current_line = [], ""
            for char in text:
                test = current_line + char
                bbox = draw.textbbox((0, 0), test, font=font)
                if bbox[2] - bbox[0] <= max_w:
                    current_line = test
                else:
                    if current_line:
                        lines.append(current_line)
                    current_line = char
            if current_line:
                lines.append(current_line)
            return lines

        title_lines       = wrap_text(title, font_title, max_text_width)
        sub_lines         = wrap_text(subtitle, font_sub, max_text_width)
        point_lines_list  = [wrap_text(f"✔️ {p}", font_point, max_text_width - 60) for p in points]

        total_height  = len(title_lines) * 230 + len(sub_lines) * 130 + 50
        total_height += sum(len(pl) * 115 + 20 for pl in point_lines_list)

        current_y = max(50, (height - total_height) / 2)

        for line in title_lines:
            bbox = draw.textbbox((0, 0), line, font=font_title)
            draw.text((cx - (bbox[2]-bbox[0])/2, current_y), line, font=font_title, fill=(255, 235, 59, 255))
            current_y += 230
        current_y += 30

        for line in sub_lines:
            bbox = draw.textbbox((0, 0), line, font=font_sub)
            draw.text((cx - (bbox[2]-bbox[0])/2, current_y), line, font=font_sub, fill=(255, 255, 255, 255))
            current_y += 130
        current_y += 80

        if points:
            box_width  = max_text_width
            box_height = sum(len(pl) * 115 + 20 for pl in point_lines_list) + 40
            draw.rounded_rectangle(
                [cx - box_width/2, current_y, cx + box_width/2, current_y + box_height],
                radius=20, fill=(0, 0, 0, 100), outline=(255, 255, 255, 100), width=3
            )
            current_y += 30
            for pl in point_lines_list:
                for line in pl:
                    bbox = draw.textbbox((0, 0), line, font=font_point)
                    draw.text((cx - (bbox[2]-bbox[0])/2, current_y), line, font=font_point, fill=(255, 255, 255, 255))
                    current_y += 115
                current_y += 20

        img.convert("RGB").save(image_path, quality=95)
        print("     [성공] 1번 썸네일 카드뉴스 텍스트 합성 완료!")

    except Exception as e:
        print(f"     [경고] 카드뉴스 텍스트 합성 실패: {e}")


def download_images_from_leonardo(prompts, folder_path, card_data=None, start_num=1):
    """
    Leonardo AI로 이미지를 생성합니다.
    start_num: 실제 이미지가 이미 채운 다음 번호부터 시작합니다.
    """
    api_key = os.getenv("LEONARDO_API_KEY")
    if not api_key:
        print("[오류] .env에 LEONARDO_API_KEY가 설정되지 않아 AI 이미지 생성을 건너뜁니다.")
        return

    leo_headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "authorization": f"Bearer {api_key}"
    }

    remaining = len([p for p in prompts if p.strip()])
    print(f"\n[3] Leonardo AI로 나머지 {remaining}장 이미지를 생성합니다... (슬롯 {start_num}번부터)")

    leo_idx = 0
    for prompt_text in prompts:
        if not prompt_text.strip():
            continue

        clean_prompt = re.sub(r"^\d+[\.\)]\s*", "", prompt_text).strip()
        image_num  = start_num + leo_idx
        image_path = os.path.join(folder_path, f"{image_num}.jpg")

        # 이미 실제 이미지가 존재하는 슬롯은 덮어쓰지 않음
        if os.path.exists(image_path):
            print(f"  -> [{image_num}] 이미 실제 이미지 존재 — 건너뜀")
            leo_idx += 1
            continue

        print(f"  -> [{image_num}] Leonardo 생성 요청 중...")

        try:
            payload = {
                "prompt": clean_prompt,
                "num_images": 1,
                "width": 1024,
                "height": 1024,
                "photoReal": True,
                "alchemy": True
            }
            res = requests.post(
                "https://cloud.leonardo.ai/api/rest/v1/generations",
                json=payload, headers=leo_headers, timeout=30
            )

            if res.status_code == 400 and any(
                k in res.text for k in ["alchemy", "unauthorized", "unexpected"]
            ):
                print(f"     [안내] photoReal 권한 없음 → 기본 모드로 재시도")
                payload.pop("photoReal")
                payload.pop("alchemy")
                res = requests.post(
                    "https://cloud.leonardo.ai/api/rest/v1/generations",
                    json=payload, headers=leo_headers, timeout=30
                )

            if res.status_code != 200:
                print(f"     [오류] API 거절 (코드 {res.status_code}): {res.text}")
                leo_idx += 1
                continue

            generation_id = res.json().get("sdGenerationJob", {}).get("generationId")
            if not generation_id:
                print(f"     [오류] generationId를 받지 못했습니다.")
                leo_idx += 1
                continue

            status, attempts, image_url = "PENDING", 0, None
            print(f"     대기 중 (ID: {generation_id}) ", end="", flush=True)

            while status != "COMPLETE" and attempts < 15:
                time.sleep(5)
                attempts += 1
                print(".", end="", flush=True)
                poll = requests.get(
                    f"https://cloud.leonardo.ai/api/rest/v1/generations/{generation_id}",
                    headers=leo_headers, timeout=20
                )
                if poll.status_code == 200:
                    data = poll.json().get("generations_by_pk", {})
                    status = data.get("status", "")
                    if status == "COMPLETE":
                        imgs = data.get("generated_images", [])
                        if imgs:
                            image_url = imgs[0].get("url")

            print()

            if not image_url:
                print(f"     [오류] {image_num}번 생성 실패 (상태: {status})")
                leo_idx += 1
                continue

            img_res = requests.get(image_url, timeout=30)
            img_res.raise_for_status()
            with open(image_path, "wb") as f:
                f.write(img_res.content)
            print(f"     완료: {image_num}.jpg 저장됨!")

            # 카드뉴스 합성: 1번 슬롯이 Leonardo 담당이 된 경우에만 실행
            if image_num == 1 and card_data:
                make_card_news(image_path, card_data)

            leo_idx += 1

        except Exception as e:
            print(f"\n     [오류] {image_num}번 처리 중 예외: {e}")
            leo_idx += 1
            continue


def _make_post_folder(content_text):
    """
    posts/YYYY-MM-DD/글제목/ 폴더를 생성하고 경로를 반환합니다.
    같은 날 여러 번 실행해도 글마다 독립된 폴더가 만들어집니다.
    """
    today_str = datetime.datetime.now().strftime("%Y-%m-%d")

    # 원고 첫 줄(=블로그 제목)을 폴더명으로 사용
    title_line = next((ln.strip() for ln in content_text.split('\n') if ln.strip()), "제목없음")

    # 파일 시스템에서 사용할 수 없는 문자 제거 후 40자 제한
    safe_title = re.sub(r'[\\/:*?"<>|\n\r\t]', '', title_line).strip()[:40]
    if not safe_title:
        safe_title = "포스트"

    base_dir = os.path.join("posts", today_str, safe_title)
    os.makedirs(base_dir, exist_ok=True)
    print(f"[폴더] {base_dir}")
    return base_dir


def save_content_and_download_images(full_text, news_url=None):
    # ── AI 출력 파싱: 원고 / 카드뉴스 데이터 / 이미지 프롬프트 분리 ──
    content_text = full_text

    if "===CARD_NEWS===" in content_text:
        parts = content_text.split("===CARD_NEWS===")
        content_text = parts[0].strip()
        rest = parts[1]
        if "===IMAGE_PROMPTS===" in rest:
            c_parts      = rest.split("===IMAGE_PROMPTS===")
            prompts_text = c_parts[1].strip()
        else:
            prompts_text = ""
    elif "===IMAGE_PROMPTS===" in content_text:
        parts        = content_text.split("===IMAGE_PROMPTS===")
        content_text = parts[0].strip()
        prompts_text = parts[1].strip()
    else:
        print("[경고] ===IMAGE_PROMPTS=== 구분선을 찾지 못했습니다.")
        content_text = full_text.strip()
        prompts_text = ""

    # ── 폴더 생성 (글제목 기반) ──
    base_dir = _make_post_folder(content_text)

    # ── 파일 저장 ──
    with open(os.path.join(base_dir, "content.txt"), "w", encoding="utf-8") as f:
        f.write(content_text)
    with open(os.path.join(base_dir, "prompts.txt"), "w", encoding="utf-8") as f:
        f.write(prompts_text)

    # ── 카드뉴스 데이터 파싱 ──
    card_data  = {}
    clean_text = full_text.replace('*', '').replace('#', '')
    for line in clean_text.split('\n'):
        line = line.strip()
        if line.startswith("- "):
            line = line[2:]
        for key in ['TITLE', 'SUBTITLE', 'POINT1', 'POINT2', 'POINT3']:
            m = re.search(rf'{re.escape(key)}\s*:', line, re.IGNORECASE)
            if m:
                card_data[key] = line[m.end():].strip()

    if 'TITLE' in card_data:
        print(f"     [안내] 카드뉴스 데이터 감지: '{card_data['TITLE']}'")
    else:
        print("     [경고] 카드뉴스 데이터를 찾지 못했습니다.")

    # ── 이미지 수집 순서 ──
    # 1단계: 기사 본문 이미지 + 조감도/평면도 (실제 이미지)
    leo_start = fetch_all_real_images(
        news_url=news_url,
        content_text=content_text,
        folder_path=base_dir,
        max_article=4,      # 기사 이미지 최대 4장
        max_realestate=5,   # 조감도·평면도 최대 5장
    )

    # 2단계: Leonardo AI 이미지 (나머지 슬롯 채우기)
    if prompts_text:
        prompt_lines = [ln for ln in prompts_text.split("\n") if ln.strip()]
        download_images_from_leonardo(
            prompt_lines, base_dir,
            card_data=card_data,
            start_num=leo_start     # 실제 이미지 다음 번호부터
        )
    else:
        print("[경고] 프롬프트가 없어 Leonardo 이미지 생성을 건너뜁니다.")

    return base_dir, os.path.join(base_dir, "content.txt")


def main():
    print("==================================================")
    print("  블로그 원고 & AI 이미지 완전 자동 생성기")
    print("==================================================")
    print("글쓰기 주제 획득 방식을 선택해주세요:\n")
    print("  1. 네이버 경제 섹션 부동산 뉴스 자동 작성 (기사 이미지 자동 수집)")
    print("  2. 키워드 검색 뉴스 기반 작성  (예: 마포 아파트 청약)")
    print("  3. 자유 주제 기획 작성          (예: 수익형 상가 투자법)")
    print("--------------------------------------------------")

    choice = input("번호를 입력하세요 (1, 2, 3): ").strip()
    input_data = ""

    if choice == '2':
        input_data = input("검색할 뉴스 키워드를 입력하세요: ").strip()
    elif choice == '3':
        input_data = input("원하시는 블로그 기획 주제를 입력하세요: ").strip()
    elif choice != '1':
        print("잘못된 입력입니다. 기본값인 1번으로 진행합니다.")
        choice = '1'

    try:
        title, full_result, news_url = generate_blog_content(choice, input_data)
        saved_dir, _ = save_content_and_download_images(full_result, news_url=news_url)

        print("\n[성공] 원고 생성 및 이미지 수집이 모두 완료되었습니다!")
        print(f"작업 폴더: {saved_dir}")
        print("이제 'python step2_upload.py'를 실행하여 네이버 블로그에 업로드하세요!")
    except Exception as e:
        print(f"\n[오류 발생] {e}")


if __name__ == "__main__":
    main()
