@echo off
chcp 65001 >nul
cd /d "%~dp0"
if "%~1"=="" (echo 만화 폴더나 zip 파일을 이 파일 위로 끌어다 놓으세요. & pause & exit /b 1)
if not exist venv (echo 먼저 "설치.bat" 을 실행하세요. & pause & exit /b 1)
:loop
if "%~1"=="" goto done
venv\Scripts\python translate_manga.py "%~1"
shift
goto loop
:done
pause
