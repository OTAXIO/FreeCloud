@echo off
chcp 65001 >nul
cd /d "%~dp0"
"D:\Basement\Miniconda3\envs\jiaoworun\python.exe" start.py --no-pause
echo.
pause
