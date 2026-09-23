#!/usr/bin/env python3
"""
텔레그램 증권사 리포트 다이제스트 봇

1) 텔레그램 채널(내 계정으로 구독 중인 곳)에서 새로 올라온 PDF 리포트를 모은다.
2) 리포트마다 Claude API에 PDF를 통째로 넘겨 요약(증권사, 투자의견, 목표가, 핵심 논리, 리스크)을 뽑는다.
3) 요약들을 모아 하루치 브리핑(목표가 상향·하향, 섹터별 묶음, 공통 언급 종목)을 만든다.
4) 텔레그램 봇으로 브리핑을 보낸다.

사용법:
  python telegram_report_digest.py            # 수집 → 요약 → 브리핑 발송
  python telegram_report_digest.py --login    # 텔레그램 로그인만 (첫 실행, 터미널에서)
  python telegram_report_digest.py --dry-run  # 발송 대신 화면에 출력 (state.json은 건드리지 않음)
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import anthropic
import requests
from dotenv import load_dotenv
from telethon import TelegramClient

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

STATE_FILE = BASE_DIR / "state.json"      # 채널별 마지막으로 처리한 메시지 ID
PENDING_FILE = BASE_DIR / "pending.json"  # 요약은 끝났지만 아직 발송 안 된 리포트
ARCHIVE_DIR = BASE_DIR / "summaries"      # 날짜별 요약 보관

KST = timezone(timedelta(hours=9))
TG_MSG_LIMIT = 4000  # 텔레그램 한 메시지 최대 4096자, 여유를 둠

log = logging.getLogger("report_digest")


# ─────────────────────────────────────────────
# 설정
# ─────────────────────────────────────────────
def env(name: str, default: str | None = None, required: bool = True) -> str:
    value = os.getenv(name, default)
    if required and not value:
        sys.exit(f"[설정 오류] .env에 {name} 값이 없습니다. .env.example을 참고하세요.")
    return value or ""


API_ID = int(env("TG_API_ID"))
API_HASH = env("TG_API_HASH")
SESSION_NAME = str(BASE_DIR / env("TG_SESSION", "tg_session"))
SOURCE_CHANNELS = [c.strip() for c in env("SOURCE_CHANNELS").split(",") if c.strip()]
BOT_TOKEN = env("BOT_TOKEN")
CHAT_ID = env("CHAT_ID")
env("ANTHROPIC_API_KEY")  # anthropic 클라이언트가 환경변수에서 직접 읽음

REPORT_MODEL = env("REPORT_MODEL", "claude-sonnet-5")
DIGEST_MODEL = env("DIGEST_MODEL", "claude-sonnet-5")
LOOKBACK_HOURS = int(env("LOOKBACK_HOURS", "24"))
MAX_PDF_MB = float(env("MAX_PDF_MB", "20"))


# ─────────────────────────────────────────────
# 상태 파일
# ─────────────────────────────────────────────
def load_json(path: Path, default):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            log.warning("%s 파일이 깨져 있어 무시합니다.", path.name)
    return default


def save_json(path: Path, data) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)  # 중간에 죽어도 파일이 반쯤 쓰이지 않게


# ─────────────────────────────────────────────
# 1) 텔레그램에서 새 PDF 수집
# ─────────────────────────────────────────────
def channel_ref(raw: str):
    """'-100123...' 같은 숫자 ID는 int로, 나머지는 @username 그대로."""
    try:
        return int(raw)
    except ValueError:
        return raw


def is_pdf(message) -> bool:
    doc = message.document
    if not doc:
        return False
    if doc.mime_type == "application/pdf":
        return True
    name = message.file.name if message.file else None
    return bool(name and name.lower().endswith(".pdf"))


async def fetch_new_pdfs(client: TelegramClient, state: dict) -> list[dict]:
    """state의 마지막 ID 이후(첫 실행이면 최근 LOOKBACK_HOURS 시간) PDF 메시지를 모은다."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)
    await client.get_dialogs()  # 숫자 ID 채널을 찾을 수 있도록 엔티티 캐시 채우기

    found = []
    for raw in SOURCE_CHANNELS:
        try:
            entity = await client.get_entity(channel_ref(raw))
        except Exception as e:  # noqa: BLE001
            log.error("채널 '%s'를 찾지 못했습니다: %s", raw, e)
            continue

        key = str(entity.id)
        last_id = state.get(key, 0)
        title = getattr(entity, "title", raw)
        count = 0

        async for msg in client.iter_messages(entity, min_id=last_id):
            if not last_id and msg.date < cutoff:
                break  # 첫 실행: 최근 LOOKBACK_HOURS만
            if not is_pdf(msg):
                continue
            found.append({
                "channel_key": key,
                "channel": title,
                "message": msg,
                "file_name": msg.file.name or f"{msg.id}.pdf",
                "caption": (msg.message or "").strip(),
                "date": msg.date.astimezone(KST).strftime("%Y-%m-%d %H:%M"),
            })
            count += 1

        log.info("[%s] 새 PDF %d건 (last_id=%s)", title, count, last_id)

    found.sort(key=lambda x: (x["channel_key"], x["message"].id))
    return found


