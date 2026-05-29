@echo off
setlocal enabledelayedexpansion
title LeShine JimuReport - Full Setup

set "LOGFILE=%~dp0setup-jmreport.log"
echo ==== JimuReport Setup Start %date% %time% ==== > "%LOGFILE%"

set "INSTALL_DIR=D:\commission-system"
set "SERVICE_NAME=LeShineJmReport"
set "PORT=8888"
set "JM_DIR=%INSTALL_DIR%\jmreport-service"
set "JAR_NAME=jimureport-example-2.3.jar"

echo.
echo ============================================================
echo   LeShine Ark - JimuReport One-Click Setup
echo   Install dir: %INSTALL_DIR%
echo   Service:     %SERVICE_NAME%
echo   Port:        %PORT%
echo   Log:         %LOGFILE%
echo ============================================================
echo.

REM ===== [1/7] Admin check =====
echo [1/7] Check admin privilege...
echo [STEP 1] Admin check >> "%LOGFILE%"
net session >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Please run as Administrator! Right-click -^> Run as administrator
    echo [ERROR] Not admin >> "%LOGFILE%"
    call :fail
)
echo OK.
echo.

REM ===== [2/7] JDK 17+ =====
echo [2/7] Check JDK...
echo [STEP 2] Check JDK >> "%LOGFILE%"

set "JAVA_OK=0"
set "JAVA_VER="
set "JAVA_MAJOR="

where java >nul 2>&1
if errorlevel 1 goto :need_jdk

for /f "tokens=3" %%v in ('java -version 2^>^&1 ^| findstr /i "version"') do set "JAVA_VER=%%v"
set "JAVA_VER=!JAVA_VER:"=!"
echo   Found java !JAVA_VER!
echo   java version = !JAVA_VER! >> "%LOGFILE%"

for /f "tokens=1 delims=._-" %%m in ("!JAVA_VER!") do set "JAVA_MAJOR=%%m"
if "!JAVA_MAJOR!"=="" goto :need_jdk
if !JAVA_MAJOR! GEQ 17 (
    set "JAVA_OK=1"
    echo   Version OK ^>=17^)
) else (
    echo   Version too low, need 17+
    goto :need_jdk
)
goto :jdk_done

:need_jdk
echo   JDK not found or too low, trying auto-install...
where winget >nul 2>&1
if errorlevel 1 (
    echo   [!] winget not available
    echo.
    echo   Please install JDK 17 manually:
    echo   1. Go to: https://adoptium.net/temurin/releases/
    echo   2. Download JDK 17, Windows, x64, .msi
    echo   3. Check "Add to PATH" during install
    echo   4. Open new terminal, run this script again
    echo   winget not available >> "%LOGFILE%"
    call :fail
)
echo   Installing via winget...
winget install --id EclipseAdoptium.Temurin.17.JDK -e --accept-package-agreements --accept-source-agreements >> "%LOGFILE%" 2>&1
if errorlevel 1 (
    echo   [!] winget install failed, please install manually
    echo   winget failed >> "%LOGFILE%"
    call :fail
)
for /f "tokens=2*" %%a in ('reg query "HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment" /v Path 2^>nul') do set "PATH=%%b;!PATH!"
where java >nul 2>&1
if errorlevel 1 (
    echo   [!] java still not found after install, open new terminal and retry
    echo   java not found after winget >> "%LOGFILE%"
    call :fail
)
echo   JDK installed OK

:jdk_done
echo OK.
echo.

REM ===== [3/7] Maven 3.9+ =====
echo [3/7] Check Maven...
echo [STEP 3] Check Maven >> "%LOGFILE%"

set "MAVEN_OK=0"
where mvn >nul 2>&1
if errorlevel 1 goto :need_maven

for /f "tokens=3" %%v in ('mvn -version 2^>^&1 ^| findstr /i "Apache Maven"') do (
    echo   Found Maven %%v
    set "MAVEN_OK=1"
)
goto :maven_done

:need_maven
echo   Maven not found, auto-installing...
set "MAVEN_VER=3.9.8"
set "MAVEN_ZIP=apache-maven-!MAVEN_VER!-bin.zip"
set "MAVEN_URL=https://dlcdn.apache.org/maven/maven-3/!MAVEN_VER!/bin/!MAVEN_ZIP!"
set "MAVEN_DIR=C:\Program Files\apache-maven-!MAVEN_VER!"

