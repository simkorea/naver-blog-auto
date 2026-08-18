@echo off
chcp 65001 > nul
title 블로그 발행하기
cd /d "%~dp0"
if exist "venv\Scripts\python.exe" (
    venv\Scripts\python.exe publish.py
) else (
    python publish.py
)
pause
