@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ===============================================
echo   FaceSwap - Windows one-time setup
echo ===============================================
echo.

REM ---- 1. Python check ----
where python >nul 2>&1
if errorlevel 1 (
    echo Python not found. Trying to install Python 3.11 via winget...
    where winget >nul 2>&1
    if errorlevel 1 (
        echo.
        echo winget is not available on this Windows.
        echo Please install Python 3.11 manually from:
        echo   https://www.python.org/downloads/
        echo Make sure to check "Add python.exe to PATH" during install.
        echo Then re-run setup.bat.
        pause
        exit /b 1
    )
    winget install -e --id Python.Python.3.11 --scope user --accept-package-agreements --accept-source-agreements
    if errorlevel 1 (
        echo.
        echo winget install failed. Install Python 3.11 manually:
        echo   https://www.python.org/downloads/
        pause
        exit /b 1
    )
    echo.
    echo Python installed. Close this window, open a NEW Command Prompt,
    echo then double-click setup.bat again.
    pause
    exit /b 0
)

for /f "tokens=2 delims= " %%v in ('python --version') do set PYVER=%%v
echo Found Python !PYVER!
echo.

REM ---- 2. Create venv ----
if not exist ".venv" (
    echo Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 (
        echo Failed to create venv. Aborting.
        pause
        exit /b 1
    )
)

call .venv\Scripts\activate.bat

REM ---- 3. Install packages ----
echo.
echo Installing packages (this can take 5-10 minutes)...
python -m pip install --upgrade pip
pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo Package install failed. Common causes:
    echo   - No internet / behind a firewall
    echo   - Missing "Microsoft Visual C++ Build Tools" for insightface
    echo     Download: https://visualstudio.microsoft.com/visual-cpp-build-tools/
    echo     Include the "Desktop development with C++" workload.
    pause
    exit /b 1
)

REM ---- 4. Download model ----
echo.
echo Downloading swap model (~554 MB)...
python download_models.py
if errorlevel 1 (
    echo.
    echo Model download failed. Check your network and re-run setup.bat.
    pause
    exit /b 1
)

REM ---- 5. Desktop shortcut ----
echo.
echo Creating desktop shortcut...
powershell -NoProfile -Command ^
  "$WshShell = New-Object -ComObject WScript.Shell; ^
   $s = $WshShell.CreateShortcut([System.IO.Path]::Combine([Environment]::GetFolderPath('Desktop'), 'FaceSwap.lnk')); ^
   $s.TargetPath = '%CD%\run.bat'; ^
   $s.WorkingDirectory = '%CD%'; ^
   $s.IconLocation = '%SystemRoot%\System32\shell32.dll,220'; ^
   $s.Description = 'FaceSwap local app'; ^
   $s.Save()"

echo.
echo ===============================================
echo   Setup complete!
echo ===============================================
echo.
echo Double-click the "FaceSwap" icon on your Desktop to launch.
echo (Or double-click run.bat in this folder.)
echo.
pause
