@echo off
setlocal EnableExtensions EnableDelayedExpansion
cls

REM -- Always run from this script's directory
cd /d "%~dp0"

echo Starting MS Discovery agent workbench...
echo.

REM -- Delete user-session folder if present (no noisy error)
if exist "user-session" rd /s /q "user-session"

REM -- Ensure Python is installed. If not, try to install it automatically.
echo Checking for Python installation...

set "PYTHON_CMD="
python --version >nul 2>&1 && set "PYTHON_CMD=python"
if not defined PYTHON_CMD (
    py --version >nul 2>&1 && set "PYTHON_CMD=py -3"
)

if defined PYTHON_CMD (
    echo Found !PYTHON_CMD!
    
    REM Check Python version - requires 3.9+
    for /f "tokens=2" %%i in ('!PYTHON_CMD! --version 2^>^&1') do set "PYTHON_VERSION=%%i"
    echo Python version: !PYTHON_VERSION!
    
    REM Use Python to validate version directly (more reliable)
    !PYTHON_CMD! -c "import sys; v=sys.version_info; sys.exit(0 if (v.major>3 or (v.major==3 and v.minor>=9)) else 1)" >nul 2>&1
    
    if !errorlevel! neq 0 (
        echo ERROR: Python 3.9 or newer is required, but version !PYTHON_VERSION! was detected.
        echo Please upgrade Python and re-run this script.
        pause
        exit /b 1
    )
    
    goto PythonAvailable
)

echo Python not found. Attempting automatic installation...

REM Try using winget first (preferred on modern Windows)
winget --version >nul 2>&1
if %errorlevel%==0 (
    echo Installing Python via winget ^(requires internet and may prompt^)...
    winget install Python.Python.3.13 --source winget --accept-package-agreements --accept-source-agreements
    
    REM Wait for Windows to register the new Python installation
    echo Waiting for Python to be registered...
    timeout /t 5 /nobreak >nul 2>&1
    
    REM Refresh PATH after installation
    call :RefreshPath
) else (
    echo winget not available. Downloading python.org installer and running silent install...
    powershell -NoProfile -Command "try { $out = Join-Path $env:TEMP 'python-installer.exe'; Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.11.6/python-3.11.6-amd64.exe' -OutFile $out -UseBasicParsing; Start-Process -FilePath $out -ArgumentList '/quiet','InstallAllUsers=1','PrependPath=1','Include_pip=1' -Wait; exit $LASTEXITCODE } catch { exit 1 }"
    
    REM Refresh PATH after installation
    call :RefreshPath
)

REM Re-check Python presence after attempted install (prefer python, then py)
set "PYTHON_CMD="
python --version >nul 2>&1 && set "PYTHON_CMD=python"
if not defined PYTHON_CMD (
    py --version >nul 2>&1 && set "PYTHON_CMD=py -3"
)
if not defined PYTHON_CMD (
    echo Python still not detected after installation attempt.
    echo Please install Python 3.9+ and ensure it is added to PATH, then re-run this script.
    pause
    exit /b 1
)

:PythonAvailable
echo Using !PYTHON_CMD!

REM Check if virtual environment exists and is valid
if exist ".venv\Scripts\python.exe" (
    echo Found existing virtual environment
) else (
    REM Clean up any broken venv
    if exist ".venv" (
        echo Cleaning up broken virtual environment...
        rd /s /q ".venv"
    )
    
    echo Creating virtual environment...
    !PYTHON_CMD! -m venv .venv
    if !errorlevel! neq 0 (
        echo Failed to create virtual environment.
        pause
        exit /b 1
    )
)

REM Activate virtual environment
echo Activating virtual environment...
call .venv\Scripts\activate

REM Check if dependencies are already installed (skip slow pip operations)
REM Compare requirements.txt timestamp with marker file
set "DEPS_MARKER=.venv\.deps_installed"

