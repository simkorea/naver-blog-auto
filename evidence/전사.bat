@echo off
chcp 65001 > nul
title Evidence Finder - Transcribe
cd /d "%~dp0.."

where python > nul 2>&1
if errorlevel 1 goto nopython

python evidence\transcribe.py
pause
exit /b 0

:nopython
echo Python not found. Install Python 3.10+ and check "Add Python to PATH".
pause
