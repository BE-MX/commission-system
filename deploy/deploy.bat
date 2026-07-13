@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
title LeShine Ark Platform - Sync
REM ============================================================
REM  LeShine Ark Platform - Daily Update Script
REM  Run on server after each git push from dev machine
REM  [5/7] and [6/7] auto-skip if frontend has no changes
REM ============================================================

set "INSTALL_DIR=D:\commission-system"
set "SERVICE_NAME=CommissionSystem"
set "CONNECTOR_SERVICE_NAME=WhatsAppConnector"
if not defined CONNECTOR_SERVICE_NAME set "CONNECTOR_SERVICE_NAME=WhatsAppConnector"
set "NSSM_EXE=%USERPROFILE%\AppData\Local\Microsoft\WinGet\Links\nssm.exe"
set "CLOUD_SERVER=root@119.28.107.92"
set "CLOUD_DIST=/var/www/ark/dist"
REM All ssh/scp go through these opts (2026-07-13): BatchMode turns any interactive
REM prompt (host key / password) into an immediate error instead of a silent hang;
REM ConnectTimeout/ServerAlive bound dead-network waits to ~70s max.
set "SSH_OPTS=-o BatchMode=yes -o ConnectTimeout=10 -o ServerAliveInterval=15 -o ServerAliveCountMax=4"

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
if not exist "%NSSM_EXE%" (
    for /f "delims=" %%P in ('where nssm.exe 2^>nul') do (
        if not defined NSSM_EXE_FOUND set "NSSM_EXE_FOUND=%%P"
    )
    if defined NSSM_EXE_FOUND set "NSSM_EXE=!NSSM_EXE_FOUND!"
)
if not exist "%NSSM_EXE%" (
    echo [ERROR] nssm.exe not found. Install NSSM or update NSSM_EXE in deploy.bat
    goto :error
)

REM ---------- [0/7] Pre-deploy snapshot (rollback anchor, B-9) ----------
echo [0/7] Pre-deploy snapshot...
cd /d "%INSTALL_DIR%"
for /f "delims=" %%T in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd-HHmmss"') do set "SNAP_TS=%%T"
for /f "delims=" %%H in ('git rev-parse --short HEAD') do set "PREV_HEAD=%%H"
git tag -f deploy-last >nul 2>&1
git tag deploy-%SNAP_TS% >nul 2>&1
if not exist "%INSTALL_DIR%\.deploy_state" mkdir "%INSTALL_DIR%\.deploy_state"
echo %PREV_HEAD%>"%INSTALL_DIR%\.deploy_state\last_deploy_commit.txt"
if exist "%INSTALL_DIR%\frontend\dist" (
    if exist "%INSTALL_DIR%\.deploy_state\dist_backup" rmdir /s /q "%INSTALL_DIR%\.deploy_state\dist_backup"
    xcopy /e /i /q /y "%INSTALL_DIR%\frontend\dist" "%INSTALL_DIR%\.deploy_state\dist_backup" >nul
)
echo      OK ^(tag deploy-%SNAP_TS%, commit %PREV_HEAD%^)
echo.

REM ---------- [1/7] Pull latest code ----------
echo [1/7] Git pull...
cd /d "%INSTALL_DIR%"
git pull
if errorlevel 1 (
    echo [ERROR] git pull failed
    goto :error
)
echo      OK
echo.

