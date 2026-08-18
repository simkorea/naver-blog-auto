@echo off
chcp 65001 > nul
title 블로그 여러건 발행
cd /d "%~dp0"
if exist "venv\Scripts\python.exe" (
    venv\Scripts\python.exe publish.py --list
    echo.
    echo 예시: batch_publish.py 1 3 5 --gap 10
    echo.
    set /p ARGS="번호와 옵션 입력: "
    venv\Scripts\python.exe batch_publish.py %ARGS%
) else (
    python publish.py --list
    set /p ARGS="번호와 옵션 입력: "
    python batch_publish.py %ARGS%
)
pause
