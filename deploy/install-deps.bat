@echo off
chcp 65001 >nul
title LeShine Ark Platform - Install Deps

echo.
echo ==============================
echo  LeShine Ark Platform - Install Deps
echo  请以管理员身份运行
echo ==============================
echo.

REM ---------- 检查管理员权限 ----------
net session >nul 2>&1
if errorlevel 1 (
    echo [ERROR] 请右键此文件，选择「以管理员身份运行」
    goto :done
)

REM ---------- 检查 winget ----------
where winget >nul 2>&1
if errorlevel 1 (
    echo [ERROR] 未找到 winget，请先更新「应用安装程序」
    echo   Microsoft Store 搜索「应用安装程序」并更新即可
    goto :done
)

REM ---------- 安装 Git ----------
echo [1/4] Git...
where git >nul 2>&1
if errorlevel 1 (
    winget install --id Git.Git -e --accept-package-agreements --accept-source-agreements
    if errorlevel 1 (
        echo [ERROR] Git 安装失败
        goto :done
    )
    echo Git 已安装
) else (
    echo 已存在，跳过
)

REM ---------- 安装 Python 3.12 ----------
echo.
echo [2/4] Python 3.12...
where python >nul 2>&1
if errorlevel 1 (
    winget install --id Python.Python.3.12 -e --accept-package-agreements --accept-source-agreements
    if errorlevel 1 (
        echo [ERROR] Python 安装失败
        goto :done
    )
    echo Python 已安装
) else (
    echo 已存在，跳过
)

REM ---------- 安装 Node.js 20 LTS ----------
echo.
echo [3/4] Node.js 20 LTS...
where node >nul 2>&1
if errorlevel 1 (
    winget install --id OpenJS.NodeJS.LTS -e --accept-package-agreements --accept-source-agreements
    if errorlevel 1 (
        echo [ERROR] Node.js 安装失败
        goto :done
    )
    echo Node.js 已安装
) else (
    echo 已存在，跳过
)

REM ---------- 安装 nssm ----------
echo.
echo [4/4] NSSM (Windows 服务管理)...
where nssm >nul 2>&1
if errorlevel 1 (
    winget install --id NSSM.NSSM -e --accept-package-agreements --accept-source-agreements
    if errorlevel 1 (
        echo [WARNING] nssm 自动安装失败，可手动下载: https://nssm.cc/download
        echo   下载后将 nssm.exe 放到 PATH 目录中即可
    ) else (
        echo NSSM 已安装
    )
) else (
    echo 已存在，跳过
)

REM ---------- 刷新 PATH ----------
echo.
echo 刷新环境变量...
set "PATH=%SystemRoot%;%SystemRoot%\System32;%ProgramFiles%\Git\cmd;%LocalAppData%\Programs\Python\Python312;%LocalAppData%\Programs\Python\Python312\Scripts;%ProgramFiles%\nodejs"

REM ---------- 验证 ----------
echo.
echo ==============================
echo  验证安装结果
echo ==============================
echo.

where git >nul 2>&1 && (git --version) || echo [FAIL] Git 未就绪，请重启终端后重试
where python >nul 2>&1 && (python --version) || echo [FAIL] Python 未就绪，请重启终端后重试
where node >nul 2>&1 && (node --version & npm --version) || echo [FAIL] Node.js 未就绪，请重启终端后重试
where nssm >nul 2>&1 && (echo nssm OK) || echo [WARN] nssm 未就绪，部署脚本会给出手动注册命令

echo.
echo ==============================
echo  安装完成! 下一步:
echo  运行 deploy\setup-server.bat
echo ==============================

:done
echo.
pause