# ─────────────────────────────────────────────
# 2) 리포트별 요약 (Claude가 PDF를 표·차트까지 직접 읽음)
# ─────────────────────────────────────────────
REPORT_PROMPT = """첨부된 증권사 리포트 PDF를 읽고 아래 JSON 하나만 출력하세요. 설명이나 코드블록 없이 JSON만.

{
  "broker": "증권사명",
  "analyst": "애널리스트 이름 (없으면 빈 문자열)",
  "title": "리포트 제목",
  "report_type": "기업 | 산업 | 시황/전략 | 경제 | 채권 | 기타",
  "company": "대상 종목명 (기업 리포트가 아니면 빈 문자열)",
  "ticker": "종목코드 (모르면 빈 문자열)",
  "sector": "섹터 (예: 반도체, 2차전지, 자동차, 은행, 바이오, 인터넷, 화학 ...)",
  "rating": "투자의견 (예: 매수, Buy, 중립, 없으면 빈 문자열)",
  "rating_change": "상향 | 하향 | 유지 | 신규 | 없음",
  "target_price": 숫자 또는 null (원화 기준, 쉼표 없이),
  "prev_target_price": 숫자 또는 null,
  "target_change": "상향 | 하향 | 유지 | 신규 | 없음",
  "current_price": 숫자 또는 null,
  "summary": "한 줄 요약 (60자 이내)",
  "thesis": ["핵심 투자 논리 2~4개, 숫자 근거 포함"],
  "risks": ["리스크 1~3개"],
  "mentioned_stocks": ["본문에서 의미 있게 언급된 다른 종목명들"]
}

목표가 변경 여부는 리포트 본문·표에 적힌 이전 목표가를 근거로 판단하세요. 확실하지 않으면 추측하지 말고 null이나 "없음"을 쓰세요."""


def extract_json(text: str) -> dict:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("응답에서 JSON을 찾지 못했습니다")
    return json.loads(text[start:end + 1])


def response_text(resp) -> str:
    return "".join(b.text for b in resp.content if b.type == "text").strip()


def summarize_report(claude: anthropic.Anthropic, pdf_bytes: bytes, item: dict) -> dict:
    context = f"파일명: {item['file_name']}"
    if item["caption"]:
        context += f"\n채널 메시지: {item['caption'][:500]}"

    resp = claude.messages.create(
        model=REPORT_MODEL,
        max_tokens=4000,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": "application/pdf",
                        "data": base64.standard_b64encode(pdf_bytes).decode("ascii"),
                    },
                },
                {"type": "text", "text": f"{context}\n\n{REPORT_PROMPT}"},
            ],
        }],
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError("모델이 요약을 거절했습니다")

    data = extract_json(response_text(resp))
    data.update({
        "channel": item["channel"],
        "date": item["date"],
        "file_name": item["file_name"],
    })
    log.info("  요약 완료: %s / %s (입력 %s토큰)", data.get("broker"), data.get("title"),
             resp.usage.input_tokens)
    return data


