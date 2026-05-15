#!/usr/bin/env python3
"""아침 방송용 뉴스 스크립트 생성기.

연합뉴스 RSS에서 헤드라인을 받아와 약 400음절 분량의 낭독용
스크립트를 만든다. (한국 방송 속도 기준 약 1분 분량)
"""
from __future__ import annotations

import argparse
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

KST = timezone(timedelta(hours=9))
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# 위에서부터 순서대로 시도하고, 모은 헤드라인이 충분하면 중단.
FEEDS = [
    # Google News - 가장 안정적
    "https://news.google.com/rss?hl=ko&gl=KR&ceid=KR:ko",
    "https://news.google.com/rss/headlines/section/topic/NATION?hl=ko&gl=KR&ceid=KR:ko",
    # 국내 매체 RSS (백업)
    "https://www.yna.co.kr/rss/news.xml",
    "https://rss.donga.com/total.xml",
    "https://www.hani.co.kr/rss/",
    "https://rss.nocutnews.co.kr/news.xml",
]

WEEKDAY_KO = ["월", "화", "수", "목", "금", "토", "일"]

CONNECTORS = [
    "첫 소식입니다.",
    "다음 소식입니다.",
    "이어서 전해드립니다.",
    "계속해서 전해드립니다.",
    "마지막 소식입니다.",
]


def fetch_feed(url: str, timeout: int = 15) -> list[tuple[str, str]]:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/rss+xml, application/xml, text/xml, */*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.5",
    }
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    root = ET.fromstring(raw)
    items: list[tuple[str, str]] = []
    for item in root.iter("item"):
        title = clean_text(item.findtext("title") or "")
        desc = clean_text(item.findtext("description") or "")
        # Google News 의 경우 title 끝에 " - 매체명" 이 붙음 - 그대로 둠
        if title:
            items.append((title, desc))
    return items


def fetch_headlines(limit: int = 10) -> list[tuple[str, str]]:
    seen: set[str] = set()
    pool: list[tuple[str, str]] = []
    errors: list[str] = []
    for url in FEEDS:
        try:
            for title, desc in fetch_feed(url):
                key = re.sub(r"[\s\-·,]", "", title)[:25]
                if key in seen:
                    continue
                seen.add(key)
                pool.append((title, desc))
            if len(pool) >= limit:
                break
        except Exception as e:  # noqa: BLE001
            errors.append(f"{url}: {e}")
    if not pool:
        raise RuntimeError("RSS 수신 실패: " + " / ".join(errors))
    return pool[:limit]


def clean_text(s: str) -> str:
    s = re.sub(r"<[^>]+>", "", s)
    s = s.replace("&nbsp;", " ").replace("&amp;", "&")
    s = s.replace("&quot;", '"').replace("&#39;", "'")
    s = s.replace("&lt;", "<").replace("&gt;", ">")
    s = re.sub(r"\[[^\]]*\]", "", s)  # [속보], [사진] 등 제거
    s = re.sub(r"\s+", " ", s).strip()
    return s


def count_syllables(text: str) -> int:
    return len(re.findall(r"[가-힣]", text))


def first_sentence(text: str) -> str:
    if not text:
        return ""
    parts = re.split(r"(?<=[.!?。])\s+", text)
    return parts[0].strip() if parts else ""


def build_script(items: list[tuple[str, str]], target: int = 400) -> tuple[str, int]:
    today = datetime.now(KST)
    date_str = f"{today.month}월 {today.day}일 {WEEKDAY_KO[today.weekday()]}요일"
    opening = f"안녕하세요. {date_str} 아침 주요 뉴스를 전해드립니다."
    closing = "이상 오늘의 주요 소식이었습니다. 활기찬 하루 보내세요."

    lines: list[str] = []
    used = count_syllables(opening) + count_syllables(closing)
    for idx, (title, desc) in enumerate(items):
        connector = CONNECTORS[min(idx, len(CONNECTORS) - 1)]
        sentence = first_sentence(desc)
        if sentence and sentence != title:
            chunk = f"{connector} {title}. {sentence}"
        else:
            chunk = f"{connector} {title}."
        chunk = re.sub(r"\.+", ".", chunk).strip()
        chunk_syl = count_syllables(chunk)
        # 목표 음절 초과하면 더 추가하지 않음
        if used + chunk_syl > target + 40 and lines:
            break
        lines.append(chunk)
        used += chunk_syl
        if used >= target - 20:
            break

    # 마지막 줄이 "마지막 소식입니다." 가 아니면 마무리 멘트 자연스럽게
    if lines and not lines[-1].startswith("마지막"):
        # 첫 단어만 교체
        lines[-1] = re.sub(r"^[^.]*\.", "끝으로 전해드립니다.", lines[-1], count=1)

    script = opening + "\n\n" + "\n\n".join(lines) + "\n\n" + closing
    return script, count_syllables(script)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="아침 방송용 뉴스 스크립트 생성")
    parser.add_argument("--output", "-o", type=Path, help="저장할 파일 경로")
    parser.add_argument("--target", type=int, default=400, help="목표 음절 수")
    parser.add_argument("--limit", type=int, default=10, help="후보 헤드라인 수")
    args = parser.parse_args(argv)

    items = fetch_headlines(limit=args.limit)
    script, syllables = build_script(items, target=args.target)

    today = datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")
    header = (
        f"[방송용 낭독 스크립트 / {syllables}음절 / {today}]\n"
        f"※ 약 1분 분량입니다. 또박또박 읽어보세요.\n"
        f"{'-' * 40}\n"
    )
    output = header + script + "\n"

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
