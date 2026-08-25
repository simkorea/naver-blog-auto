@echo off
chcp 65001 > nul
title 증거파인더
cd /d "%~dp0.."

python --version > nul 2>&1
if errorlevel 1 (
    echo   파이썬이 설치되어 있지 않습니다. "설치.bat" 을 먼저 실행하세요.
    pause
    exit /b 1
)

echo.
echo   증거파인더를 시작합니다...
echo   브라우저가 자동으로 열립니다. 열리지 않으면 아래 주소로 접속하세요:
echo       http://localhost:8501
echo.
echo   ※ 프로그램을 끄려면 이 창을 닫으세요.
echo.

python -m streamlit run evidence\app.py

pause
