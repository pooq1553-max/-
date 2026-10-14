#!/bin/bash
# 맥용: 두 번 클릭하면 쇼츠 자동화 화면이 켜집니다.
cd "$(dirname "$0")" || exit 1
echo "쇼츠 자동화를 시작합니다."
if [ ! -x ".venv/bin/python" ]; then
  PY="$(command -v python3)"
  if [ -z "$PY" ]; then
    echo ""
    echo "파이썬이 없습니다. https://www.python.org/downloads/ 에서 설치한 뒤 다시 두 번 클릭해 주세요."
    read -r -p "엔터를 누르면 닫힙니다..." _
    exit 1
  fi
  echo "처음 실행이라 준비 중입니다 (가상환경 만들기)…"
  "$PY" -m venv .venv || { echo "가상환경을 만들지 못했습니다."; read -r -p "엔터를 누르면 닫힙니다..." _; exit 1; }
fi
exec .venv/bin/python scripts/launcher.py
