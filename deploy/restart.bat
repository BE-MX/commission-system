@echo off
chcp 65001 >nul
title LeShine Ark Platform - Restart

set SERVICE_NAME=CommissionSystem

echo.
echo ==============================
echo   LeShine Ark - Restart
echo ==============================
echo.

REM Stop service
echo [1/2] Stopping service...
nssm stop %SERVICE_NAME%
timeout /t 3 /nobreak >nul

REM Start service
echo [2/2] Starting service...
nssm start %SERVICE_NAME%
if errorlevel 1 (
    echo [ERROR] Start failed. Run: nssm status %SERVICE_NAME%
    goto :done
)

echo.
echo ==============================
echo   Restart OK
echo   Permissions seed reloaded
echo ==============================

:done
echo.
pause
