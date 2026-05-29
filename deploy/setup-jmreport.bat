@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
REM ============================================================
REM  LeShine Ark - JimuReport Service First Setup
REM  在服务器上以管理员身份运行一次即可注册 NSSM 服务
REM
REM  前置条件：
REM    1. 已克隆 commission-system 仓库到 %INSTALL_DIR%
REM    2. 已安装 JDK 17+ 与 Maven 3.9+
REM    3. backend\.env 已配好（脚本会从中读取 JWT_SECRET / DB_*）
REM    4. 腾讯云 jimureport 库已初始化（参考 jmreport-service\sql\import.py）
REM ============================================================

echo.
echo ==============================
echo  LeShine Ark - JimuReport Setup
echo ==============================
echo.

REM ---------- 配置区 ----------
set "INSTALL_DIR=D:\commission-system"
set "SERVICE_NAME=LeShineJmReport"
set "PORT=8888"
set "JM_DIR=%INSTALL_DIR%\jmreport-service"
set "JAR_NAME=jimureport-example-2.3.jar"

REM ---------- 检查依赖 ----------
echo [1/5] 检查依赖...

where java >nul 2>&1
if errorlevel 1 (
    echo [ERROR] 未找到 java，请先安装 JDK 17 并配置 PATH
    goto :error
)

where mvn >nul 2>&1
if errorlevel 1 (
    echo [ERROR] 未找到 mvn，请先安装 Maven 并配置 PATH
    goto :error
)

where nssm >nul 2>&1
if errorlevel 1 (
    echo [ERROR] 未找到 nssm，请下载 https://nssm.cc/download 并加入 PATH
    goto :error
)

if not exist "%JM_DIR%\pom.xml" (
    echo [ERROR] 目录 %JM_DIR% 不存在，先 git clone commission-system
    goto :error
)

if not exist "%INSTALL_DIR%\backend\.env" (
    echo [ERROR] %INSTALL_DIR%\backend\.env 不存在，需先配置方舟后端
    goto :error
)

java -version
mvn -version
echo OK.

REM ---------- 读取方舟 .env 中的密钥与数据库凭证 ----------
echo.
echo [2/5] 从 backend\.env 读取凭证...
for /f "tokens=2 delims==" %%a in ('findstr /b "JWT_SECRET_KEY=" "%INSTALL_DIR%\backend\.env"') do set "ARK_JWT_SECRET=%%a"
for /f "tokens=2 delims==" %%a in ('findstr /b "COMMISSION_DB_HOST=" "%INSTALL_DIR%\backend\.env"') do set "DB_HOST=%%a"
for /f "tokens=2 delims==" %%a in ('findstr /b "COMMISSION_DB_PORT=" "%INSTALL_DIR%\backend\.env"') do set "DB_PORT=%%a"
for /f "tokens=2 delims==" %%a in ('findstr /b "COMMISSION_DB_USER=" "%INSTALL_DIR%\backend\.env"') do set "DB_USER=%%a"
for /f "tokens=2 delims==" %%a in ('findstr /b "COMMISSION_DB_PASSWORD=" "%INSTALL_DIR%\backend\.env"') do set "DB_PASS=%%a"

if "%ARK_JWT_SECRET%"=="" (
    echo [ERROR] 在 backend\.env 中未找到 JWT_SECRET_KEY
    goto :error
)
if "%DB_HOST%"=="" (
    echo [ERROR] 在 backend\.env 中未找到 COMMISSION_DB_HOST
    goto :error
)
echo 凭证已读取

REM ---------- Maven 打包 ----------
echo.
echo [3/5] Maven 打包（首次会拉 jeecg 私服依赖，约 5-10 分钟）...
cd /d "%JM_DIR%"
call mvn -B -q package -DskipTests
if errorlevel 1 (
    echo [ERROR] mvn package 失败
    goto :error
)
if not exist "target\%JAR_NAME%" (
    echo [ERROR] 找不到 target\%JAR_NAME%
    goto :error
)
echo 打包完成

REM ---------- 准备日志目录 ----------
if not exist "%INSTALL_DIR%\logs\jmreport" mkdir "%INSTALL_DIR%\logs\jmreport"
if not exist "%JM_DIR%\logs" mkdir "%JM_DIR%\logs"

REM ---------- 注册 NSSM 服务 ----------
echo.
echo [4/5] 注册 NSSM 服务 %SERVICE_NAME%...

REM 先删旧服务（如果存在）
nssm status %SERVICE_NAME% >nul 2>&1
if not errorlevel 1 (
    echo 已存在同名服务，先删除...
    nssm stop %SERVICE_NAME% >nul 2>&1
    nssm remove %SERVICE_NAME% confirm >nul 2>&1
)

REM 找到 java.exe 的绝对路径（NSSM 不读 PATH）
for /f "delims=" %%j in ('where java') do (
    set "JAVA_EXE=%%j"
    goto :found_java
)
:found_java

REM Application = java.exe
nssm install %SERVICE_NAME% "%JAVA_EXE%"

REM AppParameters：JVM 参数 + jar
REM   敏感值通过 AppEnvironmentExtra 注入，不进命令行
nssm set %SERVICE_NAME% AppParameters "-Xms512m -Xmx1024m -Dspring.profiles.active=prod -DMYSQL-HOST=%DB_HOST% -DMYSQL-PORT=%DB_PORT% -DMYSQL-DB=jimureport -jar target\%JAR_NAME%"

REM AppDirectory：相对路径里的 target\ 由它解析
nssm set %SERVICE_NAME% AppDirectory "%JM_DIR%"

REM 敏感值走环境变量
nssm set %SERVICE_NAME% AppEnvironmentExtra "ARK_JWT_SECRET=%ARK_JWT_SECRET%" "spring.datasource.username=%DB_USER%" "spring.datasource.password=%DB_PASS%"

REM 日志
nssm set %SERVICE_NAME% AppStdout "%INSTALL_DIR%\logs\jmreport\service.log"
nssm set %SERVICE_NAME% AppStderr "%INSTALL_DIR%\logs\jmreport\service.log"
nssm set %SERVICE_NAME% AppRotateFiles 1
nssm set %SERVICE_NAME% AppRotateBytes 20971520
nssm set %SERVICE_NAME% AppRotateOnline 1

REM 启动设置
nssm set %SERVICE_NAME% Start SERVICE_AUTO_START
nssm set %SERVICE_NAME% AppStopMethodSkip 6
nssm set %SERVICE_NAME% AppStopMethodConsole 30000
nssm set %SERVICE_NAME% AppExit Default Restart
nssm set %SERVICE_NAME% AppRestartDelay 5000

echo 服务已注册

REM ---------- 启动服务 ----------
echo.
echo [5/5] 启动服务...
nssm start %SERVICE_NAME%
if errorlevel 1 (
    echo [WARN] 启动可能失败，30 秒后再用 nssm status %SERVICE_NAME% 检查
)

echo.
echo 等待 20 秒让 JVM 完成启动...
timeout /t 20 /nobreak >nul

echo.
echo ==============================
echo  JimuReport 部署完成
echo  服务名: %SERVICE_NAME%
echo  端口:   %PORT%
echo  访问:   http://localhost:%PORT%/jmreport/list
echo  日志:   %INSTALL_DIR%\logs\jmreport\service.log
echo ==============================
echo.
echo 验证健康：
echo   curl http://localhost:%PORT%/jmreport/list?token=test  ^(应返回 302 或 HTML^)
echo.
goto :done

:error
echo.
echo ==============================
echo  部署失败! 请根据上方错误信息排查
echo ==============================

:done
echo.
pause
endlocal
