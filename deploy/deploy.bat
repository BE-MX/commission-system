@echo off
chcp 65001 >nul
REM ============================================================
REM  Commission System - 日常更新脚本
REM  每次本机开发完 push 后，在服务器上双击运行
REM ============================================================

set "INSTALL_DIR=D:\commission-system"
set "SERVICE_NAME=CommissionSystem"

echo.
echo === 开始更新 ===
echo.

REM ---------- 拉取最新代码 ----------
echo [1/4] 拉取代码...
cd /d "%INSTALL_DIR%"
git pull
if errorlevel 1 (
    echo ERROR: git pull 失败
    pause
    exit /b 1
)

REM ---------- 后端依赖 ----------
echo.
echo [2/4] 更新后端依赖...
cd /d "%INSTALL_DIR%\backend"
call .venv\Scripts\activate.bat
pip install -r requirements.txt -q

REM ---------- 数据库迁移 ----------
echo.
echo [3/4] 数据库迁移...
alembic upgrade head

REM ---------- 前端构建 ----------
echo.
echo [4/4] 构建前端...
cd /d "%INSTALL_DIR%\frontend"
call npm install --silent
call npm run build

REM ---------- 重启服务 ----------
echo.
echo 重启服务...
nssm restart %SERVICE_NAME%

echo.
echo === 更新完成 ===
echo.
pause
