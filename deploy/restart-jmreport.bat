@echo off
chcp 65001 >nul
title LeShine JimuReport - Restart

set SERVICE_NAME=LeShineJmReport

echo.
echo ==============================
echo   LeShine JimuReport - Restart
echo ==============================
echo.

REM Stop service
echo [1/2] Stopping service...
nssm stop %SERVICE_NAME%
timeout /t 5 /nobreak >nul

REM Start service
echo [2/2] Starting service...
nssm start %SERVICE_NAME%
if errorlevel 1 (
    echo [ERROR] Start failed. Run: nssm status %SERVICE_NAME%
    goto :done
)

echo.
echo Waiting 15s for JVM warm-up...
timeout /t 15 /nobreak >nul

echo.
echo ==============================
echo   Restart OK
echo   Check: nssm status %SERVICE_NAME%
echo ==============================

:done
echo.
pause