REM Use Python to check if deps need installing (more reliable than batch)
python -c "import os,sys; m='%DEPS_MARKER%'; r='requirements.txt'; sys.exit(0 if os.path.exists(m) and os.path.getmtime(m)>=os.path.getmtime(r) else 1)" >nul 2>&1
if %ERRORLEVEL%==0 (
    echo Dependencies already installed
    goto InstallDone
)

REM Upgrade pip first
echo Upgrading pip...
python -m pip install --upgrade pip >nul 2>&1

REM Clean install of dependencies
echo Cleaning old dependencies...
pip uninstall -y openai httpx >nul 2>&1

echo Installing dependencies...
pip install -q --prefer-binary -r requirements.txt >nul 2>&1
if %ERRORLEVEL%==0 (
    echo 1> "%DEPS_MARKER%"
    goto InstallDone
)

echo.
echo Primary install failed. Attempting binary-only install...
pip install -q --only-binary=:all: -r requirements.txt >nul 2>&1
if %ERRORLEVEL%==0 (
    echo 1> "%DEPS_MARKER%"
    goto InstallDone
)

echo.
echo Binary-only install failed. Retrying normal install...
pip install -q -r requirements.txt >nul 2>&1
if %ERRORLEVEL%==0 (
    echo 1> "%DEPS_MARKER%"
    goto InstallDone
)

echo.
echo ERROR: All install attempts failed.
pause
exit /b 1

:InstallDone

REM -- Install/upgrade Discovery CLI (Python package)
REM echo.
REM echo Installing Discovery CLI ^(Python package^)...
REM where git >nul 2>&1
REM if %errorlevel% neq 0 (
REM     echo ERROR: 'git' is required to install the Discovery CLI from GitHub, but was not found on PATH.
REM     echo Install Git from https://git-scm.com/downloads and re-run this script.
REM     pause
REM     exit /b 1
REM )

REM python -m pip install --upgrade "git+https://github.com/microsoft/discovery.git#subdirectory=utils/supercomputer-cli/discovery"
REM if %errorlevel% neq 0 (
REM     echo.
REM     echo ERROR: Failed to install the Discovery CLI Python package.
REM     pause
REM     exit /b 1
REM )

REM -- Attempt to ensure Docker CLI is installed (non-blocking)
echo Ensuring Docker CLI is available...
where docker >nul 2>&1
if %errorlevel%==0 (
    echo Docker CLI found in PATH
) else (
    echo Docker CLI not found. Attempting installation of Docker Desktop...

    REM Try winget first (check existence first)
    set "WINGET_AVAILABLE="
    where winget >nul 2>&1 && set "WINGET_AVAILABLE=1"
    
    if defined WINGET_AVAILABLE (
        echo Installing Docker Desktop via winget ^(requires internet and may prompt^)...
        echo This will install both Docker CLI and Docker Engine. The installation may take a few minutes.
        winget install --id Docker.DockerDesktop -e --accept-package-agreements --accept-source-agreements
        
        REM Refresh PATH in current session after installation
        call :RefreshPath
        
        REM Check if docker is now available
        where docker >nul 2>&1
        if %errorlevel%==0 (
            echo Docker Desktop successfully installed and available
            goto DockerCheckComplete
        ) else (
            echo Docker Desktop may have been installed but requires shell restart to be available in PATH
        )
    ) else (
        echo winget not available.
    )

    :DockerCheckComplete
    REM Final check
    where docker >nul 2>&1
    if %errorlevel% neq 0 (
        echo.
        echo NOTICE: Docker Desktop was not installed automatically.
        echo To use container features, please install Docker Desktop manually.
        echo See: https://docs.docker.com/desktop/install/windows-home/
        echo.
    )
)