REM ---------- [2/7] Backend deps ----------
echo [2/7] Backend dependencies...
cd /d "%INSTALL_DIR%\backend"
call .venv\Scripts\activate.bat
if errorlevel 1 (
    echo [ERROR] venv activate failed
    goto :error
)
REM Python version guard: deps are validated on 3.12. A venv built with another
REM Python (e.g. 3.14) resolves a different set (ResolutionImpossible) or misses
REM cp3xx wheels and falls back to source build. Fail fast with clear guidance.
for /f "tokens=2" %%v in ('.\.venv\Scripts\python.exe --version 2^>^&1') do set "PYVER=%%v"
echo      venv Python %PYVER%
echo %PYVER% | findstr /b "3.12." >nul
if errorlevel 1 (
    echo [ERROR] venv Python is %PYVER%, expected 3.12.x
    echo         Recreate the venv with Python 3.12:
    echo           "%NSSM_EXE%" stop "%SERVICE_NAME%"
    echo           rmdir /s /q "%INSTALL_DIR%\backend\.venv"
    echo           py -3.12 -m venv "%INSTALL_DIR%\backend\.venv"
    echo         then rerun deploy.bat
    goto :error
)
REM UTF-8 mode: sdist builds reading README default to system GBK on CN Windows and crash
set PYTHONUTF8=1
REM Upgrade pip first: old pip legacy resolver picks an old starlette violating fastapi<0.47
REM and builds it from source; modern resolver hits the starlette 0.46.2 wheel. Explicit
REM venv python to dodge PATH pollution.
.\.venv\Scripts\python.exe -m pip install --upgrade pip -q
if errorlevel 1 (
    echo [ERROR] pip upgrade failed
    goto :error
)
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -q
if errorlevel 1 (
    echo [ERROR] pip install failed
    goto :error
)
echo      OK
echo.

REM ---------- [3/7] Connector dependencies ----------
echo [3/7] Connector dependencies...
cd /d "%INSTALL_DIR%\services\whatsapp-connector"
call npm install --silent
if errorlevel 1 (
    echo [ERROR] connector npm install failed
    goto :error
)
call npm run check
if errorlevel 1 (
    echo [ERROR] connector syntax check failed
    goto :error
)
echo      OK
echo.

REM ---------- [4/7] Database migration ----------
echo [4/7] Database migration...
cd /d "%INSTALL_DIR%\backend"
.\.venv\Scripts\python.exe scripts\show_db_config.py
.\.venv\Scripts\python.exe -m alembic upgrade head
if errorlevel 1 (
    echo [ERROR] alembic migration failed
    goto :error
)
REM Migration validation
for /f "delims=" %%V in ('.\.venv\Scripts\python.exe -m alembic current 2^>nul') do set "CURRENT_REVISION=%%V"
echo      Current revision: %CURRENT_REVISION%
if "%CURRENT_REVISION%"=="" (
    echo [ERROR] Failed to read current migration revision
    goto :error
)
echo      OK
echo.

REM ---------- Detect frontend changes ----------
set "FRONTEND_CHANGED=0"
set "FRONTEND_MARKER=%INSTALL_DIR%\.deploy_state\frontend_build_commit.txt"
set "FRONTEND_BASE="
cd /d "%INSTALL_DIR%"
if exist "%FRONTEND_MARKER%" (
    set /p FRONTEND_BASE=<"%FRONTEND_MARKER%"
)

if not defined FRONTEND_BASE (
    set "FRONTEND_CHANGED=1"
    echo      Frontend build marker missing; build required
) else (
    REM 检查上次成功构建的 commit 到当前 HEAD 是否改了 frontend
    git diff --name-only %FRONTEND_BASE% HEAD -- frontend/src/ frontend/public/ frontend/package.json frontend/package-lock.json frontend/vite.config.* 2>nul | findstr /R "." >nul 2>&1
    if not errorlevel 1 (
        set "FRONTEND_CHANGED=1"
    )
)
REM 也检查是否有未提交的本地改动
git diff --name-only -- frontend/src/ frontend/public/ frontend/package.json | findstr /R "." >nul 2>&1
if not errorlevel 1 (
    set "FRONTEND_CHANGED=1"
)

if "%FRONTEND_CHANGED%"=="0" (
    echo [5/7] Build frontend... SKIPPED ^(no frontend changes detected^)
    echo.
    echo [6/7] Sync dist to cloud... SKIPPED
    echo.
    goto :restart_service
)

REM ---------- [5/7] Build frontend ----------
echo [5/7] Build frontend... ^(changes detected^)
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

REM ---------- [6/7] Sync dist to cloud ----------
echo [6/7] Sync frontend to cloud server...
cd /d "%INSTALL_DIR%\frontend"

REM 优先用 Git Bash 自带的 rsync（增量同步，只传变化的文件）
set "SYNC_OK=0"
set "RSYNC_PATH="
for /f "delims=" %%P in ('where rsync 2^>nul') do set "RSYNC_PATH=%%P"

