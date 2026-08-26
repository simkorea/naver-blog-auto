@echo off
chcp 65001 > nul
title Evidence Finder - Backup
cd /d "%~dp0.."
python -m evidence.backup --create --note "manual"
echo.
python -m evidence.backup --list
echo.
pause