if not exist "!MAVEN_DIR!\bin\mvn.cmd" (
    echo   Downloading Maven !MAVEN_VER! ^(9MB^)...
    echo   Trying primary mirror... >> "%LOGFILE%"
    curl -fSL -o "%TEMP%\!MAVEN_ZIP!" "!MAVEN_URL!" >> "%LOGFILE%" 2>&1
    if errorlevel 1 (
        echo   Primary mirror failed, trying archive...
        set "MAVEN_URL2=https://archive.apache.org/dist/maven/maven-3/!MAVEN_VER!/bin/!MAVEN_ZIP!"
        curl -fSL -o "%TEMP%\!MAVEN_ZIP!" "!MAVEN_URL2!" >> "%LOGFILE%" 2>&1
        if errorlevel 1 (
            echo   [!] Both mirrors failed
            echo   Please install manually: https://maven.apache.org/download.cgi
            echo   Maven download failed >> "%LOGFILE%"
            call :fail
        )
    )
    echo   Extracting...
    powershell -NoProfile -Command "Expand-Archive -Path '%TEMP%\!MAVEN_ZIP!' -DestinationPath 'C:\Program Files' -Force" >> "%LOGFILE%" 2>&1
    if errorlevel 1 (
        echo   [!] Extract failed
        echo   Maven extract failed >> "%LOGFILE%"
        call :fail
    )
)

set "PATH=!MAVEN_DIR!\bin;%PATH%"
set "NEED_P=1"
for /f "tokens=2*" %%a in ('reg query "HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment" /v Path 2^>nul') do (
    echo %%b | findstr /i "apache-maven" >nul
    if not errorlevel 1 set "NEED_P=0"
)
if "!NEED_P!"=="1" (
    echo   Adding to PATH...
    for /f "tokens=2*" %%a in ('reg query "HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment" /v Path 2^>nul') do (
        setx /M PATH "%%b;!MAVEN_DIR!\bin" >nul 2>&1
    )
)
where mvn >nul 2>&1
if errorlevel 1 (
    echo   [!] Maven installed but not found, open new terminal and retry
    echo   mvn not found after install >> "%LOGFILE%"
    call :fail
)
echo   Maven installed OK

:maven_done
echo OK.
echo.

REM ===== [4/7] NSSM =====
echo [4/7] Check NSSM...
echo [STEP 4] Check NSSM >> "%LOGFILE%"

where nssm >nul 2>&1
if not errorlevel 1 (
    echo   Already installed
    goto :nssm_done
)

echo   NSSM not found, auto-installing...
set "NSSM_VER=nssm-2.24"
set "NSSM_ZIP=!NSSM_VER!.zip"
set "NSSM_URL=https://nssm.cc/release/!NSSM_ZIP!"
set "NSSM_DIR=C:\Program Files\nssm"

if not exist "!NSSM_DIR!\win64\nssm.exe" (
    echo   Downloading NSSM...
    curl -fSL -o "%TEMP%\!NSSM_ZIP!" "!NSSM_URL!" >> "%LOGFILE%" 2>&1
    if errorlevel 1 (
        echo   [!] Download failed, get it from https://nssm.cc/download
        echo   NSSM download failed >> "%LOGFILE%"
        call :fail
    )
    echo   Extracting...
    powershell -NoProfile -Command "Expand-Archive -Path '%TEMP%\!NSSM_ZIP!' -DestinationPath '%TEMP%\nssm-tmp' -Force" >> "%LOGFILE%" 2>&1
    if not exist "!NSSM_DIR!" mkdir "!NSSM_DIR!"
    xcopy "%TEMP%\nssm-tmp\!NSSM_VER!\*" "!NSSM_DIR!\" /E /I /Y >nul
    rmdir /s /q "%TEMP%\nssm-tmp" >nul 2>&1
)

set "PATH=!NSSM_DIR!\win64;%PATH%"
set "NEED_P=1"
for /f "tokens=2*" %%a in ('reg query "HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment" /v Path 2^>nul') do (
    echo %%b | findstr /i "nssm" >nul
    if not errorlevel 1 set "NEED_P=0"
)
if "!NEED_P!"=="1" (
    for /f "tokens=2*" %%a in ('reg query "HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment" /v Path 2^>nul') do (
        setx /M PATH "%%b;!NSSM_DIR!\win64" >nul 2>&1
    )
)
where nssm >nul 2>&1
if errorlevel 1 (
    echo   [!] NSSM installed but not found
    echo   nssm not found after install >> "%LOGFILE%"
    call :fail
)
echo   NSSM installed OK

:nssm_done
echo OK.
echo.

