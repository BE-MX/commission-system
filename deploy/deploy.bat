@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
title LeShine Ark Platform - Sync Update
REM ============================================================
REM  LeShine Ark Platform - Daily Update Script
REM  Run on server after each git push from dev machine
REM ============================================================

set "INSTALL_DIR=D:\commission-system"
set "SERVICE_NAME=CommissionSystem"
set "CLOUD_SERVER=root@119.28.107.92"
set "CLOUD_DIST=/var/www/ark/dist"

echo.
echo ==============================
echo   LeShine Ark Platform - Sync
echo ==============================
echo.

REM ---------- Check directory ----------
if not exist "%INSTALL_DIR%\.git" (
    echo [ERROR] %INSTALL_DIR% is not a Git repo, run setup-server.bat first
    goto :error
)

REM ---------- [1/6] Pull latest code ----------
echo [1/6] Git pull...
cd /d "%INSTALL_DIR%"
git pull
if errorlevel 1 (
    echo [ERROR] git pull failed
    goto :error
)
echo      OK
echo.

REM ---------- [2/6] Backend deps ----------
echo [2/6] Backend dependencies...
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

REM ---------- [3/6] Database migration ----------
echo [3/6] Database migration...
alembic upgrade head
if errorlevel 1 (
    echo [ERROR] alembic migration failed
    goto :error
)
echo      OK
echo.

REM ---------- [4/6] Build frontend ----------
echo [4/6] Build frontend...
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

REM ---------- [5/6] Sync dist to cloud ----------
echo [5/6] Sync frontend to cloud server...
cd /d "%INSTALL_DIR%\frontend"
scp -r dist/* %CLOUD_SERVER%:%CLOUD_DIST%
if errorlevel 1 (
    echo [WARNING] SCP sync failed - cloud CDN may be stale
) else (
    echo      OK
)
echo.

REM ---------- [6/6] Restart service ----------
echo [6/6] Restart service...
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