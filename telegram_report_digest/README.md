# 텔레그램 증권사 리포트 다이제스트

텔레그램 채널에 올라오는 증권사 리포트 PDF를 모아서 Claude API로 요약하고, 하루치 브리핑을 텔레그램 봇으로 보내 줍니다.

- **PDF 파싱이 필요 없어요.** Claude API가 PDF를 표와 차트까지 통째로 읽어요.
- **리포트별 요약:** 증권사, 투자의견, 목표가(이전 → 신규), 핵심 논리, 리스크
- **하루치 브리핑:** 목표가 상향·하향, 투자의견 변경, 섹터별 묶음, 공통 언급 종목, 반복되는 리스크
- 브리핑 뒤에 리포트별 한 줄 목록도 따로 보내요.

## 동작 흐름

```
텔레그램 채널 (내 계정, Telethon)
   └─ 새 PDF 메시지 (state.json 이후 것만)
        └─ Claude: 리포트별 요약 JSON  ──► pending.json
                                              └─ Claude: 종합 브리핑
                                                   └─ 텔레그램 봇 발송 ──► summaries/날짜.json 보관
```

| 파일 | 설명 |
|---|---|
| `state.json` | 채널별로 마지막에 처리한 메시지 ID. 같은 리포트를 두 번 요약하지 않아요. 첫 실행 때는 최근 24시간치(`LOOKBACK_HOURS`)만 가져와요. |
| `pending.json` | 요약은 끝났지만 아직 발송되지 않은 것. 발송이 실패해도 다음 실행 때 다시 요약하지 않고 그대로 보내요. |
| `summaries/YYYY-MM-DD.json` | 발송한 요약 원본 보관 |
| `run.log` | cron 실행 로그 |

## 맥미니 세팅 순서

1. 설치
   ```bash
   cd telegram_report_digest
   python3 -m venv .venv
   .venv/bin/pip install -r requirements.txt
   ```
   (가상환경 없이 `pip install telethon anthropic python-dotenv requests` 해도 돼요.)

2. `.env` 만들기
   ```bash
   cp .env.example .env
   ```
   - `TG_API_ID`, `TG_API_HASH`: https://my.telegram.org → API development tools
   - `BOT_TOKEN`: @BotFather → `/newbot`
   - `CHAT_ID`: 만든 봇에게 아무 메시지나 보낸 뒤 `https://api.telegram.org/bot<BOT_TOKEN>/getUpdates` 에서 `"chat":{"id":...}` 값
   - `ANTHROPIC_API_KEY`: https://console.anthropic.com
   - `SOURCE_CHANNELS`: 3단계에서 나오는 채널 목록을 보고 채워요

3. **첫 실행은 반드시 터미널에서 직접** (전화번호 + 인증코드 입력)
   ```bash
   .venv/bin/python telegram_report_digest.py --login
   ```
   로그인하면 `tg_session.session` 파일이 생기고, 구독 중인 채널의 ID와 @username 목록이 출력돼요. 원하는 채널을 `.env`의 `SOURCE_CHANNELS`에 넣으세요.

4. 테스트 실행
   ```bash
   .venv/bin/python telegram_report_digest.py --dry-run   # 발송 없이 화면 출력, state 저장 안 함
   .venv/bin/python telegram_report_digest.py             # 실제 발송
   ```

5. cron 등록 (매일 아침 7시 예시)
   ```bash
   bash setup_cron.sh          # 기본 07:00
   bash setup_cron.sh 30 6     # 06:30
   ```
   직접 등록하려면 아래처럼 해도 돼요.
   ```
   0 7 * * * cd /경로/telegram_report_digest && /경로/.venv/bin/python telegram_report_digest.py >> run.log 2>&1
   ```

## 참고할 점

- **비용:** PDF는 페이지 수만큼 토큰이 나가서 하루 수십 건이면 비용이 꽤 쌓여요. `.env`에서 `REPORT_MODEL=claude-haiku-4-5`로 바꾸고 종합 브리핑(`DIGEST_MODEL`)만 Sonnet으로 두면 가성비가 좋아요. Haiku는 PDF를 100페이지까지만 받아요.
- **세션 파일 보안:** `tg_session.session`은 텔레그램 계정 로그인과 같아요. 외부에 공유하거나 커밋하지 마세요. `.gitignore`에 이미 들어가 있어요.
- **맥 절전:** 맥이 잠자기 상태면 cron이 돌지 않아요. 시스템 설정 → 에너지에서 잠자기를 끄거나, `sudo pmset repeat wakeorpoweron MTWRFSU 06:55:00`로 실행 직전에 깨우세요.
- **macOS 권한:** 폴더가 `~/Documents`, `~/Desktop` 아래에 있으면 cron이 파일에 접근하지 못할 수 있어요. 시스템 설정 → 개인정보 보호 및 보안 → 전체 디스크 접근 권한에 `/usr/sbin/cron`을 추가하거나, 폴더를 홈 디렉터리 바로 아래로 옮기세요.
- 20MB(`MAX_PDF_MB`)보다 큰 PDF, 암호가 걸린 PDF는 건너뛰고 로그에 남겨요. API 연결 오류나 요청 한도 초과처럼 일시적인 오류가 나면 거기서 멈추고, 다음 실행 때 그 리포트부터 다시 처리해요.

---

## Claude Code에게 세팅 맡기기

이 폴더에서 Claude Code를 열고 **"README 보고 이거 세팅해줘"** 라고 하면 아래 순서로 진행돼요.

> **Claude Code용 체크리스트**
> 1. `python3 --version` 확인 (3.9 이상). `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`
> 2. `.env`가 없으면 `cp .env.example .env`. 비밀값(API ID/HASH, 봇 토큰, API 키)은 사용자에게 직접 입력받아 채우고, 대화나 로그에 다시 출력하지 않는다.
> 3. `CHAT_ID`를 모르면 사용자에게 봇에게 메시지를 한 번 보내 달라고 한 뒤 `curl -s https://api.telegram.org/bot$BOT_TOKEN/getUpdates`로 찾는다.
> 4. 텔레그램 로그인은 전화번호·인증코드 입력이 필요하므로 **사용자가 터미널에서 직접** `.venv/bin/python telegram_report_digest.py --login`을 실행하게 안내한다 (Claude Code 안에서는 `! ` 접두어로 실행 가능). 출력된 채널 목록을 보고 `SOURCE_CHANNELS`를 사용자와 함께 정한다.
> 5. `.venv/bin/python telegram_report_digest.py --dry-run`으로 확인 → 문제없으면 실제 실행 1회.
> 6. 사용자에게 받을 시각을 물어 `bash setup_cron.sh <분> <시>`로 등록하고 `crontab -l`로 확인한다.
> 7. 위 "참고할 점"의 맥 절전·전체 디스크 접근 권한 항목을 사용자에게 알려 준다.
