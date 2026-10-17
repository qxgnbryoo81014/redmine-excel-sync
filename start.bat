@echo off
chcp 65001 >nul
cd /d "%~dp0"

if exist "python\python.exe" (
    set "PY=python\python.exe"
) else (
    set "PY=python"
)

rem 略過 Streamlit 首次啟動的 Email 詢問（否則視窗會停住等待輸入）
if not exist "%USERPROFILE%\.streamlit\credentials.toml" (
    if not exist "%USERPROFILE%\.streamlit" mkdir "%USERPROFILE%\.streamlit"
    (echo [general]& echo email = "")>"%USERPROFILE%\.streamlit\credentials.toml"
)

%PY% -m streamlit run app.py --server.headless false --browser.gatherUsageStats false
if errorlevel 1 (
    echo 介面啟動失敗，可改用 progress-cli.bat
    pause
)
