@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
title Commission System - Sync Update
REM ============================================================
REM  Commission System - Daily Update Script
REM  Run on server after each git push from dev machine
REM ============================================================

set "INSTALL_DIR=D:\commission-system"
set "SERVICE_NAME=CommissionSystem"

echo.
echo ==============================
echo   Commission System - Sync
echo ==============================
echo.

REM ---------- Check directory ----------
if not exist "%INSTALL_DIR%\.git" (
    echo [ERROR] %INSTALL_DIR% is not a Git repo, run setup-server.bat first
    goto :error
)

REM ---------- [1/5] Pull latest code ----------
echo [1/5] Git pull...
cd /d "%INSTALL_DIR%"
git pull
if errorlevel 1 (
    echo [ERROR] git pull failed
    goto :error
)
echo      OK
echo.

REM ---------- [2/5] Backend deps ----------
echo [2/5] Backend dependencies...
cd /d "%INSTALL_DIR%\backend"
call .venv\Scripts\activate.bat
if errorlevel 1 (
    echo [ERROR] venv activate failed
    goto :error
)
pip install -r requirements.txt -q
if errorlevel 1 (
    echo [ERROR] pip install failed
    goto :error
)
echo      OK
echo.

REM ---------- [3/5] Database migration ----------
echo [3/5] Database migration...
alembic upgrade head
if errorlevel 1 (
    echo [ERROR] alembic migration failed
    goto :error
)
echo      OK
echo.

REM ---------- [4/5] Build frontend ----------
echo [4/5] Build frontend...
cd /d "%INSTALL_DIR%\frontend"
call npm install --silent
if errorlevel 1 (
    echo [ERROR] npm install failed
    goto :error
)
call npm run build
if errorlevel 1 (
    echo [ERROR] npm build failed
    goto :error
)
echo      OK
echo.

REM ---------- [5/5] Restart service ----------
echo [5/5] Restart service...
nssm restart %SERVICE_NAME%
if errorlevel 1 (
    echo [WARNING] Restart failed, trying stop + start...
    nssm stop %SERVICE_NAME%
    timeout /t 2 /nobreak >nul
    nssm start %SERVICE_NAME%
    if errorlevel 1 (
        echo [ERROR] Service start failed
        goto :error
    )
)
echo      OK
echo.

echo ==============================
echo   Update completed!
echo ==============================
echo.
goto :done

:error
echo.
echo ==============================
echo   Update FAILED! Check errors above
echo ==============================

:done
echo.
pause