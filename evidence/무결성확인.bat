@echo off
chcp 65001 > nul
title Evidence Finder - Verify Originals
cd /d "%~dp0.."
python -m evidence.integrity --verify
echo.
pause
