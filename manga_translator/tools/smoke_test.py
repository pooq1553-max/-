#!/usr/bin/env python3
"""
실제 OCR·번역까지 끝까지 돌려 보는 점검 스크립트 (빌드 자동화에서 사용).

일본어 세로쓰기 말풍선이 든 테스트 페이지를 직접 그린 뒤, 주어진 명령으로 번역시키고
결과 폴더에 한글 번역문이 나왔는지 확인한다.

  python tools/smoke_test.py 일본어폰트.ttf -- python translate_manga.py
  python tools/smoke_test.py 일본어폰트.ttf -- dist/MangaTranslator/MangaTranslator.exe
"""
import re
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

LINES = [
    (250, 260, ["おはよう", "ございます"]),
    (650, 300, ["今日は", "いい天気", "ですね"]),
    (330, 820, ["ありがとう", "先輩"]),
]


def make_pages(font_path, out_dir: Path):
    font = ImageFont.truetype(font_path, 34)
    out_dir.mkdir(parents=True, exist_ok=True)
    for n in range(2):
        img = Image.new("RGB", (900, 1200), "white")
        d = ImageDraw.Draw(img)
        d.rectangle((20, 20, 880, 1180), outline="black", width=4)
        for x in range(24, 880, 14):
            d.line((x, 24, x, 1176), fill=(170, 170, 170), width=2)
        for cx, cy, cols in LINES:
            rx = 60 + 38 * len(cols)
            ry = 40 + 20 * max(len(c) for c in cols)
            d.ellipse((cx - rx, cy - ry, cx + rx, cy + ry), fill="white", outline="black", width=4)
            x = cx + (len(cols) - 1) * 23
            for col in cols:
                y = cy - len(col) * 19
                for ch in col:
                    d.text((x - 17, y), ch, font=font, fill="black")
                    y += 38
                x -= 46
        img.save(out_dir / f"{n + 1:03d}.png")


def main():
    font_path = sys.argv[1]
    cmd = sys.argv[sys.argv.index("--") + 1:]
    work = Path("smoke")
    shutil.rmtree(work, ignore_errors=True)
    src = work / "pages"
    make_pages(font_path, src)

    proc = subprocess.run(cmd + [str(src)], timeout=3600)
    out = work / "pages_한국어"
    log = Path.home() / ".manga_translator" / "last_run.log"
    if log.exists():
        print("── 프로그램 기록 ──")
        print(log.read_text(encoding="utf-8", errors="replace")[-6000:])

    tl = out / "번역문.txt"
    text = tl.read_text(encoding="utf-8") if tl.exists() else ""
    print("── 번역문.txt ──")
    print(text or "(없음)")
    pngs = sorted(out.glob("*.png"))
    hangul = len(re.findall(r"[가-힣]", text))
    print(f"종료코드={proc.returncode}, 결과 이미지 {len(pngs)}장, 한글 {hangul}자")
    if proc.returncode != 0 or len(pngs) != 2 or hangul < 10:
        sys.exit("점검 실패")
    print("점검 통과")


if __name__ == "__main__":
    main()
