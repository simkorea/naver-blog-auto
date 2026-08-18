@echo off
chcp 65001 > nul
title 네이버 블로그 자동화
cd /d "%~dp0"
if exist "venv\Scripts\python.exe" (
    venv\Scripts\python.exe menu.py
) else (
    python menu.py
)
