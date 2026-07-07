@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
title LeShine Ark Platform - Rollback
REM ============================================================
REM  一键回滚到上次部署快照（B-9）
REM  前提：deploy.bat 的 [0/7] 已生成 .deploy_state 快照
REM  回滚内容：代码 → 上次部署 commit；dist → 上次构建产物；重启服务
REM  数据库不回滚（RDS 自动备份兜底，迁移问题单独处理）
REM ============================================================

set "INSTALL_DIR=D:\commission-system"
set "SERVICE_NAME=CommissionSystem"
set "NSSM_EXE=%USERPROFILE%\AppData\Local\Microsoft\WinGet\Links\nssm.exe"
set "CLOUD_SERVER=root@119.28.107.92"
set "CLOUD_DIST=/var/www/ark/dist"

echo.
echo ==============================
echo   Ark Rollback
echo ==============================
echo.

if not exist "%INSTALL_DIR%\.deploy_state\last_deploy_commit.txt" (
    echo [ERROR] 没有部署快照（.deploy_state\last_deploy_commit.txt 不存在）
    echo         先至少跑过一次新版 deploy.bat 才有回滚锚点
    goto :error
)
set /p LAST_COMMIT=<"%INSTALL_DIR%\.deploy_state\last_deploy_commit.txt"
echo 将回滚到上次部署 commit: %LAST_COMMIT%
echo 按 Ctrl+C 取消，任意键继续...
pause >nul

REM ---------- [1/4] 代码回滚 ----------
echo [1/4] Git checkout %LAST_COMMIT% ...
cd /d "%INSTALL_DIR%"
git checkout %LAST_COMMIT%
if errorlevel 1 (
    echo [ERROR] git checkout 失败（工作区有未提交改动？先 git stash）
    goto :error
)
echo      OK ^(detached HEAD, 恢复最新代码用 git checkout main^)
echo.

REM ---------- [2/4] 恢复 dist ----------
echo [2/4] Restore dist backup...
if exist "%INSTALL_DIR%\.deploy_state\dist_backup" (
    if exist "%INSTALL_DIR%\frontend\dist" rmdir /s /q "%INSTALL_DIR%\frontend\dist"
    xcopy /e /i /q /y "%INSTALL_DIR%\.deploy_state\dist_backup" "%INSTALL_DIR%\frontend\dist" >nul
    echo      OK
) else (
    echo      [WARNING] 无 dist 备份，跳过（前端保持当前版本）
)
echo.

REM ---------- [3/4] 同步 dist 到云端 ----------
echo [3/4] Sync dist to cloud...
if exist "%INSTALL_DIR%\frontend\dist" (
    scp -r "%INSTALL_DIR%\frontend\dist\*" %CLOUD_SERVER%:%CLOUD_DIST%/
    if errorlevel 1 (
        echo      [WARNING] scp 失败，云端前端可能仍是新版本
    ) else (
        echo      OK
    )
)
echo.

REM ---------- [4/4] 重启服务 ----------
echo [4/4] Restart service...
"%NSSM_EXE%" restart "%SERVICE_NAME%"
if errorlevel 1 (
    "%NSSM_EXE%" stop "%SERVICE_NAME%"
    timeout /t 2 /nobreak >nul
    "%NSSM_EXE%" start "%SERVICE_NAME%"
)
timeout /t 2 /nobreak >nul
"%NSSM_EXE%" status "%SERVICE_NAME%"
echo.
echo ==============================
echo   Rollback completed
echo   注意：数据库迁移未回滚；若新版本跑过迁移且不兼容旧代码，
echo   需人工评估（查 alembic current 与 RDS 备份）
echo ==============================
goto :done

:error
echo.
echo ==============================
echo   Rollback FAILED
echo ==============================

:done
echo.
pause
