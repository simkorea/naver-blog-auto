@echo off
chcp 65001 > nul
title 증거파인더 백업
cd /d "%~dp0.."

echo.
echo   분석 결과를 백업합니다...
echo   (원본 녹음·문서는 원래 자리에 그대로 있으므로 백업에 넣지 않습니다)
echo.

python -m evidence.backup --create --note "수동 백업"

echo.
python -m evidence.backup --list
echo.
pause
