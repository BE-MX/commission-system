@echo off
chcp 65001 >nul
setlocal
title LeShine Ark - Uploads Backup
REM ============================================================
REM  素材与上传文件每日镜像备份（B-9 / 架构评估 S7）
REM  备份对象：
REM    1) %INSTALL_DIR%\uploads      设计附件/头像/日报HTML/expo客户照片
REM    2) D:\WORKSOURCE              素材中台全部文件（取代钉钉网盘的资产）
REM  目标盘 BACKUP_ROOT 需指向另一块物理盘或 NAS，首次使用前确认！
REM
REM  注册每晚 02:30 计划任务（管理员 cmd 执行一次）：
REM    schtasks /create /tn ArkUploadsBackup /tr "D:\commission-system\deploy\backup-uploads.bat" /sc daily /st 02:30 /ru SYSTEM
REM ============================================================

set "INSTALL_DIR=D:\commission-system"
set "BACKUP_ROOT=E:\ark_backup"
set "LOG_FILE=%INSTALL_DIR%\.deploy_state\backup.log"

if not exist "%INSTALL_DIR%\.deploy_state" mkdir "%INSTALL_DIR%\.deploy_state"
echo [%date% %time%] backup start >> "%LOG_FILE%"

if not exist "%BACKUP_ROOT%\" (
    echo [%date% %time%] [ERROR] BACKUP_ROOT %BACKUP_ROOT% 不存在，请先修改本脚本指向备份盘 >> "%LOG_FILE%"
    echo [ERROR] 备份目标 %BACKUP_ROOT% 不存在——编辑本脚本 BACKUP_ROOT 指向另一块物理盘/NAS
    exit /b 1
)

REM robocopy /MIR 镜像；退出码 <8 均为成功（0=无变化 1=有复制 ...）
robocopy "%INSTALL_DIR%\uploads" "%BACKUP_ROOT%\uploads" /MIR /R:2 /W:5 /NP /NFL /NDL >> "%LOG_FILE%" 2>&1
set "RC1=%ERRORLEVEL%"
robocopy "D:\WORKSOURCE" "%BACKUP_ROOT%\WORKSOURCE" /MIR /R:2 /W:5 /NP /NFL /NDL >> "%LOG_FILE%" 2>&1
set "RC2=%ERRORLEVEL%"

if %RC1% GEQ 8 goto :fail
if %RC2% GEQ 8 goto :fail
echo [%date% %time%] backup OK (uploads rc=%RC1%, worksource rc=%RC2%) >> "%LOG_FILE%"
exit /b 0

:fail
echo [%date% %time%] [ERROR] backup FAILED (uploads rc=%RC1%, worksource rc=%RC2%) >> "%LOG_FILE%"
exit /b 1