if defined RSYNC_PATH (
    echo      Using rsync incremental sync...
    rsync -avz --delete --chmod=D755,F644 -e "ssh %SSH_OPTS%" dist/ %CLOUD_SERVER%:%CLOUD_DIST%/
    if not errorlevel 1 (
        set "SYNC_OK=1"
        echo      OK
    ) else (
        echo [WARNING] rsync failed, fallback to scp...
        call :scp_full
        if not errorlevel 1 set "SYNC_OK=1"
    )
) else (
    REM 没有 rsync，通过 ssh 在远程做增量比对
    call :scp_smart
    if not errorlevel 1 set "SYNC_OK=1"
)
echo.

REM Sync failure aborts and leaves the marker unchanged, so the next deploy retries
REM (2026-07-11 fix: marker was written unconditionally + scp errors swallowed by >nul,
REM  so one silent sync failure poisoned the marker and skipped cloud sync forever).
if not "!SYNC_OK!"=="1" (
    echo [ERROR] Frontend sync to cloud FAILED - cloud dist NOT updated.
    echo         Build marker left unchanged so the next deploy retries the sync.
    echo         Check ssh/rsync to %CLOUD_SERVER% ^(key / network / path %CLOUD_DIST%^).
    goto :error
)

REM Advance the frontend build marker only after a confirmed successful sync
if not exist "%INSTALL_DIR%\.deploy_state" mkdir "%INSTALL_DIR%\.deploy_state"
for /f "delims=" %%H in ('git -C "%INSTALL_DIR%" rev-parse HEAD') do set "CURRENT_HEAD=%%H"
echo !CURRENT_HEAD!>"%FRONTEND_MARKER%"
goto :restart_service

:scp_smart
REM 利用 ssh+md5sum 比对，只传变化的文件
set "SMART_FAIL=0"
REM 1) 获取远程 assets 文件 md5 清单
echo      Computing diff via ssh...
ssh %SSH_OPTS% %CLOUD_SERVER% "cd %CLOUD_DIST% && find assets/ -type f -exec md5sum {} \; 2>/dev/null" > "%TEMP%\cloud_md5.txt" 2>nul
REM ssh failure leaves an EMPTY file behind (the > redirect creates it first);
REM delete it so we fall through to :scp_full instead of diffing against nothing
if errorlevel 1 del /q "%TEMP%\cloud_md5.txt" >nul 2>&1

REM 2) 生成本地 md5 清单
cd /d "%INSTALL_DIR%\frontend\dist"
if exist "%TEMP%\cloud_md5.txt" (
    REM 有远程清单，做增量比对
    set UPLOAD_COUNT=0
    REM Always upload index.html; its failure means the ssh/scp channel is down = overall fail
    echo      index.html...
    scp %SSH_OPTS% index.html %CLOUD_SERVER%:%CLOUD_DIST%/index.html
    if errorlevel 1 set "SMART_FAIL=1"
    REM m/ is small (<1MB), always upload
    scp %SSH_OPTS% -r m %CLOUD_SERVER%:%CLOUD_DIST%/ >nul 2>&1
    REM vendor/ holds ~35MB Stimulsoft that almost never changes: upload only when
    REM git says it changed since the last synced build, or the cloud copy is missing
    set "VENDOR_CHANGED=0"
    if not defined FRONTEND_BASE set "VENDOR_CHANGED=1"
    if defined FRONTEND_BASE (
        git -C "%INSTALL_DIR%" diff --name-only %FRONTEND_BASE% HEAD -- frontend/public/vendor/ 2>nul | findstr /R "." >nul 2>&1
        if not errorlevel 1 set "VENDOR_CHANGED=1"
    )
    git -C "%INSTALL_DIR%" diff --name-only -- frontend/public/vendor/ 2>nul | findstr /R "." >nul 2>&1
    if not errorlevel 1 set "VENDOR_CHANGED=1"
    ssh %SSH_OPTS% %CLOUD_SERVER% "test -d %CLOUD_DIST%/vendor/stimulsoft" >nul 2>&1
    if errorlevel 1 set "VENDOR_CHANGED=1"
    if "!VENDOR_CHANGED!"=="1" (
        echo      vendor/ changed or missing on cloud, uploading ~35MB...
        REM no ^>nul here: a 35MB transfer with output swallowed looks like a hang
        scp %SSH_OPTS% -r vendor %CLOUD_SERVER%:%CLOUD_DIST%/
        if errorlevel 1 set "SMART_FAIL=1"
    ) else (
        echo      vendor/ unchanged, skipped
    )
    REM 逐个比对 assets 文件（每传一个打一行进度——2026-07-13 前这里全程静默，
    REM 几十个文件 × 每个单开一条 SSH 连接会安静跑数分钟，曾被误判为卡死而中断）
    for /f "delims=" %%F in ('dir /s /b assets\*') do (
        set "RELPATH=%%F"
        set "RELPATH=!RELPATH:%CD%\=!"
        REM 替换反斜杠为正斜杠
        set "RELPATH=!RELPATH:\=/!"
        REM 检查远程是否有同名文件（vite 内容 hash 命名，同名即同内容）
        findstr /C:"!RELPATH!" "%TEMP%\cloud_md5.txt" >nul 2>&1
        if errorlevel 1 (
            REM 远程没有此文件，需要上传
            set /a UPLOAD_COUNT+=1
            echo      [!UPLOAD_COUNT!] !RELPATH!
            scp %SSH_OPTS% "%%F" %CLOUD_SERVER%:%CLOUD_DIST%/!RELPATH! >nul 2>&1
            if errorlevel 1 (
                echo      [ERROR] upload failed: !RELPATH!
                set "SMART_FAIL=1"
            )
        )
    )
    echo      OK !UPLOAD_COUNT! new/changed assets uploaded
) else (
    REM 无法获取远程清单，回退全量 scp
    call :scp_full
    if errorlevel 1 set "SMART_FAIL=1"
)
exit /b !SMART_FAIL!

