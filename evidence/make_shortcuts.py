# -*- coding: utf-8 -*-
"""
바탕화면 바로가기 만들기 — 더블클릭으로 프로그램을 켠다.

왜 필요한가
  명령창을 열고 폴더로 이동하고 명령어를 치는 것은 매번 부담이다.
  게다가 클로드 코드가 백그라운드로 띄운 프로그램은 클로드 코드 쪽 작업이
  끝나면 같이 꺼진다. 실제로 그렇게 꺼져서 화면이 안 열렸다.

  그래서 **프로그램만 따로 도는 창**을 여는 바로가기를 만든다.

만드는 것 두 개
  증거파인더 실행    프로그램 화면 (streamlit)
  증거파인더 클로드   클로드 코드 (이 폴더에서 시작)

왜 .bat 이 아니라 바로가기인가
  이 저장소에서 이미 겪었다 — 내려받은 `.bat` 은 윈도우의 Smart App Control
  에 막힌다. 바로가기(.lnk)는 그 대상이 아니다.

왜 파이썬에서 PowerShell 을 부르는가
  바로가기 파일(.lnk)은 윈도우 COM 으로만 만들 수 있다. 파이썬에서 직접
  하려면 pywin32 가 필요한데 그건 깔려 있지 않다. PowerShell 은 윈도우에
  항상 있으므로 그쪽에 시키는 편이 확실하다.

    python evidence/make_shortcuts.py
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evidence.console import marks, setup as _console_setup


def _ps_quote(text: str) -> str:
    """PowerShell 작은따옴표 문자열로 감싼다. 안의 작은따옴표는 두 번 쓴다."""
    return "'" + str(text).replace("'", "''") + "'"


def build_script(shortcuts: list[dict]) -> str:
    """
    바로가기를 만드는 PowerShell 스크립트를 짠다.

    바탕화면 경로를 문자열로 박지 않고 GetFolderPath('Desktop') 로 묻는다.
    한국어 윈도우는 '바탕 화면'이고, OneDrive 를 쓰면 아예 다른 곳에 있다.
    """
    lines = [
        "$ErrorActionPreference = 'Stop'",
        "$desk = [Environment]::GetFolderPath('Desktop')",
        "$sh = New-Object -ComObject WScript.Shell",
    ]
    for s in shortcuts:
        lnk = f"Join-Path $desk {_ps_quote(s['name'] + '.lnk')}"
        lines += [
            f"$p = {lnk}",
            "$s = $sh.CreateShortcut($p)",
            f"$s.TargetPath = {_ps_quote(s['target'])}",
            f"$s.Arguments = {_ps_quote(s['arguments'])}",
            f"$s.WorkingDirectory = {_ps_quote(s['workdir'])}",
            f"$s.Description = {_ps_quote(s['description'])}",
            "$s.Save()",
            "Write-Output ('MADE ' + $p)",
        ]
    return "\r\n".join(lines) + "\r\n"


def shortcut_specs(root: Path = None, python: str = None) -> list[dict]:
    """만들 바로가기 두 개의 내용."""
    root = Path(root or ROOT)
    # 지금 이 스크립트를 돌린 파이썬을 그대로 쓴다. PATH 의 'python' 이
    # 다른 버전을 가리키는 일이 흔하다.
    py = python or sys.executable or "python"
    return [
        {
            "name": "증거파인더 실행",
            "target": "powershell.exe",
            # -NoExit: 창이 닫히면 프로그램도 꺼지므로 열어 둔다.
            "arguments": f'-NoExit -Command "& \'{py}\' -m streamlit run evidence/app.py"',
            "workdir": str(root),
            "description": "증거파인더 화면을 엽니다. 이 창을 닫으면 프로그램도 꺼집니다.",
        },
        {
            "name": "증거파인더 클로드",
            "target": "powershell.exe",
            "arguments": "-NoExit -Command claude",
            "workdir": str(root),
            "description": "이 폴더에서 클로드 코드를 시작합니다.",
        },
    ]


def create(root: Path = None) -> list[str]:
    """
    실제로 만든다. 만들어진 경로 목록을 돌려준다.

    윈도우가 아니면 아무것도 하지 않는다 — 바탕화면 바로가기는 윈도우 것이다.
    """
    if os.name != "nt":
        raise RuntimeError("바탕화면 바로가기는 윈도우에서만 만들 수 있습니다.")

    script = build_script(shortcut_specs(root))
    # PowerShell 5.1 은 BOM 이 없으면 UTF-8 파일을 ANSI 로 읽는다.
    # 그러면 '증거파인더'가 깨져서 이름이 이상한 바로가기가 생긴다.
    tmp = Path(tempfile.gettempdir()) / "_증거파인더_바로가기.ps1"
    tmp.write_text(script, encoding="utf-8-sig")
    try:
        r = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-File", str(tmp)],
            capture_output=True, text=True, errors="replace", timeout=120,
        )
    finally:
        tmp.unlink(missing_ok=True)

    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout or "").strip()[:500])
    return [ln[5:] for ln in (r.stdout or "").splitlines()
            if ln.startswith("MADE ")]


def main() -> int:
    _console_setup()
    M = marks()

    print()
    print(M["dline"] * 68)
    print("  바탕화면 바로가기 만들기")
    print(M["dline"] * 68)

    try:
        made = create()
    except RuntimeError as e:
        print(f"\n  {M['no']} 만들지 못했습니다: {e}")
        print("\n  손으로 만드는 방법:")
        for s in shortcut_specs():
            print(f"     [{s['name']}]")
            print(f"        항목 위치 : {s['target']} {s['arguments']}")
            print(f"        시작 위치 : {s['workdir']}")
        return 1

    print()
    for p in made:
        print(f"  {M['ok']} {p}")
    print()
    print("  바탕화면에서 더블클릭하면 됩니다.")
    print()
    print("  [증거파인더 실행]  프로그램 화면 — 실제로 증거를 찾는 곳")
    print("                     검은 창이 같이 뜹니다. 그 창을 닫으면 프로그램도 꺼집니다.")
    print("  [증거파인더 클로드] 코드 고치기 · 검증 · 오류 잡기")
    print(M["dline"] * 68 + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
