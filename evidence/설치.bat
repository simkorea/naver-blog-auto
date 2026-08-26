@echo off
chcp 65001 > nul
title Evidence Finder - Install
cd /d "%~dp0.."

where python > nul 2>&1
if errorlevel 1 goto nopython

python evidence\setup_check.py --install
if errorlevel 1 goto failed

python evidence\setup_check.py --ask-models
goto done

:nopython
echo.
echo   [!] Python is not installed.
echo.
echo   1. Download from https://www.python.org/downloads/
echo   2. CHECK "Add Python to PATH" during install
echo   3. Run this file again
echo.
pause
exit /b 1

:failed
echo.
echo   Install had a problem. See the messages above.
pause
exit /b 1

:done
pause