REM ===== [5/7] Read backend\.env =====
echo [5/7] Read backend\.env credentials...
echo [STEP 5] Read .env >> "%LOGFILE%"

if not exist "%INSTALL_DIR%\backend\.env" (
    echo   [ERROR] %INSTALL_DIR%\backend\.env not found
    echo   .env not found >> "%LOGFILE%"
    call :fail
)

set "ARK_JWT_SECRET="
set "DB_HOST="
set "DB_PORT="
set "DB_USER="
set "DB_PASS="

for /f "tokens=1,* delims==" %%a in ('findstr /b "COMMISSION_DB_HOST=" "%INSTALL_DIR%\backend\.env"') do set "DB_HOST=%%b"
for /f "tokens=1,* delims==" %%a in ('findstr /b "COMMISSION_DB_PORT=" "%INSTALL_DIR%\backend\.env"') do set "DB_PORT=%%b"
for /f "tokens=1,* delims==" %%a in ('findstr /b "COMMISSION_DB_USER=" "%INSTALL_DIR%\backend\.env"') do set "DB_USER=%%b"
for /f "tokens=1,* delims==" %%a in ('findstr /b "COMMISSION_DB_PASSWORD=" "%INSTALL_DIR%\backend\.env"') do set "DB_PASS=%%b"
for /f "tokens=1,* delims==" %%a in ('findstr /b "JWT_SECRET_KEY=" "%INSTALL_DIR%\backend\.env"') do set "ARK_JWT_SECRET=%%b"

set "MISSING=0"
if "!ARK_JWT_SECRET!"=="" echo   [ERROR] Missing JWT_SECRET_KEY && set "MISSING=1"
if "!DB_HOST!"=="" echo   [ERROR] Missing COMMISSION_DB_HOST && set "MISSING=1"
if "!DB_PORT!"=="" echo   [ERROR] Missing COMMISSION_DB_PORT && set "MISSING=1"
if "!DB_USER!"=="" echo   [ERROR] Missing COMMISSION_DB_USER && set "MISSING=1"
if "!DB_PASS!"=="" echo   [ERROR] Missing COMMISSION_DB_PASSWORD && set "MISSING=1"
if "!MISSING!"=="1" (
    echo   Check: %INSTALL_DIR%\backend\.env
    echo   Credentials incomplete >> "%LOGFILE%"
    call :fail
)

echo   HOST=!DB_HOST!  PORT=!DB_PORT!  USER=!DB_USER!
echo   Credentials OK >> "%LOGFILE%"
echo OK.
echo.

REM ===== [6/7] Maven package =====
echo [6/7] Maven package...
echo [STEP 6] Maven package >> "%LOGFILE%"
echo   First build takes 5-10 min, please wait...
echo.

REM Ensure mvn is reachable
where mvn >nul 2>&1
if errorlevel 1 (
    echo   mvn not in PATH, searching known locations...
    if exist "C:\Program Files\apache-maven-3.9.8\bin\mvn.cmd" (
        set "PATH=C:\Program Files\apache-maven-3.9.8\bin;%PATH%"
    ) else if exist "C:\Program Files\apache-maven-3.9.9\bin\mvn.cmd" (
        set "PATH=C:\Program Files\apache-maven-3.9.9\bin;%PATH%"
    ) else (
        for /d %%d in ("C:\Program Files\apache-maven-*") do (
            if exist "%%d\bin\mvn.cmd" set "PATH=%%d\bin;%PATH%"
        )
    )
)

where mvn >nul 2>&1
if errorlevel 1 (
    echo   [ERROR] mvn still not found. Is Maven installed?
    echo   Check: dir "C:\Program Files\apache-maven-*"
    echo   mvn not found >> "%LOGFILE%"
    call :fail
)

if not exist "%JM_DIR%\pom.xml" (
    echo   [ERROR] %JM_DIR%\pom.xml not found
    echo   pom.xml not found >> "%LOGFILE%"
    call :fail
)

cd /d "%JM_DIR%"
echo   Working dir: %CD% >> "%LOGFILE%"
call mvn -B -q package -DskipTests >> "%LOGFILE%" 2>&1
if errorlevel 1 (
    echo   [ERROR] mvn package failed, check log: %LOGFILE%
    echo   mvn package failed >> "%LOGFILE%"
    call :fail
)
if not exist "target\%JAR_NAME%" (
    echo   [ERROR] target\%JAR_NAME% not found after build
    echo   jar not found >> "%LOGFILE%"
    call :fail
)
echo OK.
echo.

REM ===== [7/7] Register and start NSSM service =====
echo [7/7] Register and start NSSM service...
echo [STEP 7] Register service >> "%LOGFILE%"

