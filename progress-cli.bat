@echo off
chcp 65001 >nul
cd /d "%~dp0"

if exist "python\python.exe" (
    set "PY=python\python.exe"
) else (
    set "PY=python"
)

%PY% main.py --stage all
if errorlevel 1 (
    echo 更新失敗，請檢查執行紀錄
    pause
    exit /b 1
)
