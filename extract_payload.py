#!/usr/bin/env python3
"""
주간 브리핑 워크플로우 로그에서 집계 데이터(JSON)를 꺼낸다.

print_data=true 로 실행하면 로그에 'PAYLOAD|...' 줄이 찍힌다.
GitHub 로그 원문(.txt)이나, 로그를 담은 JSON(logs_content 필드) 모두 받는다.

  python extract_payload.py job.log -o payload.json
"""
import argparse
import json
import sys


def extract(text):
    chunks = []
    for line in text.splitlines():
        if "PAYLOAD|" in line and 'print("PAYLOAD|"' not in line:
            chunks.append(line.split("PAYLOAD|", 1)[1])
    if not chunks:
        raise SystemExit("PAYLOAD 줄을 찾지 못했습니다 (print_data=true 로 실행했는지 확인)")
    return json.loads("".join(chunks))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("log")
    ap.add_argument("-o", "--output", default="payload.json")
    args = ap.parse_args()
    raw = open(args.log, encoding="utf-8").read()
    try:
        obj = json.loads(raw)
        raw = obj.get("logs_content") or "\n".join(l.get("logs_content", "") for l in obj.get("logs", []))
    except (json.JSONDecodeError, AttributeError):
        pass
    payload = extract(raw)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    print(f"{args.output}: {payload.get('title')} 미장 {payload.get('week_us')} 국장 {payload.get('week_kr')}",
          file=sys.stderr)


if __name__ == "__main__":
    main()
