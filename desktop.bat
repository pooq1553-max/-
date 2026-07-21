@echo off
cd /d "%~dp0"

if not exist ".venv\Scripts\activate.bat" (
    echo Setup not done yet. Double-click setup.bat first.
    pause
    exit /b 1
)

call .venv\Scripts\activate.bat

python desktop_app.py
set APPCODE=%ERRORLEVEL%

if not "%APPCODE%"=="0" (
    echo.
    echo App exited with error code %APPCODE%
    echo Read the message above.
    pause
)
