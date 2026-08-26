@echo off
chcp 65001 > nul
title Evidence Finder
cd /d "%~dp0.."

where python > nul 2>&1
if errorlevel 1 goto nopython

python -m streamlit run evidence\app.py
pause
exit /b 0

:nopython
echo.
echo   [!] Python is not installed. Run "install.bat" first.
echo.
pause
exit /b 1
