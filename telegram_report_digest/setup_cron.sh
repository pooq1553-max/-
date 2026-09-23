#!/bin/bash
# 매일 아침 cron 등록
# 사용법: bash setup_cron.sh [분 시]   (기본: 0 7 → 매일 07:00)
#   예) bash setup_cron.sh 30 6      → 매일 06:30
#   평일만 원하면 아래 CRON_DAYS 를 "1-5" 로

MIN="${1:-0}"
HOUR="${2:-7}"
CRON_DAYS="*"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON="${PYTHON:-$(command -v python3)}"
if [ -x "$SCRIPT_DIR/.venv/bin/python" ]; then
  PYTHON="$SCRIPT_DIR/.venv/bin/python"
fi

if [ ! -f "$SCRIPT_DIR/.env" ]; then
  echo "[오류] .env 가 없습니다. cp .env.example .env 후 값을 채우세요."; exit 1
fi
if ! ls "$SCRIPT_DIR"/*.session >/dev/null 2>&1; then
  echo "[오류] 텔레그램 세션 파일이 없습니다. 먼저 터미널에서 로그인하세요:"
  echo "  cd $SCRIPT_DIR && $PYTHON telegram_report_digest.py --login"; exit 1
fi

CRON_CMD="$MIN $HOUR * * $CRON_DAYS cd \"$SCRIPT_DIR\" && \"$PYTHON\" telegram_report_digest.py >> run.log 2>&1"

(crontab -l 2>/dev/null | grep -v "telegram_report_digest.py"; echo "$CRON_CMD") | crontab -

echo "cron 등록 완료: $CRON_CMD"
echo ""
echo "현재 crontab:"
crontab -l
echo ""
echo "해제: crontab -l | grep -v telegram_report_digest.py | crontab -"