REM Check if Docker Engine is running and attempt to start if needed
echo Checking Docker Engine status...
docker version >nul 2>&1
if %errorlevel% neq 0 (
    echo Docker Engine not running. Checking for Docker Desktop...
    
    REM Check if Docker Desktop is installed
    set "DOCKER_DESKTOP="
    if exist "C:\Program Files\Docker\Docker\Docker Desktop.exe" set "DOCKER_DESKTOP=C:\Program Files\Docker\Docker\Docker Desktop.exe"
    
    if defined DOCKER_DESKTOP (
        REM Check if Docker Desktop is already running
        tasklist /FI "IMAGENAME eq Docker Desktop.exe" 2>nul | find /I "Docker Desktop.exe" >nul
        if !errorlevel!==0 (
            echo Docker Desktop is already running. Waiting for Docker Engine to become ready...
        ) else (
            echo Docker Desktop found. Starting Docker Desktop ^(this may take 30-60 seconds^)...
            powershell -Command "Start-Process -FilePath \"!DOCKER_DESKTOP!\""
            echo Docker Desktop launched. Waiting for Docker Engine to start...
        )
        
        echo Checking Docker Engine ^(max 60 seconds^)...
        set "WAIT_COUNT=0"
        :WaitForDocker
        timeout /t 3 /nobreak >nul 2>&1
        docker version >nul 2>&1
        if !errorlevel!==0 (
            echo Docker Engine is now running
            goto DockerReady
        )
        set /a "WAIT_COUNT+=1"
        if !WAIT_COUNT! lss 20 goto WaitForDocker
        
        echo Docker Engine did not start within 60 seconds.
        echo The web server will still start, but container features may not work immediately.
        echo Please wait for Docker Desktop to finish starting, then retry container operations.
        echo.
    ) else (
        echo.
        echo WARNING: Docker Desktop not found.
        echo The web server will still start, but local container-related features ^(building/running agents^) require Docker.
        echo Please install Docker Desktop from: https://docs.docker.com/desktop/install/windows-home/
        echo.
    )
) else (
    :DockerReady
    echo Docker Engine is running

    REM Setup multi-architecture emulation for ARM64 hosts (only once)
    set "BINFMT_MARKER=.venv\.binfmt_configured"
    if not exist "%BINFMT_MARKER%" (
        echo Configuring multi-architecture emulation support...
        docker run --privileged --rm tonistiigi/binfmt --install all >nul 2>&1
        if !errorlevel!==0 (
            echo Multi-architecture emulation configured
            echo 1>"%BINFMT_MARKER%"
        ) else (
            echo Note: Multi-architecture emulation setup skipped
        )
    ) else (
        echo Multi-architecture emulation already configured
    )
    
    REM Ensure multi-platform buildx builder exists
    docker buildx inspect multiplatform >nul 2>&1
    if !errorlevel! neq 0 (
        echo Creating multi-platform Docker builder...
        docker buildx create --name multiplatform --driver docker-container --use --platform linux/amd64,linux/arm64 >nul 2>&1
        if !errorlevel!==0 (
            echo Multi-platform builder created
        ) else (
            echo Note: Multi-platform builder creation skipped
        )
    ) else (
        echo Multi-platform builder already exists
        docker buildx use multiplatform >nul 2>&1
    )
)

REM Start the web server
echo Starting web server...
echo.
echo WEB INTERFACE:
echo    http://localhost:8050
echo.
echo AGENT CONTAINER MANAGEMENT:
echo    Use the web interface to switch agents and manage containers
echo.
echo AVAILABLE AGENTS:
python -c "from agent_manager import StaticAgentManager; m=StaticAgentManager('agents-catalog.yaml'); [print(f'    - {name}') for name in m.agents.keys()]" 2>nul
echo.
echo Press Ctrl+C to stop the server
echo.
python web_server.py

REM Exit cleanly when the server stops
endlocal
exit /b 0

:RefreshPath
REM Refresh PATH from registry to pick up newly installed tools (append only, preserve venv)
for /f "skip=2 tokens=3*" %%i in ('reg query "HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment" /v Path 2^>nul') do set "SysPath=%%i %%j"
for /f "skip=2 tokens=3*" %%i in ('reg query "HKCU\Environment" /v Path 2^>nul') do set "UserPath=%%i %%j"
set "PATH=%PATH%;%SysPath%;%UserPath%"
exit /b 0