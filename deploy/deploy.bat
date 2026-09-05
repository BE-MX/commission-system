chcp 65001 >nul
@echo off
setlocal
title LeShine Ark Platform - Deploy
set PYTHONUTF8=1
set DEPLOY_PYTHON=%~dp0..\backend\.venv\Scripts\python.exe
if not exist "%DEPLOY_PYTHON%" set DEPLOY_PYTHON=python
"%DEPLOY_PYTHON%" "%~dp0publish.py" %*
set DEPLOY_RESULT=%ERRORLEVEL%
if not "%DEPLOY_RESULT%"=="0" echo Deployment failed. See the platform and stage above.
exit /b %DEPLOY_RESULT%
