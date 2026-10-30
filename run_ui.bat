@echo off
chcp 65001 >nul
title HoYoLAB Multi-Account Toolkit UI

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [!] Khong tim thay moi truong ao .venv!
    echo [*] Vui long kiem tra lai thu muc cai dat.
    pause
    exit /b 1
)

echo ====================================================
echo    DANG KHOI DONG HOYOLAB MULTI-ACCOUNT WEB UI...
echo ====================================================
echo.
echo [*] Ung dung dang chay tai: http://127.0.0.1:8000
echo [*] Trinh duyet se tu dong mo len sau vai giay...
echo [*] Nhan Ctrl + C hoac dong cua so nay de tat ung dung.
echo.

:: Tu dong mo trinh duyet sau 2 giay
start "" cmd /c "timeout /t 2 /nobreak >nul && start http://127.0.0.1:8000"

:: Khoi dong FastAPI server
".venv\Scripts\python.exe" -m uvicorn app_ui:app --host 127.0.0.1 --port 8000

pause