:scp_full
echo      Full scp sync...
REM 显式回到 frontend：从 :scp_smart 回退进来时 CWD 在 dist 里，dist/* 会失配
cd /d "%INSTALL_DIR%\frontend"
scp %SSH_OPTS% -r dist/* %CLOUD_SERVER%:%CLOUD_DIST%/
if errorlevel 1 (
    echo [WARNING] SCP sync failed - cloud may be stale
    exit /b 1
)
echo      OK
exit /b 0

:restart_service
REM ---------- [7/7] Restart services ----------
echo [7/7] Restart services...
call :restart_nssm_service "%SERVICE_NAME%" "Ark backend"
if errorlevel 1 goto :error
call :restart_nssm_service "WhatsAppConnector" "WhatsApp connector"
if errorlevel 1 goto :error
echo      OK
echo.

echo ==============================
echo   Update completed!
echo ==============================
echo.
goto :done

:restart_nssm_service
if "%~1"=="" (
    echo [ERROR] Service name is empty for %~2
    exit /b 1
)
set "SERVICE_STATUS="
set "SERVICE_STATUS_FILE=%TEMP%\nssm_status_%~1.txt"
echo      Restarting %~2 ^(%~1^)...
"%NSSM_EXE%" restart "%~1"
if errorlevel 1 (
    echo      [WARNING] Restart failed, trying stop + start...
    "%NSSM_EXE%" stop "%~1"
    timeout /t 2 /nobreak >nul
    "%NSSM_EXE%" start "%~1"
    if errorlevel 1 (
        echo      [WARNING] Start failed, trying continue...
        "%NSSM_EXE%" continue "%~1"
        if errorlevel 1 (
            echo [ERROR] Service start failed: %~1
            "%NSSM_EXE%" status "%~1"
            exit /b 1
        )
    )
)
timeout /t 2 /nobreak >nul
"%NSSM_EXE%" status "%~1" > "!SERVICE_STATUS_FILE!" 2>&1
if exist "!SERVICE_STATUS_FILE!" (
    set /p SERVICE_STATUS=<"!SERVICE_STATUS_FILE!"
    del /q "!SERVICE_STATUS_FILE!" >nul 2>&1
)
echo      Status: !SERVICE_STATUS!
if /I not "!SERVICE_STATUS!"=="SERVICE_RUNNING" (
    echo [ERROR] Service is not running: %~1 ^(!SERVICE_STATUS!^)
    exit /b 1
)
exit /b 0

:error
echo.
echo ==============================
echo   Update FAILED! Check errors above
echo ==============================

:done
echo.
pause