async def collect_and_summarize(dry_run: bool) -> list[dict]:
    state = load_json(STATE_FILE, {})
    pending = load_json(PENDING_FILE, [])
    claude = anthropic.Anthropic()

    async with TelegramClient(SESSION_NAME, API_ID, API_HASH) as client:
        items = await fetch_new_pdfs(client, state)
        for item in items:
            msg = item["message"]
            size_mb = (msg.file.size or 0) / 1024 / 1024
            if size_mb > MAX_PDF_MB:
                log.warning("  건너뜀(%.1fMB > %sMB): %s", size_mb, MAX_PDF_MB, item["file_name"])
            else:
                try:
                    pdf_bytes = await client.download_media(msg, file=bytes)
                    pending.append(summarize_report(claude, pdf_bytes, item))
                except anthropic.BadRequestError as e:
                    # 페이지 수 초과, 암호 걸린 PDF 등은 다시 해도 실패하므로 넘어감
                    log.error("  요약 불가(%s): %s", item["file_name"], e.message)
                except (anthropic.APIConnectionError, anthropic.RateLimitError,
                        anthropic.InternalServerError) as e:
                    # 일시 오류: 여기서 멈추고 다음 실행 때 이 리포트부터 다시
                    log.error("  일시 오류로 중단, 다음 실행에서 재시도: %s", e)
                    break
                except Exception as e:  # noqa: BLE001
                    log.error("  요약 실패(%s): %s", item["file_name"], e)

            if not dry_run:
                state[item["channel_key"]] = max(state.get(item["channel_key"], 0), msg.id)
                save_json(STATE_FILE, state)
                save_json(PENDING_FILE, pending)

    return pending


# ─────────────────────────────────────────────
# 3) 하루치 종합 브리핑
# ─────────────────────────────────────────────
DIGEST_PROMPT = """아래는 오늘 수집한 증권사 리포트 {n}건의 요약 JSON입니다.
이걸로 텔레그램에 보낼 하루치 리포트 브리핑을 한국어로 작성하세요.

형식 규칙:
- 마크다운/HTML 문법(**, #, <b> 등)을 쓰지 말고 일반 텍스트와 이모지, 줄바꿈만 사용
- 전체 3500자 이내, 휴대폰에서 훑어보기 좋게 짧게
- 없는 섹션은 생략

구성:
📌 오늘의 핵심 (3줄 이내로 전체 흐름)

🔺 목표가 상향
  종목명 (증권사) 이전 → 신규 (변화율%) : 이유 한 줄

🔻 목표가 하향
  같은 형식

🔄 투자의견 변경

🏭 섹터별 정리
  섹터명: 종목·논지를 묶어서 1~2줄

👥 공통 언급 종목 (2개 이상 증권사가 다룬 종목)
  종목명: 증권사들 / 시각이 같은지 엇갈리는지

⚠️ 눈여겨볼 리스크 (여러 리포트에서 반복되는 것 위주)

요약 데이터:
{data}"""


