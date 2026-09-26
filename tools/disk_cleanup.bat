@echo off
chcp 65001 >nul
cd /d "%~dp0"

REM cmd handles Korean in .bat poorly (BOM breaks the first line, no BOM garbles
REM text), so keep this launcher ASCII-only. All Korean output lives in the .ps1,
REM which is saved with a UTF-8 BOM so Windows PowerShell 5.1 reads it correctly.

net session >nul 2>&1
if errorlevel 1 (
    echo Requesting administrator rights...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0disk_cleanup.ps1"
