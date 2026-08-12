chcp 65001 >nul
@echo off
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
set "CLOUD_PM_DIST=/var/www/pm/dist"
set "BACKEND_RESTARTED_AFTER_MIGRATION=0"
REM All ssh/scp go through these opts (2026-07-13): BatchMode turns any interactive
REM prompt (host key / password) into an immediate error instead of a silent hang;
REM ConnectionAttempts retries transient port-22 timeouts; the other options bound hangs.
set "SSH_OPTS=-o BatchMode=yes -o ConnectTimeout=10 -o ConnectionAttempts=3 -o ServerAliveInterval=15 -o ServerAliveCountMax=4"

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
REM Fail before migration/service restart when invoice PDF Chinese font is unavailable.
.\.venv\Scripts\python.exe -m app.invoice.pdf_font
if errorlevel 1 (
    echo [ERROR] Invoice PDF CJK font preflight failed
    echo         Set PDF_CJK_FONT_PATH in backend\.env to an existing Chinese .ttf/.ttc font
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
echo      Stopping Ark backend to prevent writes during migration...
"%NSSM_EXE%" stop "%SERVICE_NAME%"
if errorlevel 1 (
    echo [ERROR] Failed to stop %SERVICE_NAME%; migration was not started
    goto :error
)
.\.venv\Scripts\python.exe -m alembic upgrade head
if errorlevel 1 (
    echo [ERROR] alembic migration failed; %SERVICE_NAME% remains stopped to protect data
    goto :error
)
REM Migration validation
for /f "delims=" %%V in ('.\.venv\Scripts\python.exe -m alembic current 2^>nul') do set "CURRENT_REVISION=%%V"
echo      Current revision: %CURRENT_REVISION%
if "%CURRENT_REVISION%"=="" (
    echo [ERROR] Failed to read current migration revision; %SERVICE_NAME% remains stopped to protect data
    goto :error
)
call :restart_nssm_service "%SERVICE_NAME%" "Ark backend"
if errorlevel 1 goto :error
set "BACKEND_RESTARTED_AFTER_MIGRATION=1"
REM PM 协作站预置数据（幂等：已存在自动跳过，--reset 需手动执行）
.\.venv\Scripts\python.exe scripts\seed_pm.py
if errorlevel 1 (
    echo [ERROR] PM seed failed
    goto :error
)
.\.venv\Scripts\python.exe scripts\import_pantone.py
if errorlevel 1 (
    echo [ERROR] Pantone Solid Coated import failed
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
    goto :pm_hub_sync
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
    call :rsync_sync
    if not errorlevel 1 (
        set "SYNC_OK=1"
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
goto :pm_hub_sync

:rsync_sync
REM 2026-07-26: 两趟同步，index.html 必须最后翻（原子切换）。
REM 起因：2026-07-25 22:04 index.html 先落地、22:16-22:37 才传 assets，其中一个
REM assets 上传失败 → 线上 index.html 指向不存在的 CSS，生产站无样式近 2 小时。
REM --delete 不会删被 --exclude 保护的 index.html，所以失败时云端保持旧页面可用。
cd /d "%INSTALL_DIR%\frontend"
rsync -avz --delete --exclude=index.html --chmod=D755,F644 -e "ssh %SSH_OPTS%" dist/ %CLOUD_SERVER%:%CLOUD_DIST%/
if errorlevel 1 exit /b 1
rsync -avz --chmod=F644 -e "ssh %SSH_OPTS%" dist/index.html %CLOUD_SERVER%:%CLOUD_DIST%/index.html
if errorlevel 1 (
    echo [ERROR] assets synced OK but index.html flip FAILED - cloud still serves the previous page
    exit /b 1
)
echo      OK
exit /b 0

:scp_smart
REM 利用 git diff + 远端存在性检查，只传变化的文件
set "SMART_FAIL=0"
cd /d "%INSTALL_DIR%\frontend\dist"
REM m/ is small (<1MB), always upload
scp %SSH_OPTS% -r m %CLOUD_SERVER%:%CLOUD_DIST%/ >nul
if errorlevel 1 echo      [WARNING] m/ upload failed ^(mobile pages may be stale^) - not fatal
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
REM 同步其余 public 顶层项（festival/card/expo-sales/6010/caigoujie/logo.webp 等）。
REM 2026-08-03 根因：无 rsync 的生产机固定走本分支，但旧逻辑只传 m/vendor/assets/index，
REM 新增的 festival/ 被静默漏传，/festival/ 因 nginx SPA fallback 错返主站首页。
for /f "delims=" %%E in ('dir /b') do (
    set "STATIC_ITEM_SKIP=0"
    if /i "%%E"=="assets" set "STATIC_ITEM_SKIP=1"
    if /i "%%E"=="index.html" set "STATIC_ITEM_SKIP=1"
    if /i "%%E"=="m" set "STATIC_ITEM_SKIP=1"
    if /i "%%E"=="vendor" set "STATIC_ITEM_SKIP=1"
    if "!STATIC_ITEM_SKIP!"=="0" (
        set "STATIC_ITEM_CHANGED=0"
        if not defined FRONTEND_BASE set "STATIC_ITEM_CHANGED=1"
        if defined FRONTEND_BASE (
            git -C "%INSTALL_DIR%" diff --name-only %FRONTEND_BASE% HEAD -- "frontend/public/%%E" 2>nul | findstr /R "." >nul 2>&1
            if not errorlevel 1 set "STATIC_ITEM_CHANGED=1"
        )
        git -C "%INSTALL_DIR%" diff --name-only -- "frontend/public/%%E" 2>nul | findstr /R "." >nul 2>&1
        if not errorlevel 1 set "STATIC_ITEM_CHANGED=1"
        if "!STATIC_ITEM_CHANGED!"=="0" (
            ssh %SSH_OPTS% %CLOUD_SERVER% "test -e %CLOUD_DIST%/%%E" >nul 2>&1
            if errorlevel 1 set "STATIC_ITEM_CHANGED=1"
        )
        if "!STATIC_ITEM_CHANGED!"=="1" (
            echo      Uploading static item %%E...
            scp %SSH_OPTS% -r "%%E" %CLOUD_SERVER%:%CLOUD_DIST%/
            if errorlevel 1 set "SMART_FAIL=1"
        ) else (
            echo      Static item %%E unchanged, skipped
        )
    )
)
REM 2026-07-26: assets 整目录一次传完，取代原来的 md5 逐文件比对。
REM 实测一次 build = 211 文件 / 5.2MB，其中 193 个 / 4.0MB 是新 hash——vite 每次 build
REM 都换文件名，"只传变化的"只省 23% 流量，却要开 191 条 SSH 连接、跑 27 分钟，
REM 且每条连接都是一次失败机会（2026-07-25 就是其中一条挂了）。
echo      Uploading assets in one connection...
ssh %SSH_OPTS% %CLOUD_SERVER% "rm -rf %CLOUD_DIST%/assets.new %CLOUD_DIST%/index.html.new"
scp %SSH_OPTS% -r assets %CLOUD_SERVER%:%CLOUD_DIST%/assets.new
if errorlevel 1 set "SMART_FAIL=1"
scp %SSH_OPTS% index.html %CLOUD_SERVER%:%CLOUD_DIST%/index.html.new
if errorlevel 1 set "SMART_FAIL=1"
if "!SMART_FAIL!"=="0" (
    REM Flip assets and index.html together to avoid a mixed-version window.
    REM Keep the previous assets as assets.old until the next deploy for rollback.
    REM If needed, restore assets.old over SSH.
    echo      Switching cloud to the new build...
    ssh %SSH_OPTS% %CLOUD_SERVER% "cd %CLOUD_DIST% && rm -rf assets.old; mv assets assets.old 2>/dev/null; mv assets.new assets && mv index.html.new index.html"
    if errorlevel 1 (
        echo [ERROR] remote switch FAILED - cloud still serves the previous page
        set "SMART_FAIL=1"
    ) else (
        echo      OK
    )
) else (
    echo      [SKIP] switch aborted - cloud keeps serving the previous page
    ssh %SSH_OPTS% %CLOUD_SERVER% "rm -rf %CLOUD_DIST%/assets.new %CLOUD_DIST%/index.html.new" >nul
)
exit /b !SMART_FAIL!

:scp_full
echo      Full scp sync...
REM 显式回到 frontend：从 :scp_smart 回退进来时 CWD 在 dist 里，dist/* 会失配
cd /d "%INSTALL_DIR%\frontend"
if not exist "dist\index.html" (
    echo [ERROR] dist\index.html missing - build did not produce a dist
    exit /b 1
)
set "FULL_FAIL=0"
REM 逐个顶层项上传，index.html 留到最后（原子切换，同 :rsync_sync 的理由）
for /f "delims=" %%E in ('dir /b dist') do (
    if /i not "%%E"=="index.html" (
        scp %SSH_OPTS% -r "dist/%%E" %CLOUD_SERVER%:%CLOUD_DIST%/
        if errorlevel 1 (
            echo [WARNING] scp failed: %%E
            set "FULL_FAIL=1"
        )
    )
)
if "!FULL_FAIL!"=="1" (
    echo [WARNING] SCP sync failed - index.html NOT updated, cloud keeps serving the previous page
    exit /b 1
)
scp %SSH_OPTS% dist/index.html %CLOUD_SERVER%:%CLOUD_DIST%/index.html
if errorlevel 1 (
    echo [ERROR] assets synced OK but index.html flip FAILED - cloud still serves the previous page
    exit /b 1
)
echo      OK
exit /b 0

:pm_hub_sync
REM ---------- PM Hub (frontend-pm) 构建 + 同步（独立站点 pm.leshine.work） ----------
if not exist "%INSTALL_DIR%\frontend-pm\package.json" (
    echo [PM] frontend-pm not present, skipped
    goto :restart_service
)
set "PM_CHANGED=0"
set "PM_MARKER=%INSTALL_DIR%\.deploy_state\pm_build_commit.txt"
set "PM_BASE="
if exist "%PM_MARKER%" set /p PM_BASE=<"%PM_MARKER%"
if not defined PM_BASE (
    set "PM_CHANGED=1"
) else (
    git diff --name-only %PM_BASE% HEAD -- frontend-pm/ 2>nul | findstr /R "." >nul 2>&1
    if not errorlevel 1 set "PM_CHANGED=1"
)
REM 未提交的本地改动也触发构建
git diff --name-only -- frontend-pm/ 2>nul | findstr /R "." >nul 2>&1
if not errorlevel 1 set "PM_CHANGED=1"
if "%PM_CHANGED%"=="0" (
    echo [PM] frontend-pm unchanged, skipped
    goto :restart_service
)
echo [PM] Build frontend-pm...
cd /d "%INSTALL_DIR%\frontend-pm"
call npm install --silent
if errorlevel 1 (
    echo [ERROR] frontend-pm npm install failed
    goto :error
)
call npm run build
if errorlevel 1 (
    echo [ERROR] frontend-pm build failed
    goto :error
)
ssh %SSH_OPTS% %CLOUD_SERVER% "mkdir -p %CLOUD_PM_DIST%"
echo [PM] Sync dist to %CLOUD_SERVER%:%CLOUD_PM_DIST% ...
scp %SSH_OPTS% -r dist/* %CLOUD_SERVER%:%CLOUD_PM_DIST%/
if errorlevel 1 (
    echo [ERROR] PM dist sync FAILED - marker left unchanged so the next deploy retries
    goto :error
)
REM 内网入口构建（base=/pm/），本机后端托管，供局域网大文件上传绕开 frp 隧道
REM 放在云端 scp 之后：LAN 构建失败不连累外网 pm.leshine.work 部署（marker 未写，下次一并重试）
echo [PM] Build LAN entry (dist-lan, base=/pm/)...
call npm run build -- --base=/pm/ --outDir dist-lan
if errorlevel 1 (
    echo [ERROR] frontend-pm LAN build failed
    goto :error
)
for /f "delims=" %%H in ('git -C "%INSTALL_DIR%" rev-parse HEAD') do set "CURRENT_HEAD=%%H"
echo !CURRENT_HEAD!>"%PM_MARKER%"
echo      OK
echo.

:restart_service
REM ---------- [7/7] Restart services ----------
echo [7/7] Restart services...
if "%BACKEND_RESTARTED_AFTER_MIGRATION%"=="1" (
    echo      Ark backend already restarted after migration
) else (
    call :restart_nssm_service "%SERVICE_NAME%" "Ark backend"
    if errorlevel 1 goto :error
)
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
