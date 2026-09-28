@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo [1/2] 가상환경 만드는 중...
python -m venv venv || (echo 파이썬이 없습니다. https://www.python.org 에서 설치하세요. 설치할 때 "Add python.exe to PATH" 체크! & pause & exit /b 1)
echo [2/2] 필요한 프로그램 설치 중... (몇 분 걸립니다)
venv\Scripts\python -m pip install --upgrade pip
venv\Scripts\pip install -r requirements.txt
echo.
echo 설치 완료! 이제 만화 폴더를 "번역하기.bat" 위로 끌어다 놓으세요.
pause
