@echo off
chcp 65001 > nul
rem 윈도우용: 두 번 클릭하면 쇼츠 자동화 화면이 켜집니다.
cd /d "%~dp0"
set "PATH=%~dp0;%PATH%"
echo 쇼츠 자동화를 시작합니다.
if exist ".venv\Scripts\python.exe" goto run
set "PY="
where py > nul 2>&1 && set "PY=py -3"
if not defined PY where python > nul 2>&1 && set "PY=python"
if not defined PY goto install_python
echo 처음 실행이라 준비 중입니다 (가상환경 만들기)...
%PY% -m venv .venv
if errorlevel 1 goto venv_fail
:run
".venv\Scripts\python.exe" scripts\launcher.py
goto end
:install_python
echo 파이썬이 없어서 설치를 시도합니다...
where winget > nul 2>&1 || goto python_manual
winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
echo.
echo 파이썬 설치를 마쳤습니다. 이 창을 닫고 시작하기를 한 번 더 두 번 클릭해 주세요.
pause
goto end
:python_manual
echo https://www.python.org/downloads/ 에서 파이썬을 설치해 주세요.
echo 설치할 때 첫 화면 아래의 "Add python.exe to PATH" 에 꼭 체크하세요.
pause
goto end
:venv_fail
echo 가상환경을 만들지 못했습니다. 이 창의 내용을 캡처해서 보내 주세요.
pause
:end
