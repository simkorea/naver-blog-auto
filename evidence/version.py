# -*- coding: utf-8 -*-
"""
지금 도는 코드가 어느 버전인지.

왜 필요한가
  검색 결함을 고쳐 올렸는데 사장님 화면에서는 그대로 0건이 나왔다.
  원인은 코드가 아니라 **고친 코드가 안 돌고 있던 것**이었다. 그런데
  화면 어디에도 버전이 없어서, 둘 중 무엇인지 알 방법이 없었다.

    · `git pull` 을 안 했거나
    · pull 은 했지만 화면을 껐다 켜지 않아 파이썬이 옛 코드를 계속 쓰거나

  이것을 눈으로 바로 확인할 수 있어야 한다. 안 그러면 "고쳤는데 왜 안 되냐"를
  몇 번이고 되풀이하게 된다. 실제로 되풀이했다.
"""
import subprocess
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _git_short() -> str:
    """커밋 짧은 번호. git 이 없거나 저장소가 아니면 빈 문자열."""
    try:
        r = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, errors="replace", timeout=5,
        )
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def _newest_source_mtime() -> float:
    """
    `evidence/` 안에서 가장 최근에 바뀐 .py 파일의 시각.

    git 없이도 "코드가 언제 갱신됐는지"를 알 수 있다. `git pull` 을 하면
    이 값이 올라간다. 사장님이 확인해야 하는 것은 결국 이 값이다.
    """
    newest = 0.0
    try:
        for p in (ROOT / "evidence").rglob("*.py"):
            if "__pycache__" in p.parts:
                continue
            newest = max(newest, p.stat().st_mtime)
    except Exception:
        pass
    return newest


def info() -> dict:
    mt = _newest_source_mtime()
    return {
        "commit": _git_short(),
        "updated": (datetime.fromtimestamp(mt).strftime("%Y-%m-%d %H:%M")
                    if mt else ""),
        "updated_ts": mt,
    }


def label() -> str:
    """화면 한 줄에 넣을 문구."""
    v = info()
    parts = []
    if v["commit"]:
        parts.append(v["commit"])
    if v["updated"]:
        parts.append(f"코드 갱신 {v['updated']}")
    return " · ".join(parts) or "버전을 확인할 수 없음"
