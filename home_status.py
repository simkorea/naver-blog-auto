"""
home_status.py - 홈 화면에 띄울 '지금 상태' 요약

대시보드를 열자마자 오늘 뭘 해야 하는지 보이도록,
흩어져 있는 정보(발행 이력·포스트 폴더·카드뉴스 ZIP·대기열)를 한 번에 모읍니다.

UI 코드가 아니라 계산만 담당합니다 - 테스트하기 쉽도록 분리했습니다.
"""
import datetime
import json
from pathlib import Path

POSTS_DIR = Path("posts")
LOG_FILE = POSTS_DIR / "publish_log.jsonl"

# processing 상태가 이 시간을 넘으면 '멈춘 작업'으로 봅니다.
STUCK_HOURS = 2


def _today() -> str:
    return datetime.date.today().isoformat()


def load_publish_log(log_path: Path | str = LOG_FILE) -> list:
    """발행 이력을 최신순으로 반환합니다."""
    log_path = Path(log_path)
    if not log_path.exists():
        return []
    records = []
    for line in log_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                records.append(json.loads(line))
            except Exception:
                continue
    records.reverse()
    return records


def published_today(records: list | None = None) -> list:
    """오늘 올린 글 목록."""
    records = load_publish_log() if records is None else records
    today = _today()
    return [r for r in records if str(r.get("at", "")).startswith(today)]


def count_ready_posts(posts_dir: Path | str = POSTS_DIR) -> int:
    """content.txt 가 있는 포스트 폴더 개수."""
    posts_dir = Path(posts_dir)
    if not posts_dir.exists():
        return 0
    n = 0
    for date_dir in posts_dir.iterdir():
        if date_dir.is_dir():
            n += sum(1 for d in date_dir.iterdir()
                     if d.is_dir() and (d / "content.txt").exists())
    return n


def count_new_zips() -> int:
    """아직 임포트하지 않은 카드뉴스 ZIP 개수."""
    try:
        from publish import collect_candidates
        return sum(1 for c in collect_candidates() if c["kind"] == "zip")
    except Exception:
        return 0


def find_stuck_rows(rows: list, hours: int = STUCK_HOURS) -> list:
    """processing 상태로 오래 멈춰 있는 대기열 행을 골라냅니다.

    업로드 중 브라우저가 죽으면 status 가 processing 에 남는데,
    이걸 되돌리지 않으면 그 글은 영원히 처리되지 않습니다.
    """
    stuck = []
    now = datetime.datetime.now(datetime.timezone.utc)
    for r in rows:
        if r.get("status") != "processing":
            continue
        raw = str(r.get("created_at", "")).replace("Z", "+00:00")
        try:
            created = datetime.datetime.fromisoformat(raw)
            if created.tzinfo is None:
                created = created.replace(tzinfo=datetime.timezone.utc)
        except Exception:
            stuck.append(r)      # 시각을 못 읽으면 일단 의심 대상
            continue
        if (now - created).total_seconds() > hours * 3600:
            stuck.append(r)
    return stuck


def build_summary(queue_rows: list | None = None) -> dict:
    """홈 화면에 필요한 값을 한 번에 계산합니다."""
    records = load_publish_log()
    today_posts = published_today(records)
    rows = queue_rows or []

    return {
        "published_today":  len(today_posts),
        "today_titles":     [r.get("title", "") for r in today_posts],
        "recent":           records[:5],
        "ready_posts":      count_ready_posts(),
        "new_zips":         count_new_zips(),
        "queue_pending":    sum(1 for r in rows if r.get("status") == "pending"),
        "queue_error":      sum(1 for r in rows if r.get("status") == "error"),
        "stuck":            find_stuck_rows(rows),
        "total_published":  len(records),
    }


def next_action(summary: dict) -> tuple[str, str]:
    """지금 가장 먼저 할 일을 (제목, 설명) 으로 돌려줍니다."""
    if summary["stuck"]:
        return ("멈춘 작업 정리하기",
                f"{len(summary['stuck'])}건이 처리 중 상태로 멈춰 있습니다. "
                "시스템 상태 탭에서 되돌려주세요.")
    if summary["new_zips"]:
        return ("새 카드뉴스 가져오기",
                f"아직 등록하지 않은 카드뉴스 ZIP이 {summary['new_zips']}건 있습니다.")
    if summary["published_today"] == 0 and summary["ready_posts"]:
        return ("오늘 글 발행하기",
                f"발행 대기 중인 원고가 {summary['ready_posts']}건 있습니다.")
    if summary["published_today"] == 0:
        return ("새 원고 만들기", "오늘 아직 발행한 글이 없습니다.")
    return ("오늘 할 일 완료",
            f"오늘 {summary['published_today']}건 올리셨습니다. 새 글을 더 써도 좋습니다.")
