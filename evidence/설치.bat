@echo off
chcp 65001 > nul
title 증거파인더 설치
cd /d "%~dp0.."

echo.
echo ====================================================================
echo   증거파인더 설치
echo ====================================================================
echo.
echo   필요한 것을 알아서 설치합니다. 몇 분 걸릴 수 있습니다.
echo.
pause

python --version > nul 2>&1
if errorlevel 1 (
    echo.
    echo   [문제] 파이썬이 설치되어 있지 않습니다.
    echo.
    echo   1. https://www.python.org/downloads/ 에서 내려받아 설치하세요.
    echo   2. 설치 화면에서 "Add Python to PATH" 에 반드시 체크하세요.
    echo   3. 설치 후 이 파일을 다시 실행하세요.
    echo.
    pause
    exit /b 1
)

python evidence\setup_check.py --install
if errorlevel 1 (
    echo.
    echo   설치 중 문제가 있었습니다. 위 메시지를 확인하세요.
    pause
    exit /b 1
)

echo.
echo ====================================================================
echo   AI 모델을 미리 받아둘까요?
echo ====================================================================
echo.
echo   약 4GB를 내려받습니다. 시간이 걸리지만 한 번 받아두면
echo   이후에는 인터넷 없이도 동작하고, 급할 때 기다리지 않아도 됩니다.
echo.
set /p ANS="   지금 받을까요? (Y/N): "
if /i "%ANS%"=="Y" python evidence\setup_check.py --models

echo.
echo ====================================================================
echo   설치가 끝났습니다.
echo.
echo   실행하려면 같은 폴더의 "실행.bat" 을 더블클릭하세요.
echo ====================================================================
echo.
pause
