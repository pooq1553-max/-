#!/bin/bash
# 평일 오후 4시(16:00) 자동 실행 스케줄러 설정
# 사용법: bash setup_scheduler.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON="$(which python3)"
REPORT_SCRIPT="$SCRIPT_DIR/stock_report.py"
REPORT_DIR="$SCRIPT_DIR/reports"
LOG_FILE="$SCRIPT_DIR/scheduler.log"

# reports 디렉토리 생성
mkdir -p "$REPORT_DIR"

# cron 명령어 구성
# 평일(월~금) 오후 4시 = 0 16 * * 1-5
CRON_CMD="0 16 * * 1-5 cd $SCRIPT_DIR && $PYTHON $REPORT_SCRIPT --output $REPORT_DIR/report_\$(date +\%Y\%m\%d).txt >> $LOG_FILE 2>&1"

# 기존 crontab에서 중복 제거 후 추가
(crontab -l 2>/dev/null | grep -v "stock_report.py"; echo "$CRON_CMD") | crontab -

echo "스케줄러 설정 완료!"
echo ""
echo "설정 내용:"
echo "  실행 시간: 평일(월~금) 오후 4시"
echo "  스크립트: $REPORT_SCRIPT"
echo "  보고서 저장: $REPORT_DIR/"
echo "  로그: $LOG_FILE"
echo ""
echo "현재 crontab:"
crontab -l
echo ""
echo "수동 실행: python3 stock_report.py"
echo "스케줄러 해제: crontab -l | grep -v stock_report.py | crontab -"
