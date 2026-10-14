@echo off
chcp 65001 > nul
rem 윈도우용: 두 번 클릭하면 쇼츠 자동화 화면이 켜집니다.
setlocal
cd /d "%~dp0"
title 쇼츠 자동화
set "PYTHONUTF8=1"
set "PATH=%~dp0;%PATH%"
echo 쇼츠 자동화를 시작합니다.
if exist ".venv\Scripts\python.exe" goto run

rem --- 파이썬 3.12 / 3.13 찾기 ---
set "PY="
call :find_python
if not defined PY goto install_python

:make_venv
echo 처음 실행이라 준비 중입니다 (가상환경 만들기)...
%PY% -m venv .venv
if errorlevel 1 goto venv_fail

:run
".venv\Scripts\python.exe" scripts\launcher.py
goto end

:find_python
py -3.12 -c "import sys" > nul 2>&1 && set "PY=py -3.12" && goto :eof
py -3.13 -c "import sys" > nul 2>&1 && set "PY=py -3.13" && goto :eof
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PY="%LOCALAPPDATA%\Programs\Python\Python312\python.exe"" && goto :eof
if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" set "PY="%LOCALAPPDATA%\Programs\Python\Python313\python.exe"" && goto :eof
python -c "import sys; sys.exit(0 if sys.version_info[:2] in ((3,12),(3,13)) else 1)" > nul 2>&1 && set "PY=python"
goto :eof

:install_python
echo 파이썬 3.12 가 없어서 설치합니다. 몇 분 걸릴 수 있어요...
where winget > nul 2>&1 || goto python_manual
winget install -e --id Python.Python.3.12 --scope user --accept-source-agreements --accept-package-agreements
call :find_python
if defined PY goto make_venv
echo.
echo 파이썬 설치를 마쳤습니다. 이 창을 닫고 시작하기를 한 번 더 두 번 클릭해 주세요.
pause
goto end

:python_manual
echo.
echo 파이썬 3.12 를 직접 설치해 주세요: https://www.python.org/downloads/
echo 설치 첫 화면 아래의 "Add python.exe to PATH" 에 꼭 체크하세요.
echo 설치 후 시작하기를 다시 두 번 클릭하면 됩니다.
pause
goto end

:venv_fail
echo.
echo 준비(가상환경 만들기)에 실패했습니다. 이 창을 사진으로 찍어 보내 주세요.
pause

:end
endlocal
