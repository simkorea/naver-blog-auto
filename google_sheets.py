"""
Google Sheets 연동 모듈 — 발행 대기열 관리
하이브리드 아키텍처: 클라우드 대시보드 → GSheets → 로컬 매크로 PC
"""
import json
import datetime
import uuid

import gspread
from google.oauth2.service_account import Credentials

_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

_HEADER = [
    "id", "created_at", "date", "title",
    "content", "tags", "status", "error_msg", "local_folder",
]


def _get_client(creds_json: str) -> gspread.Client:
    creds_dict = json.loads(creds_json)
    creds = Credentials.from_service_account_info(creds_dict, scopes=_SCOPES)
    return gspread.authorize(creds)


def _ensure_header(sheet: gspread.Worksheet) -> None:
    if not sheet.row_values(1):
        sheet.insert_row(_HEADER, 1)


# ── 공개 API ────────────────────────────────────────────────────────────────

def push_pending(
    creds_json: str,
    sheet_id: str,
    title: str,
    content: str,
    tags: str,
    local_folder: str,
) -> tuple[bool, str]:
    """구글 시트에 '발행 대기(pending)' 행을 추가합니다.

    Returns:
        (성공 여부, 행 ID 또는 오류 메시지)
    """
    try:
        client = _get_client(creds_json)
        sheet = client.open_by_key(sheet_id).sheet1
        _ensure_header(sheet)

        row_id    = str(uuid.uuid4())[:8]
        now       = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        date_str  = datetime.datetime.now().strftime("%Y-%m-%d")

        sheet.append_row(
            [row_id, now, date_str, title, content, tags,
             "pending", "", local_folder],
            value_input_option="RAW",
        )
        return True, row_id
    except Exception as e:
        return False, str(e)


def get_all_rows(creds_json: str, sheet_id: str) -> list[dict]:
    """시트의 모든 행(헤더 제외)을 dict 리스트로 반환합니다."""
    try:
        client = _get_client(creds_json)
        sheet  = client.open_by_key(sheet_id).sheet1
        return sheet.get_all_records()
    except Exception:
        return []


def update_status(
    creds_json: str,
    sheet_id: str,
    row_id: str,
    status: str,
    error_msg: str = "",
) -> bool:
    """특정 id 행의 status와 error_msg를 업데이트합니다."""
    try:
        client = _get_client(creds_json)
        sheet  = client.open_by_key(sheet_id).sheet1
        cell   = sheet.find(row_id, in_column=1)
        if cell:
            sheet.update_cell(cell.row, _HEADER.index("status")    + 1, status)
            sheet.update_cell(cell.row, _HEADER.index("error_msg") + 1, error_msg)
        return True
    except Exception:
        return False
