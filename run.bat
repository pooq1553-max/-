@echo off
cd /d "%~dp0"

if not exist ".venv\Scripts\activate.bat" (
    echo.
    echo Setup not done yet. Double-click setup.bat first.
    echo.
    pause
    exit /b 1
)

call .venv\Scripts\activate.bat

echo Starting FaceSwap... your browser will open at http://127.0.0.1:7860
echo (Keep this window open while using the app. Close it to shut down.)
echo.

python app.py
set APPCODE=%ERRORLEVEL%

echo.
if not "%APPCODE%"=="0" (
    echo ========================================
    echo   App exited with error code %APPCODE%
    echo   Scroll up to read the message above.
    echo ========================================
) else (
    echo App exited normally.
)
echo.
pause
