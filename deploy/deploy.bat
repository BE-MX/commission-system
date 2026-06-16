@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
title LeShine Ark Platform - Sync
REM ============================================================
REM  LeShine Ark Platform - Daily Update Script
REM  Run on server after each git push from dev machine
REM  [4/6] and [5/6] auto-skip if frontend has no changes
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
.\.venv\Scripts\python.exe scripts\show_db_config.py
.\.venv\Scripts\python.exe -m alembic upgrade head
if errorlevel 1 (
    echo [ERROR] alembic migration failed
    goto :error
)
echo      OK
echo.

REM ---------- Detect frontend changes ----------
set "FRONTEND_CHANGED=0"
cd /d "%INSTALL_DIR%"
REM 检查本次 pull 是否改了 frontend/src 或 frontend/public 或 frontend/package.json
git diff --name-only HEAD@{1} HEAD -- frontend/src/ frontend/public/ frontend/package.json frontend/package-lock.json frontend/vite.config.* 2>nul | findstr /R "." >nul 2>&1
if not errorlevel 1 (
    set "FRONTEND_CHANGED=1"
)
REM 也检查是否有未提交的本地改动
git diff --name-only -- frontend/src/ frontend/public/ frontend/package.json | findstr /R "." >nul 2>&1
if not errorlevel 1 (
    set "FRONTEND_CHANGED=1"
)

if "%FRONTEND_CHANGED%"=="0" (
    echo [4/6] Build frontend... SKIPPED ^(no frontend changes detected^)
    echo.
    echo [5/6] Sync dist to cloud... SKIPPED
    echo.
    goto :restart_service
)

REM ---------- [4/6] Build frontend ----------
echo [4/6] Build frontend... ^(changes detected^)
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

REM 优先用 Git Bash 自带的 rsync（增量同步，只传变化的文件）
set "RSYNC_PATH="
for /f "delims=" %%P in ('where rsync 2^>nul') do set "RSYNC_PATH=%%P"

if defined RSYNC_PATH (
    echo      Using rsync incremental sync...
    rsync -avz --delete --chmod=D755,F644 dist/ %CLOUD_SERVER%:%CLOUD_DIST%/
    if errorlevel 1 (
        echo [WARNING] rsync failed, fallback to scp...
        call :scp_full
    ) else (
        echo      OK
    )
) else (
    REM 没有 rsync，通过 ssh 在远程做增量比对
    call :scp_smart
)
echo.
goto :restart_service

:scp_smart
REM 利用 ssh+md5sum 比对，只传变化的文件
REM 1) 获取远程 assets 文件 md5 清单
echo      Computing diff via ssh...
ssh %CLOUD_SERVER% "cd %CLOUD_DIST% && find assets/ -type f -exec md5sum {} \; 2>/dev/null" > "%TEMP%\cloud_md5.txt" 2>nul

REM 2) 生成本地 md5 清单
cd /d "%INSTALL_DIR%\frontend\dist"
if exist "%TEMP%\cloud_md5.txt" (
    REM 有远程清单，做增量比对
    set UPLOAD_COUNT=0
    REM 始终同步 index.html
    scp index.html %CLOUD_SERVER%:%CLOUD_DIST%/index.html >nul 2>&1
    REM m/ 和 vendor/ 通常小且少变，直接传
    scp -r m %CLOUD_SERVER%:%CLOUD_DIST%/ >nul 2>&1
    scp -r vendor %CLOUD_SERVER%:%CLOUD_DIST%/ >nul 2>&1
    REM 逐个比对 assets 文件
    for /f "delims=" %%F in ('dir /s /b assets\*') do (
        set "RELPATH=%%F"
        set "RELPATH=!RELPATH:%CD%\=!"
        REM 替换反斜杠为正斜杠
        set "RELPATH=!RELPATH:\=/!"
        REM 检查远程是否有同名且 md5 一致的文件
        findstr /C:"!RELPATH!" "%TEMP%\cloud_md5.txt" >nul 2>&1
        if errorlevel 1 (
            REM 远程没有此文件，需要上传
            scp "%%F" %CLOUD_SERVER%:%CLOUD_DIST%/!RELPATH! >nul 2>&1
            set /a UPLOAD_COUNT+=1
        )
    )
    echo      OK !UPLOAD_COUNT! new/changed assets uploaded
) else (
    REM 无法获取远程清单，回退全量 scp
    call :scp_full
)
goto :eof

:scp_full
echo      Full scp sync...
scp -r dist/* %CLOUD_SERVER%:%CLOUD_DIST%/
if errorlevel 1 (
    echo [WARNING] SCP sync failed - cloud may be stale
) else (
    echo      OK
)
goto :eof

:restart_service
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
