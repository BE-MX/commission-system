@echo off
chcp 65001 >nul
title Commission System Launcher

echo ========================================
echo   提成管理系统 - 启动中...
echo ========================================
echo.

start "Backend - FastAPI :8001" cmd /k "cd /d %~dp0backend && call .venv\Scripts\activate && uvicorn app.main:app --reload --port 8001"

timeout /t 3 /nobreak >nul

start "Frontend - Vue :3000" cmd /k "cd /d %~dp0frontend && npm run dev"

timeout /t 5 /nobreak >nul

echo   后端 API:  http://localhost:8001
echo   前端页面:  http://localhost:3000
echo.
echo   正在打开浏览器...
start http://localhost:3000

echo   关闭服务请直接关闭对应的命令行窗口
echo ========================================
