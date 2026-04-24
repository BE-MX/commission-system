@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
REM ============================================================
REM  Commission System - 首次部署脚本
REM  在服务器上以管理员身份运行一次即可
REM ============================================================

echo.
echo ==============================
echo  Commission System 服务器部署
echo ==============================
echo.

REM ---------- 配置区 ----------
set "INSTALL_DIR=D:\commission-system"
set "GIT_REPO=https://github.com/BE-MX/commission-system.git"
set "SERVICE_NAME=CommissionSystem"
set "PORT=8001"

REM ---------- 检查依赖 ----------
echo [1/6] 检查依赖...

where git >nul 2>&1
if errorlevel 1 (
    echo [ERROR] 未安装 Git, 请先安装
    goto :error
)

where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] 未安装 Python, 请先安装 Python 3.12
    goto :error
)

where node >nul 2>&1
if errorlevel 1 (
    echo [ERROR] 未安装 Node.js, 请先安装 Node.js 20
    goto :error
)

python --version
node --version
echo OK.

REM ---------- 克隆代码 ----------
echo.
echo [2/6] 克隆代码...
if exist "%INSTALL_DIR%\.git" (
    echo 已存在，跳过克隆
) else (
    git clone %GIT_REPO% "%INSTALL_DIR%"
    if errorlevel 1 (
        echo [ERROR] 代码克隆失败，请检查网络或仓库地址
        goto :error
    )
)

REM ---------- 后端环境 ----------
echo.
echo [3/6] 初始化后端...
cd /d "%INSTALL_DIR%\backend"
if errorlevel 1 (
    echo [ERROR] 目录 %INSTALL_DIR%\backend 不存在
    goto :error
)

if not exist ".venv" (
    python -m venv .venv
    if errorlevel 1 (
        echo [ERROR] 虚拟环境创建失败
        goto :error
    )
    echo 虚拟环境已创建
)

call .venv\Scripts\activate.bat
if errorlevel 1 (
    echo [ERROR] 虚拟环境激活失败
    goto :error
)

pip install -r requirements.txt -q
if errorlevel 1 (
    echo [ERROR] 后端依赖安装失败
    goto :error
)
echo 后端依赖已安装

REM ---------- 配置 .env ----------
if not exist ".env" (
    copy .env.example .env
    echo.
    echo !! 请编辑 %INSTALL_DIR%\backend\.env 填入数据库连接信息 !!
    echo.
    notepad "%INSTALL_DIR%\backend\.env"
)

REM ---------- 数据库迁移 ----------
echo.
echo [4/6] 数据库迁移...
alembic upgrade head
if errorlevel 1 (
    echo [ERROR] 数据库迁移失败，请检查 .env 中的数据库连接配置
    goto :error
)

REM ---------- 前端构建 ----------
echo.
echo [5/6] 构建前端...
cd /d "%INSTALL_DIR%\frontend"
if errorlevel 1 (
    echo [ERROR] 目录 %INSTALL_DIR%\frontend 不存在
    goto :error
)

call npm install --silent
if errorlevel 1 (
    echo [ERROR] 前端依赖安装失败
    goto :error
)

call npm run build
if errorlevel 1 (
    echo [ERROR] 前端构建失败
    goto :error
)
echo 前端构建完成

REM ---------- 注册 Windows 服务 ----------
echo.
echo [6/6] 注册 Windows 服务...

where nssm >nul 2>&1
if errorlevel 1 (
    echo.
    echo !! nssm 未安装，请手动下载: https://nssm.cc/download !!
    echo 下载后将 nssm.exe 放到 PATH 中，然后运行:
    echo.
    echo   nssm install %SERVICE_NAME% "%INSTALL_DIR%\backend\.venv\Scripts\uvicorn.exe"
    echo   nssm set %SERVICE_NAME% AppParameters "app.main:app --host 0.0.0.0 --port %PORT%"
    echo   nssm set %SERVICE_NAME% AppDirectory "%INSTALL_DIR%\backend"
    echo   nssm set %SERVICE_NAME% AppStdout "%INSTALL_DIR%\logs\service.log"
    echo   nssm set %SERVICE_NAME% AppStderr "%INSTALL_DIR%\logs\service.log"
    echo   nssm set %SERVICE_NAME% AppRotateFiles 1
    echo   nssm set %SERVICE_NAME% AppRotateBytes 10485760
    echo   nssm start %SERVICE_NAME%
    echo.
) else (
    if not exist "%INSTALL_DIR%\logs" mkdir "%INSTALL_DIR%\logs"

    nssm install %SERVICE_NAME% "%INSTALL_DIR%\backend\.venv\Scripts\uvicorn.exe"
    nssm set %SERVICE_NAME% AppParameters "app.main:app --host 0.0.0.0 --port %PORT%"
    nssm set %SERVICE_NAME% AppDirectory "%INSTALL_DIR%\backend"
    nssm set %SERVICE_NAME% AppStdout "%INSTALL_DIR%\logs\service.log"
    nssm set %SERVICE_NAME% AppStderr "%INSTALL_DIR%\logs\service.log"
    nssm set %SERVICE_NAME% AppRotateFiles 1
    nssm set %SERVICE_NAME% AppRotateBytes 10485760
    nssm start %SERVICE_NAME%
    echo 服务已注册并启动
)

echo.
echo ==============================
echo  部署完成!
echo  访问: http://localhost:%PORT%
echo ==============================
goto :done

:error
echo.
echo ==============================
echo  部署失败! 请根据上方错误信息排查
echo ==============================

:done
echo.
pause