if not exist "%INSTALL_DIR%\logs\jmreport" mkdir "%INSTALL_DIR%\logs\jmreport"
if not exist "%JM_DIR%\logs" mkdir "%JM_DIR%\logs"

nssm status %SERVICE_NAME% >nul 2>&1
if not errorlevel 1 (
    echo   Existing service found, removing...
    nssm stop %SERVICE_NAME% >nul 2>&1
    timeout /t 3 /nobreak >nul
    nssm remove %SERVICE_NAME% confirm >nul 2>&1
    timeout /t 2 /nobreak >nul
)

set "JAVA_EXE="
for /f "delims=" %%j in ('where java') do (
    set "JAVA_EXE=%%j"
    goto :found_java
)
:found_java
echo   java: !JAVA_EXE! >> "%LOGFILE%"

echo   Registering service...
nssm install %SERVICE_NAME% "!JAVA_EXE!" >> "%LOGFILE%" 2>&1
nssm set %SERVICE_NAME% AppParameters "-Xms512m -Xmx1024m -Dspring.profiles.active=prod -DMYSQL-HOST=!DB_HOST! -DMYSQL-PORT=!DB_PORT! -DMYSQL-DB=jimureport -jar target\%JAR_NAME%" >> "%LOGFILE%" 2>&1
nssm set %SERVICE_NAME% AppDirectory "%JM_DIR%" >> "%LOGFILE%" 2>&1
nssm set %SERVICE_NAME% AppEnvironmentExtra "ARK_JWT_SECRET=!ARK_JWT_SECRET!" "spring.datasource.username=!DB_USER!" "spring.datasource.password=!DB_PASS!" >> "%LOGFILE%" 2>&1
nssm set %SERVICE_NAME% AppStdout "%INSTALL_DIR%\logs\jmreport\service.log" >> "%LOGFILE%" 2>&1
nssm set %SERVICE_NAME% AppStderr "%INSTALL_DIR%\logs\jmreport\service.log" >> "%LOGFILE%" 2>&1
nssm set %SERVICE_NAME% AppRotateFiles 1 >> "%LOGFILE%" 2>&1
nssm set %SERVICE_NAME% AppRotateBytes 20971520 >> "%LOGFILE%" 2>&1
nssm set %SERVICE_NAME% AppRotateOnline 1 >> "%LOGFILE%" 2>&1
nssm set %SERVICE_NAME% Start SERVICE_AUTO_START >> "%LOGFILE%" 2>&1
nssm set %SERVICE_NAME% AppStopMethodSkip 6 >> "%LOGFILE%" 2>&1
nssm set %SERVICE_NAME% AppStopMethodConsole 30000 >> "%LOGFILE%" 2>&1
nssm set %SERVICE_NAME% AppExit Default Restart >> "%LOGFILE%" 2>&1
nssm set %SERVICE_NAME% AppRestartDelay 5000 >> "%LOGFILE%" 2>&1

echo   Starting service...
nssm start %SERVICE_NAME% >> "%LOGFILE%" 2>&1

echo   Waiting 25s for JVM startup...
timeout /t 25 /nobreak >nul

echo   Health check...
curl -s -o nul -w "HTTP %%{http_code}" http://localhost:%PORT%/internal/health >nul 2>&1
if errorlevel 1 (
    echo   [WARN] Health check no response, service may still be starting
    echo   Check later: nssm status %SERVICE_NAME%
    echo   Health check no response >> "%LOGFILE%"
) else (
    echo   Health check passed
    echo   Health check passed >> "%LOGFILE%"
)

echo.
echo ============================================================
echo   Setup Complete!
echo ============================================================
echo   Service: %SERVICE_NAME%
echo   Port:    %PORT%
echo   URL:     http://localhost:%PORT%/jmreport/list
echo   Log:     %INSTALL_DIR%\logs\jmreport\service.log
echo   Setup:   %LOGFILE%
echo ============================================================
echo.
echo   Commands:
echo   - Restart: nssm restart %SERVICE_NAME%
echo   - Status:  nssm status %SERVICE_NAME%
echo   - Assign report:read permission in Ark frontend
echo.
echo ==== Setup complete %date% %time% ==== >> "%LOGFILE%"
echo.
pause
goto :eof

:fail
echo.
echo ============================================================
echo   Setup failed! Check log: %LOGFILE%
echo ============================================================
echo ==== Setup failed %date% %time% ==== >> "%LOGFILE%"
echo.
pause
exit /b 1
