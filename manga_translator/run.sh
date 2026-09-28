#!/usr/bin/env bash
# macOS / Linux: ./run.sh 만화폴더 [옵션]
cd "$(dirname "$0")"
if [ ! -d venv ]; then
  python3 -m venv venv && venv/bin/pip install -r requirements.txt || exit 1
fi
exec venv/bin/python translate_manga.py "$@"
