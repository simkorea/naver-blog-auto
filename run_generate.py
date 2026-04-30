"""
run_generate.py — 웹 대시보드가 subprocess로 호출하는 논인터랙티브 진입점.

usage:
    python run_generate.py <choice> [input_data] [persona] [extra_instruction]

완료 시 마지막 줄에 "RESULT_DIR:<경로>" 를 출력합니다.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from step1_generate import generate_blog_content, save_content_and_download_images

def main():
    if len(sys.argv) < 2:
        print("[오류] 사용법: python run_generate.py <1|2|3> [input_data] [persona] [extra]")
        sys.exit(1)

    choice           = sys.argv[1]
    input_data       = sys.argv[2] if len(sys.argv) > 2 else ""
    persona          = sys.argv[3] if len(sys.argv) > 3 else None
    extra_instruction= sys.argv[4] if len(sys.argv) > 4 else None

    title, full_text, news_url = generate_blog_content(
        choice, input_data,
        persona=persona,
        extra_instruction=extra_instruction,
    )
    saved_dir, _ = save_content_and_download_images(full_text, news_url=news_url)

    print(f"RESULT_DIR:{saved_dir}")

if __name__ == "__main__":
    main()
