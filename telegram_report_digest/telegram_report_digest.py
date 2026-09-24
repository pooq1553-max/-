#!/usr/bin/env python3
"""
텔레그램 증권사 리포트 브리핑 봇 (API 요금 없이, Claude Code 예약 실행용)

흐름:
  1) 사용자가 낮 동안 리포트 PDF를 자기 봇에게 전달(forward)한다.
  2) 매일 아침 Claude Code 예약 세션이 `fetch`로 봇에 쌓인 PDF를 inbox/에 받는다.
  3) 세션의 Claude가 PDF를 직접 읽고 inbox/summaries.json, inbox/briefing.txt를 쓴다. (ROUTINE.md 참고)
  4) `send`로 브리핑을 봇으로 보내고, 처리한 메시지를 텔레그램에 '읽음' 처리한다.

사용법:
  python telegram_report_digest.py fetch
  python telegram_report_digest.py send

필요한 환경변수: TELEGRAM_BOT_TOKEN
받는 사람(chat_id)은 config.json에 저장. 비어 있으면 봇에게 처음 메시지를 보낸 사람으로 정해진다.
외부 라이브러리 없이 파이썬 기본 모듈만 사용.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "config.json"
INBOX = BASE_DIR / "inbox"
MANIFEST = INBOX / "manifest.json"
SUMMARIES = INBOX / "summaries.json"
BRIEFING = INBOX / "briefing.txt"

KST = timezone(timedelta(hours=9))
TG_MSG_LIMIT = 4000       # 텔레그램 한 메시지 최대 4096자, 여유를 둠
BOT_FILE_LIMIT_MB = 20    # 봇 API로 받을 수 있는 파일 최대 크기


# ─────────────────────────────────────────────
# 텔레그램 Bot API
# ─────────────────────────────────────────────
def token() -> str:
    t = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not t:
        sys.exit("[오류] 환경변수 TELEGRAM_BOT_TOKEN 이 없습니다. "
                 "클라우드 환경 설정(Edit)의 환경변수에 넣고 새 세션에서 실행하세요.")
    return t


def api(method: str, **params):
    url = f"https://api.telegram.org/bot{token()}/{method}"
    data = json.dumps(params).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            body = json.load(r)
    except urllib.error.HTTPError as e:
        body = json.load(e)
    if not body.get("ok"):
        raise RuntimeError(f"텔레그램 {method} 실패: {body.get('description')}")
    return body["result"]


def download_file(file_id: str, dest: Path) -> None:
    info = api("getFile", file_id=file_id)
    url = f"https://api.telegram.org/file/bot{token()}/{info['file_path']}"
    with urllib.request.urlopen(url, timeout=120) as r:
        dest.write_bytes(r.read())


# ─────────────────────────────────────────────
# 설정 (받는 사람)
# ─────────────────────────────────────────────
def load_json(path: Path, default):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default


def save_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def source_name(msg: dict) -> str:
    """전달된 메시지의 원래 채널/사람 이름."""
    origin = msg.get("forward_origin") or {}
    chat = origin.get("chat") or origin.get("sender_chat") or msg.get("forward_from_chat") or {}
    if chat.get("title"):
        return chat["title"]
    user = origin.get("sender_user") or msg.get("forward_from") or {}
    if user:
        return " ".join(filter(None, [user.get("first_name"), user.get("last_name")]))
    return origin.get("sender_user_name") or ""


def is_pdf(doc: dict) -> bool:
    return doc.get("mime_type") == "application/pdf" or \
        (doc.get("file_name") or "").lower().endswith(".pdf")


# ─────────────────────────────────────────────
# fetch: 봇에 쌓인 PDF 받기
# ─────────────────────────────────────────────
def cmd_fetch() -> None:
    config = load_json(CONFIG_FILE, {})
    chat_id = config.get("chat_id")

    updates = api("getUpdates", timeout=0, allowed_updates=["message"])
    INBOX.mkdir(exist_ok=True)
    for old in INBOX.iterdir():
        old.unlink()

    if not updates:
        save_json(MANIFEST, {"last_update_id": None, "reports": []})
        print("새 메시지가 없습니다. (리포트 0건)")
        return

    last_update_id = max(u["update_id"] for u in updates)
    reports, skipped = [], []

    for u in updates:
        msg = u.get("message")
        if not msg or msg["chat"]["type"] != "private":
            continue
        sender = msg["chat"]["id"]

        if chat_id is None:
            # 처음 메시지를 보낸 사람을 주인으로 등록
            chat_id = sender
            config["chat_id"] = chat_id
            config["owner_name"] = msg["chat"].get("first_name", "")
            save_json(CONFIG_FILE, config)
            print(f"[안내] 받는 사람을 chat_id={chat_id} ({config['owner_name']})로 등록했습니다. "
                  "config.json을 커밋하세요.")
        if sender != chat_id:
            print(f"[무시] 등록되지 않은 사람(chat_id={sender})의 메시지")
            continue

        doc = msg.get("document")
        if not doc or not is_pdf(doc):
            continue

        name = doc.get("file_name") or f"{msg['message_id']}.pdf"
        size_mb = (doc.get("file_size") or 0) / 1024 / 1024
        if size_mb > BOT_FILE_LIMIT_MB:
            skipped.append(f"{name} ({size_mb:.0f}MB, 봇은 20MB까지만 받을 수 있음)")
            continue

        local = f"{len(reports) + 1:02d}.pdf"
        try:
            download_file(doc["file_id"], INBOX / local)
        except Exception as e:  # noqa: BLE001
            skipped.append(f"{name} (다운로드 실패: {e})")
            continue

        reports.append({
            "file": local,
            "file_name": name,
            "source": source_name(msg),
            "caption": (msg.get("caption") or "")[:500],
            "date": datetime.fromtimestamp(msg["date"], KST).strftime("%Y-%m-%d %H:%M"),
        })

    save_json(MANIFEST, {"last_update_id": last_update_id, "reports": reports,
                         "skipped": skipped})
    print(f"리포트 {len(reports)}건을 inbox/에 받았습니다.")
    for r in reports:
        print(f"  {r['file']}  {r['file_name']}  (출처: {r['source'] or '-'})")
    for s in skipped:
        print(f"  [건너뜀] {s}")


# ─────────────────────────────────────────────
# send: 브리핑 발송 + 읽음 처리
# ─────────────────────────────────────────────
def fmt_price(v) -> str:
    try:
        return f"{int(float(v)):,}"
    except (TypeError, ValueError):
        return ""


def build_report_list(summaries: list[dict]) -> str:
    lines = [f"📄 리포트별 한 줄 요약 ({len(summaries)}건)", ""]
    for s in summaries:
        name = s.get("company") or s.get("title") or s.get("file_name")
        head = f"• [{s.get('broker') or '?'}] {name}"
        rating = s.get("rating") or ""
        tp = fmt_price(s.get("target_price"))
        if tp:
            arrow = {"상향": "↑", "하향": "↓"}.get(s.get("target_change"), "")
            rating = f"{rating} 목표가 {tp}{arrow}".strip()
        if rating:
            head += f" | {rating}"
        lines.append(head)
        if s.get("summary"):
            lines.append(f"  {s['summary']}")
    return "\n".join(lines)


def split_message(text: str, limit: int = TG_MSG_LIMIT) -> list[str]:
    chunks, buf = [], ""
    for line in text.split("\n"):
        while len(line) > limit:
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


def send_text(chat_id: int, text: str) -> None:
    for chunk in split_message(text):
        api("sendMessage", chat_id=chat_id, text=chunk, disable_web_page_preview=True)


def cmd_send() -> None:
    config = load_json(CONFIG_FILE, {})
    manifest = load_json(MANIFEST, None)
    if manifest is None:
        sys.exit("[오류] inbox/manifest.json 이 없습니다. 먼저 fetch를 실행하세요.")

    chat_id = config.get("chat_id")
    reports = manifest["reports"]

    if reports:
        if not chat_id:
            sys.exit("[오류] config.json에 chat_id가 없습니다.")
        if not BRIEFING.exists() or not SUMMARIES.exists():
            sys.exit("[오류] inbox/briefing.txt 와 inbox/summaries.json 을 먼저 작성하세요.")
        briefing = BRIEFING.read_text(encoding="utf-8").strip()
        summaries = load_json(SUMMARIES, [])
        send_text(chat_id, briefing)
        send_text(chat_id, build_report_list(summaries))
        if manifest.get("skipped"):
            send_text(chat_id, "⚠️ 처리하지 못한 파일\n" + "\n".join(manifest["skipped"]))
        print(f"브리핑 발송 완료 ({len(summaries)}건)")
    else:
        print("리포트가 없어 발송하지 않습니다.")

    # 처리한 메시지를 텔레그램에 '읽음' 처리해서 다음 번에 다시 받지 않게
    if manifest.get("last_update_id") is not None:
        api("getUpdates", offset=manifest["last_update_id"] + 1, timeout=0)
        print("텔레그램 메시지 읽음 처리 완료")


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "fetch":
        cmd_fetch()
    elif cmd == "send":
        cmd_send()
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
