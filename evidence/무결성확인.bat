@echo off
chcp 65001 > nul
title 원본 무결성 확인
cd /d "%~dp0.."

echo.
echo   등록된 원본 파일이 수집 당시와 같은지 확인합니다.
echo   파일 수가 많으면 시간이 걸립니다.
echo.

python -m evidence.integrity --verify

echo.
pause