def build_digest(claude: anthropic.Anthropic, summaries: list[dict]) -> str:
    slim = [{k: v for k, v in s.items() if k not in ("file_name",)} for s in summaries]
    resp = claude.messages.create(
        model=DIGEST_MODEL,
        max_tokens=8000,
        messages=[{
            "role": "user",
            "content": DIGEST_PROMPT.format(n=len(summaries),
                                            data=json.dumps(slim, ensure_ascii=False)),
        }],
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError("모델이 브리핑 작성을 거절했습니다")
    return response_text(resp)


def fmt_price(v) -> str:
    try:
        return f"{int(float(v)):,}"
    except (TypeError, ValueError):
        return ""


def build_report_list(summaries: list[dict]) -> str:
    """리포트별 한 줄 목록 (모델 없이 로컬에서 만듦)."""
    lines = [f"📄 리포트별 요약 ({len(summaries)}건)", ""]
    for s in summaries:
        name = s.get("company") or s.get("title") or s.get("file_name")
        head = f"• [{s.get('broker', '?')}] {name}"
        rating = s.get("rating") or ""
        tp = fmt_price(s.get("target_price"))
        change = s.get("target_change")
        if tp:
            arrow = {"상향": "↑", "하향": "↓"}.get(change, "")
            rating = f"{rating} TP {tp}{arrow}".strip()
        if rating:
            head += f" | {rating}"
        lines.append(head)
        if s.get("summary"):
            lines.append(f"  {s['summary']}")
    return "\n".join(lines)


# ─────────────────────────────────────────────
# 4) 텔레그램 봇 발송
# ─────────────────────────────────────────────
def split_message(text: str, limit: int = TG_MSG_LIMIT) -> list[str]:
    chunks, buf = [], ""
    for line in text.split("\n"):
        while len(line) > limit:  # 한 줄이 너무 긴 경우
            if buf:
                chunks.append(buf)
                buf = ""
            chunks.append(line[:limit])
            line = line[limit:]
        candidate = f"{buf}\n{line}" if buf else line
        if len(candidate) > limit:
            chunks.append(buf)
            buf = line
        else:
            buf = candidate
    if buf.strip():
        chunks.append(buf)
    return chunks


def send_telegram(text: str) -> None:
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    for chunk in split_message(text):
        r = requests.post(url, json={
            "chat_id": CHAT_ID,
            "text": chunk,
            "disable_web_page_preview": True,
        }, timeout=30)
        if not r.ok:
            raise RuntimeError(f"텔레그램 발송 실패 {r.status_code}: {r.text}")


# ─────────────────────────────────────────────
# 메인
# ─────────────────────────────────────────────
async def login_only() -> None:
    async with TelegramClient(SESSION_NAME, API_ID, API_HASH) as client:
        me = await client.get_me()
        print(f"로그인 완료: {me.first_name} (@{me.username}) → 세션 파일 {SESSION_NAME}.session")
        print("\n구독 중인 채널 (SOURCE_CHANNELS에 @username 또는 숫자 ID를 넣으세요):")
        async for d in client.iter_dialogs():
            if d.is_channel:
                uname = getattr(d.entity, "username", None)
                print(f"  {d.id:>16}  {'@' + uname if uname else '-':<24} {d.name}")


def main() -> None:
    parser = argparse.ArgumentParser(description="텔레그램 증권사 리포트 다이제스트")
    parser.add_argument("--login", action="store_true", help="텔레그램 로그인 + 채널 목록 출력만")
    parser.add_argument("--dry-run", action="store_true", help="발송하지 않고 출력만, state 저장 안 함")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%Y-%m-%d %H:%M:%S")

    if args.login:
        asyncio.run(login_only())
        return

    if not sys.stdin.isatty() and not Path(SESSION_NAME + ".session").exists():
        sys.exit("[오류] 텔레그램 세션 파일이 없습니다. 먼저 터미널에서 "
                 "`python telegram_report_digest.py --login`을 실행해 로그인하세요.")

    log.info("=== 시작 (리포트 모델: %s, 브리핑 모델: %s) ===", REPORT_MODEL, DIGEST_MODEL)
    summaries = asyncio.run(collect_and_summarize(args.dry_run))

    if not summaries:
        log.info("새 리포트가 없습니다. 종료.")
        return

    claude = anthropic.Anthropic()
    today = datetime.now(KST).strftime("%Y-%m-%d")
    header = f"🗞 증권사 리포트 브리핑 {today} ({len(summaries)}건)\n\n"
    try:
        digest = header + build_digest(claude, summaries)
    except Exception as e:  # noqa: BLE001
        log.error("종합 브리핑 생성 실패, 리포트 목록만 보냅니다: %s", e)
        digest = header + "(종합 브리핑 생성에 실패했습니다)"
    report_list = build_report_list(summaries)

    if args.dry_run:
        print("\n" + digest + "\n\n" + report_list)
        return

    send_telegram(digest)
    send_telegram(report_list)
    log.info("텔레그램 발송 완료")

    # 발송 성공 후에만 pending 비우기 (실패하면 다음 실행 때 재발송, 재요약 비용 없음)
    ARCHIVE_DIR.mkdir(exist_ok=True)
    archive = ARCHIVE_DIR / f"{today}.json"
    save_json(archive, load_json(archive, []) + summaries)
    save_json(PENDING_FILE, [])


if __name__ == "__main__":
    main()
