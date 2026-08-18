@echo off
chcp 65001 > nul
title 블로그 대시보드
cd /d "%~dp0"
if exist "venv\Scripts\python.exe" (
    venv\Scripts\python.exe launcher.py
) else (
    python launcher.py
)
pause
