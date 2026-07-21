@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ===============================================
echo   FaceSwap - Windows one-time setup
echo ===============================================
echo.

REM ---- 1. Python 3.11 check (via py launcher, avoids Store stub + wrong version) ----
set PYCMD=
py -3.11 --version >nul 2>&1
if not errorlevel 1 (
    set PYCMD=py -3.11
    goto :got_python
)

REM Fallback: check plain python and confirm it's 3.11.x
where python >nul 2>&1
if not errorlevel 1 (
    for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set PYVER=%%v
    echo !PYVER! | findstr /r "^3\.11\." >nul
    if not errorlevel 1 (
        set PYCMD=python
        goto :got_python
    )
)

echo.
echo Python 3.11 is required but was not found.
echo.
echo Install Python 3.11.9 from this direct link:
echo   https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe
echo.
echo IMPORTANT: on the first installer screen, check
echo   [x] Add python.exe to PATH
echo.
echo After installing, open a NEW Command Prompt window and
echo double-click setup.bat again.
pause
exit /b 1

:got_python
for /f "tokens=2 delims= " %%v in ('%PYCMD% --version 2^>^&1') do set PYVER=%%v
echo Found Python !PYVER!  ^(using: %PYCMD%^)
echo.

REM ---- 2. Create venv ----
if not exist ".venv" (
    echo Creating virtual environment...
    %PYCMD% -m venv .venv
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
