#!/usr/bin/env python3
"""
만화 자동 번역기 — 폴더(또는 zip)에 든 만화 이미지를 한국어로 번역해 말풍선에 식자한다.

전부 무료:
  - 글자 위치 찾기 : EasyOCR (로컬)
  - 일본어 읽기    : manga-ocr (로컬, 세로쓰기 지원)
  - 번역           : 구글 번역 무료 엔드포인트(키 불필요) → 실패 시 MyMemory
                     또는 Ollama 로컬 LLM(완전 오프라인, 품질↑)
  - 식자           : 나눔고딕(OFL, 첫 실행 때 자동 다운로드)

사용법:
  python translate_manga.py 만화폴더
  python translate_manga.py 만화.zip --lang en
  python translate_manga.py 만화폴더 --engine ollama --ollama-model qwen2.5:7b
"""

import argparse
import io
import json
import re
import sys
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import requests
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
DATA_DIR = Path.home() / ".manga_translator"   # 폰트 등 내려받은 파일 저장 위치
IMG_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
FONT_URL = "https://raw.githubusercontent.com/google/fonts/main/ofl/nanumgothic/NanumGothic-Bold.ttf"
SYSTEM_FONTS = [
    "C:/Windows/Fonts/malgunbd.ttf",
    "C:/Windows/Fonts/malgun.ttf",
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",
    "/Library/Fonts/NanumGothic.ttf",
    "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
]
# 코드: (이름, EasyOCR 언어, 구글 번역 언어, 오른쪽→왼쪽으로 읽는지)
LANGS = {
    "ja": ("일본어", ["ja", "en"], "ja", True),
    "en": ("영어", ["en"], "en", False),
    "es": ("스페인어", ["es", "en"], "es", False),
    "zh": ("중국어(간체)", ["ch_sim", "en"], "zh-CN", False),
    "zh-tw": ("중국어(번체)", ["ch_tra", "en"], "zh-TW", False),
    "fr": ("프랑스어", ["fr", "en"], "fr", False),
    "de": ("독일어", ["de", "en"], "de", False),
    "pt": ("포르투갈어", ["pt", "en"], "pt", False),
    "it": ("이탈리아어", ["it", "en"], "it", False),
    "ru": ("러시아어", ["ru", "en"], "ru", False),
    "id": ("인도네시아어", ["id", "en"], "id", False),
    "vi": ("베트남어", ["vi", "en"], "vi", False),
    "th": ("태국어", ["th", "en"], "th", False),
}
LANG_NAMES = {k: v[0] for k, v in LANGS.items()}


# ───────────────────────── 입력/출력 ─────────────────────────

def natural_key(s):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", str(s))]


def load_pages(src: Path):
    """(이름, PIL 이미지) 목록을 페이지 순서대로 돌려준다."""
    if src.is_dir():
        files = sorted((p for p in src.rglob("*") if p.suffix.lower() in IMG_EXTS), key=natural_key)
        for p in files:
            yield str(p.relative_to(src)), Image.open(p).convert("RGB")
    elif src.suffix.lower() in {".zip", ".cbz"}:
        with zipfile.ZipFile(src) as zf:
            names = sorted((n for n in zf.namelist() if Path(n).suffix.lower() in IMG_EXTS), key=natural_key)
            for n in names:
                yield n, Image.open(io.BytesIO(zf.read(n))).convert("RGB")
    elif src.suffix.lower() in IMG_EXTS:
        yield src.name, Image.open(src).convert("RGB")
    else:
        raise ValueError(f"지원하지 않는 입력입니다: {src} (폴더, zip/cbz, 이미지 파일만 가능)")


def get_font_path(user_font=None, log=print):
    if user_font:
        return user_font
    for cand in (HERE / "fonts" / "NanumGothic-Bold.ttf", DATA_DIR / "NanumGothic-Bold.ttf"):
        if cand.exists():
            return str(cand)
    bundled = DATA_DIR / "NanumGothic-Bold.ttf"
    try:
        log("한글 폰트(나눔고딕) 내려받는 중...")
        r = requests.get(FONT_URL, timeout=60)
        r.raise_for_status()
        bundled.parent.mkdir(parents=True, exist_ok=True)
        bundled.write_bytes(r.content)
        return str(bundled)
    except Exception as e:
        log(f"  폰트 다운로드 실패({e}), 시스템 폰트를 찾습니다.")
    for f in SYSTEM_FONTS:
        if Path(f).exists():
            return f
    raise RuntimeError("한글 폰트를 찾지 못했습니다. --font 로 .ttf 파일 경로를 지정해 주세요.")


# ───────────────────────── 글자 검출·인식 ─────────────────────────

@dataclass
class Block:
    x0: int
    y0: int
    x1: int
    y1: int
    char: float            # 대략적인 글자 크기(px)
    bubble: int = 0        # 말풍선 라벨(0 = 말풍선 밖)
    text: str = ""
    ko: str = ""

    @property
    def w(self):
        return self.x1 - self.x0

    @property
    def h(self):
        return self.y1 - self.y0


class Ocr:
    def __init__(self, lang, gpu, log=print):
        import easyocr
        langs = LANGS[lang][1]
        log("OCR 모델 불러오는 중... (첫 실행 때는 모델 다운로드로 몇 분 걸립니다)")
        self.lang = lang
        self.reader = easyocr.Reader(langs, gpu=gpu, verbose=False)
        self.mocr = None
        if lang == "ja":
            from manga_ocr import MangaOcr
            self.mocr = MangaOcr(force_cpu=not gpu)

    def detect(self, img):
        """글자 조각들의 사각형 [(x0,y0,x1,y1), ...]"""
        horiz, free = self.reader.detect(img, min_size=10, text_threshold=0.6, low_text=0.35, width_ths=0.3)
        boxes = [(int(b[0]), int(b[2]), int(b[1]), int(b[3])) for b in horiz[0]]
        for poly in free[0]:
            xs, ys = [p[0] for p in poly], [p[1] for p in poly]
            boxes.append((int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))))
        h, w = img.shape[:2]
        return [(max(0, a), max(0, b), min(w, c), min(h, d)) for a, b, c, d in boxes if c > a and d > b]

    def read(self, img, blk: Block):
        pad = int(blk.char * 0.3)
        crop = img[max(0, blk.y0 - pad):blk.y1 + pad, max(0, blk.x0 - pad):blk.x1 + pad]
        if self.mocr:
            return self.mocr(Image.fromarray(crop)).strip()
        return " ".join(self.reader.readtext(crop, detail=0, paragraph=True)).strip()


def light_components(gray):
    """밝은 영역(말풍선 후보)의 연결 요소 라벨 맵."""
    light = (gray > 180).astype(np.uint8)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(light, connectivity=4)
    return labels, stats


def bubble_of(box, labels, stats, img_area):
    """사각형이 들어 있는 말풍선 라벨. 너무 크거나(배경) 작으면 0."""
    x0, y0, x1, y1 = box
    region = labels[y0:y1, x0:x1]
    vals = region[region > 0]
    if vals.size == 0:
        return 0
    lab = int(np.bincount(vals).argmax())
    area = stats[lab, cv2.CC_STAT_AREA]
    bx, by, bw, bh = stats[lab, :4]
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    inside = bx <= cx <= bx + bw and by <= cy <= by + bh
    if not inside or area > 0.25 * img_area or bw * bh < (x1 - x0) * (y1 - y0):
        return 0
    return lab


def group_blocks(boxes, labels, stats, img_area, rtl=True):
    """가까운 글자 조각을 하나의 대사 덩어리로 묶는다. 서로 다른 말풍선끼리는 묶지 않는다."""
    if not boxes:
        return []
    sizes = [min(b[2] - b[0], b[3] - b[1]) for b in boxes]
    char = float(np.median(sizes))
    gap = char * 0.8
    bubs = [bubble_of(b, labels, stats, img_area) for b in boxes]

    parent = list(range(len(boxes)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, a in enumerate(boxes):
        for j in range(i + 1, len(boxes)):
            b = boxes[j]
            if bubs[i] != bubs[j]:
                continue
            same_bubble = bubs[i] != 0
            g = gap * (2.0 if same_bubble else 1.0)
            if a[0] - g <= b[2] and b[0] - g <= a[2] and a[1] - g <= b[3] and b[1] - g <= a[3]:
                parent[find(i)] = find(j)

    groups = {}
    for i in range(len(boxes)):
        groups.setdefault(find(i), []).append(i)

    blocks = []
    for idx in groups.values():
        xs0, ys0, xs1, ys1 = zip(*(boxes[i] for i in idx))
        c = float(np.median([sizes[i] for i in idx]))
        blk = Block(min(xs0), min(ys0), max(xs1), max(ys1), c, bubs[idx[0]])
        if blk.w * blk.h >= (char * 0.6) ** 2:
            blocks.append(blk)
    # 읽는 순서: 위→아래, 같은 높이면 일본 만화는 오른쪽→왼쪽, 나머지는 왼쪽→오른쪽
    blocks.sort(key=lambda b: (round(b.y0 / (char * 4)), -b.x1 if rtl else b.x0))
    return blocks


def is_noise(text):
    stripped = re.sub(r"[\s\.\,…・･\-~〜ー!?！？。、「」『』()（）\"'*]", "", text)
    return len(stripped) == 0


# ───────────────────────── 번역 ─────────────────────────

class Translator:
    def __init__(self, engine, src, ollama_model, ollama_url, log=print):
        self.log = log
        self.engine = engine
        self.src = LANGS[src][2]
        self.src_name = LANG_NAMES[src]
        self.ollama_model = ollama_model
        self.ollama_url = ollama_url.rstrip("/")
        self.context = []   # 앞 페이지 대사(흐름 유지용)
        self.sess = requests.Session()
        self.sess.headers["User-Agent"] = "Mozilla/5.0"

    def translate(self, texts):
        if not texts:
            return []
        if self.engine == "ollama":
            try:
                out = self._ollama(texts)
                self.context = (self.context + list(zip(texts, out)))[-20:]
                return out
            except Exception as e:
                self.log(f"    Ollama 실패({e}) → 구글 번역으로 대신합니다.")
        return self._google_with_phrasebook(texts)

    # 무료 번역기가 자주 틀리는 짧은 일본어 인사말은 정해진 번역을 쓴다 (おはようございます → "인사" 같은 오역 방지)
    JA_PHRASES = {
        "おはようございます": "좋은 아침이에요", "おはよう": "좋은 아침",
        "こんにちは": "안녕하세요", "こんばんは": "안녕하세요",
        "ありがとうございます": "감사합니다", "ありがとう": "고마워",
        "すみません": "죄송해요", "ごめんなさい": "미안해요", "ごめん": "미안",
        "おやすみなさい": "안녕히 주무세요", "おやすみ": "잘 자",
        "いただきます": "잘 먹겠습니다", "ごちそうさまでした": "잘 먹었습니다",
        "ただいま": "다녀왔어", "おかえりなさい": "어서 와요", "おかえり": "어서 와",
        "いってきます": "다녀올게", "いってらっしゃい": "잘 다녀와",
        "よろしくお願いします": "잘 부탁드려요", "お疲れ様です": "수고하셨어요",
    }

    def _google_with_phrasebook(self, texts):
        fixed = {}
        if self.src == "ja":
            for i, t in enumerate(texts):
                m = re.fullmatch(r"(.+?)([。！？!?…ー～~♡♥]*)", t)
                if m and m.group(1) in self.JA_PHRASES:
                    tail = m.group(2).replace("。", "").replace("！", "!").replace("？", "?").replace("ー", "").replace("～", "~")
                    fixed[i] = self.JA_PHRASES[m.group(1)] + tail
        rest = [t for i, t in enumerate(texts) if i not in fixed]
        done = iter(self._google_batch(rest) if rest else [])
        return [fixed[i] if i in fixed else next(done) for i in range(len(texts))]

    # 구글 번역(무료, 키 불필요) — 한 페이지 대사를 줄바꿈으로 묶어 한 번에 보낸다.
    def _google(self, text):
        for attempt in range(4):
            try:
                r = self.sess.get(
                    "https://translate.googleapis.com/translate_a/single",
                    params={"client": "gtx", "sl": self.src, "tl": "ko", "dt": "t", "q": text},
                    timeout=20,
                )
                r.raise_for_status()
                return "".join(seg[0] for seg in r.json()[0] if seg[0])
            except Exception as e:
                last = e
                time.sleep(2 ** attempt)
        raise RuntimeError(last)

    def _mymemory(self, text):
        r = self.sess.get(
            "https://api.mymemory.translated.net/get",
            params={"q": text, "langpair": f"{self.src}|ko"},
            timeout=20,
        )
        r.raise_for_status()
        return r.json()["responseData"]["translatedText"]

    def _google_batch(self, texts):
        out = self._google_batch_raw(self._as_sentences(texts))
        return [self._polish(o, t) for o, t in zip(out, texts)]

    def _as_sentences(self, texts):
        # 끝맺음 부호가 없는 짧은 대사는 사전 뜻풀이처럼 번역되기 쉽다 (おはようございます → "인사")
        # → 일본어·중국어는 마침표를 붙여 문장으로 번역하게 한다
        if self.src not in ("ja", "zh-CN", "zh-TW"):
            return texts
        return [t if re.search(r"[。！？!?…」』）)～~ー♡♥]$", t) else t + "。" for t in texts]

    HONORIFICS = {"senpai": "선배", "sempai": "선배", "sensei": "선생님", "onii-chan": "오빠", "onee-chan": "언니",
                  "센파이": "선배", "센빠이": "선배", "센세이": "선생님", "오니쨩": "오빠", "오네쨩": "언니"}

    def _polish(self, ko, src):
        for k, v in self.HONORIFICS.items():
            ko = re.sub(rf"(?<![A-Za-z가-힣]){k}(?![A-Za-z])", v, ko, flags=re.I)
        if not re.search(r"[。.!?！？]$", src):
            ko = re.sub(r"(?<=[가-힣])\.$", "", ko)  # 원문에 없던 마침표는 떼기
        return ko.strip()

    def _google_batch_raw(self, texts):
        try:
            joined = self._google("\n".join(texts))
            parts = [p.strip() for p in joined.split("\n")]
            if len(parts) == len(texts):
                return parts
            return [self._google(t) for t in texts]
        except Exception as e:
            self.log(f"    구글 번역 실패({e}) → MyMemory 로 대신합니다.")
            out = []
            for t in texts:
                try:
                    out.append(self._mymemory(t))
                except Exception:
                    out.append("")
            return out

    def _ollama(self, texts):
        ctx = "\n".join(f"- {o} → {k}" for o, k in self.context) or "(없음)"
        numbered = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(texts))
        prompt = (
            f"다음은 만화 한 페이지의 {self.src_name} 대사들이다. 자연스러운 한국어 구어체로 번역하라.\n"
            "캐릭터 말투와 감탄사, 효과음 느낌을 살리고, 설명을 덧붙이지 마라.\n"
            f"앞 페이지 번역(말투·이름 일관성 참고):\n{ctx}\n\n"
            f"번역할 대사:\n{numbered}\n\n"
            f'반드시 {{"translations": ["...", ...]}} 형식의 JSON 으로, 정확히 {len(texts)}개를 순서대로 답하라.'
        )
        r = requests.post(
            f"{self.ollama_url}/api/chat",
            json={
                "model": self.ollama_model,
                "messages": [{"role": "user", "content": prompt}],
                "format": "json",
                "stream": False,
                "options": {"temperature": 0.3},
            },
            timeout=300,
        )
        r.raise_for_status()
        out = json.loads(r.json()["message"]["content"])["translations"]
        if len(out) != len(texts):
            raise ValueError(f"개수 불일치 {len(out)}/{len(texts)}")
        return [str(s).strip() for s in out]


# ───────────────────────── 지우기·식자 ─────────────────────────

def bubble_interior(labels, lab, cache):
    if lab not in cache:
        mask = (labels == lab).astype(np.uint8)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        filled = np.zeros_like(mask)
        cv2.drawContours(filled, contours, -1, 1, thickness=cv2.FILLED)
        ys, xs = np.nonzero(filled)
        cache[lab] = (filled.astype(bool), (xs.min(), ys.min(), xs.max() + 1, ys.max() + 1))
    return cache[lab]


def erase(img, blk, labels, cache):
    pad = int(blk.char * 0.25) + 2
    h, w = img.shape[:2]
    x0, y0 = max(0, blk.x0 - pad), max(0, blk.y0 - pad)
    x1, y1 = min(w, blk.x1 + pad), min(h, blk.y1 + pad)
    if blk.bubble:
        interior, _ = bubble_interior(labels, blk.bubble, cache)
        sub = interior[y0:y1, x0:x1]
        region = img[y0:y1, x0:x1]
        bg = np.median(region[labels[y0:y1, x0:x1] == blk.bubble], axis=0) if sub.any() else [255, 255, 255]
        region[sub] = bg
    else:
        region = img[y0:y1, x0:x1]
        gray = cv2.cvtColor(region, cv2.COLOR_RGB2GRAY)
        bg = np.median(gray)
        mask = (np.abs(gray.astype(int) - bg) > 60).astype(np.uint8) * 255
        mask = cv2.dilate(mask, np.ones((3, 3), np.uint8), iterations=2)
        img[y0:y1, x0:x1] = cv2.inpaint(region, mask, 5, cv2.INPAINT_TELEA)


def text_region(blk, labels, cache):
    """번역문을 넣을 사각형. 말풍선 안이면 말풍선 안쪽까지 넓혀 쓴다(한글은 가로쓰기라 폭이 더 필요)."""
    if not blk.bubble:
        grow = max(0, (blk.h - blk.w) // 2)  # 세로 글자 자리를 정사각형 가까이 넓힘
        return blk.x0 - grow, blk.y0, blk.x1 + grow, blk.y1
    _, (bx0, by0, bx1, by1) = bubble_interior(labels, blk.bubble, cache)
    cx, cy = (bx0 + bx1) / 2, (by0 + by1) / 2
    hw, hh = (bx1 - bx0) * 0.36, (by1 - by0) * 0.36   # 타원 안 최대 사각형 ≈ 0.707
    lim = max(blk.w, blk.h) * 0.9
    hw, hh = min(hw, lim), min(hh, lim)
    rx0, ry0, rx1, ry1 = int(cx - hw), int(cy - hh), int(cx + hw), int(cy + hh)
    # 원래 글자 영역보다 좁아지지 않게
    return (min(rx0, max(blk.x0, bx0)), min(ry0, max(blk.y0, by0)),
            max(rx1, min(blk.x1, bx1)), max(ry1, min(blk.y1, by1)))


def wrap(draw, text, font, max_w):
    lines, cur = [], ""
    for word in text.split():
        trial = f"{cur} {word}".strip()
        if draw.textlength(trial, font=font) <= max_w:
            cur = trial
            continue
        if cur:
            lines.append(cur)
        cur = ""
        for ch in word:  # 한 단어가 너무 길면 글자 단위로 자른다
            if draw.textlength(cur + ch, font=font) <= max_w or not cur:
                cur += ch
            else:
                lines.append(cur)
                cur = ch
    if cur:
        lines.append(cur)
    return lines


def typeset(pil, blk, region, font_path, max_size):
    x0, y0, x1, y1 = region
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(pil.width, x1), min(pil.height, y1)
    W, H = max(10, x1 - x0), max(10, y1 - y0)
    draw = ImageDraw.Draw(pil)
    size = int(min(max_size, max(12, blk.char * 1.1)))
    while True:
        font = ImageFont.truetype(font_path, size)
        lines = wrap(draw, blk.ko, font, W)
        lh = int(size * 1.2)
        if (lh * len(lines) <= H and all(draw.textlength(l, font=font) <= W for l in lines)) or size <= 10:
            break
        size -= 1

    # 배경이 어두우면 흰 글자 + 검은 테두리
    patch = np.asarray(pil.crop((x0, y0, x1, y1)).convert("L"))
    dark = patch.size and patch.mean() < 110
    fill, stroke = ((255, 255, 255), (0, 0, 0)) if dark else ((0, 0, 0), (255, 255, 255))
    sw = 0 if blk.bubble else max(1, size // 8)

    ty = y0 + (H - lh * len(lines)) / 2
    for line in lines:
        tw = draw.textlength(line, font=font)
        draw.text((x0 + (W - tw) / 2, ty), line, font=font, fill=fill, stroke_width=sw, stroke_fill=stroke)
        ty += lh


def fix_spanish_marks(text):
    """OCR 이 거꾸로 된 느낌표·물음표(¡ ¿)를 j/i/Z 등으로 잘못 읽은 것을 되돌린다."""
    def repl(m):
        head, body, end = m.group(1), m.group(2), m.group(3)
        if end == "!" and re.match(r"[jil1|]", head):
            return "¡" + body + end
        if end == "?" and re.match(r"[Zz2]", head):
            return "¿" + body + end
        return m.group(0)
    return re.sub(r"(?:(?<=^)|(?<=[.!?…]\s))([jil1|Zz2])([A-ZÁÉÍÓÚÑÜ][^.!?…]*)([!?])", repl, text)


def clean_ocr(text, lang="ja"):
    text = text.replace("．．．", "…").replace("...", "…").replace("・・・", "…")
    text = re.sub(r"\s+", " ", text).strip()
    if lang == "es":
        text = fix_spanish_marks(text)
    # 서양 만화는 대사가 전부 대문자인 경우가 많은데, 그대로 번역하면 품질이 떨어진다 → 문장 첫 글자만 대문자로
    letters = [c for c in text if c.isalpha() and c.lower() != c.upper()]
    if len(letters) >= 4 and sum(c.isupper() for c in letters) >= 0.85 * len(letters):
        text = re.sub(r"(^|[.!?¡¿…]\s*)(\w)", lambda m: m.group(1) + m.group(2).upper(), text.lower())
        text = re.sub(r"\bi\b", "I", text)
    return text


# ───────────────────────── 메인 ─────────────────────────

def process_page(pil, ocr, translator, font_path, max_size):
    img = np.array(pil)
    gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    labels, stats = light_components(gray)
    boxes = ocr.detect(img)
    blocks = group_blocks(boxes, labels, stats, img.shape[0] * img.shape[1], rtl=LANGS[getattr(ocr, "lang", "ja")][3])

    for b in blocks:
        b.text = clean_ocr(ocr.read(img, b), getattr(ocr, "lang", "ja"))
    blocks = [b for b in blocks if b.text and not is_noise(b.text)]

    for b, ko in zip(blocks, translator.translate([b.text for b in blocks])):
        b.ko = ko

    cache = {}
    out = img.copy()
    for b in blocks:
        if b.ko:
            erase(out, b, labels, cache)
    out_pil = Image.fromarray(out)
    for b in blocks:
        if b.ko:
            typeset(out_pil, b, text_region(b, labels, cache), font_path, max_size)
    return out_pil, blocks


def detect_gpu(force_cpu=False):
    if force_cpu:
        return False
    try:
        import torch
        return torch.cuda.is_available()
    except ImportError:
        return False


def default_output(src: Path):
    return src.parent / f"{src.stem}_한국어"


def run_job(src, out_dir, ocr, translator, font_path, max_font=40, redo=False,
            log=print, on_page=None, should_stop=lambda: False):
    """입력 하나(폴더/zip/이미지)를 번역한다. on_page(현재, 전체, 결과이미지)로 진행 상황을 알린다."""
    src = Path(src)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    pages = list(load_pages(src))
    if not pages:
        log(f"이미지가 없습니다: {src}")
        return out_dir
    started = time.time()
    with open(out_dir / "번역문.txt", "a", encoding="utf-8") as tlog:
        for i, (name, pil) in enumerate(pages, 1):
            if should_stop():
                log("중지했습니다.")
                return out_dir
            dest = out_dir / Path(name).with_suffix(".png")
            if dest.exists() and not redo:
                log(f"[{i}/{len(pages)}] {name} — 이미 있음, 건너뜀")
                if on_page:
                    on_page(i, len(pages), None)
                continue
            t = time.time()
            try:
                result, blocks = process_page(pil, ocr, translator, font_path, max_font)
            except Exception as e:
                log(f"[{i}/{len(pages)}] {name} — 실패: {e}")
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            result.save(dest)
            tlog.write(f"\n=== {name} ===\n")
            for b in blocks:
                tlog.write(f"{b.text}\n → {b.ko}\n")
            tlog.flush()
            log(f"[{i}/{len(pages)}] {name} — 대사 {len(blocks)}개, {time.time() - t:.1f}초")
            if on_page:
                on_page(i, len(pages), result)

    if src.suffix.lower() in {".zip", ".cbz"}:
        zpath = out_dir.with_suffix(".zip")
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in sorted(out_dir.rglob("*.png"), key=natural_key):
                zf.write(p, p.relative_to(out_dir))
        log(f"zip 저장: {zpath}")
    log(f"완료! {len(pages)}장, {time.time() - started:.0f}초 → {out_dir}")
    return out_dir


def main(argv=None):
    ap = argparse.ArgumentParser(description="만화 이미지를 한국어로 자동 번역·식자합니다.")
    ap.add_argument("inputs", nargs="+", help="이미지 폴더, zip/cbz, 또는 이미지 파일 (여러 개 가능)")
    ap.add_argument("-o", "--output", help="결과 폴더 (입력이 하나일 때만. 기본: 입력이름_한국어)")
    ap.add_argument("--lang", default="ja", choices=list(LANGS), help="원문 언어 (기본 ja): " + ", ".join(f"{k}={v[0]}" for k, v in LANGS.items()))
    ap.add_argument("--engine", default="google", choices=["google", "ollama"], help="번역 엔진 (기본 google)")
    ap.add_argument("--ollama-model", default="qwen2.5:7b")
    ap.add_argument("--ollama-url", default="http://localhost:11434")
    ap.add_argument("--font", help="식자에 쓸 .ttf/.otf/.ttc 경로")
    ap.add_argument("--max-font", type=int, default=40, help="최대 글자 크기(px)")
    ap.add_argument("--cpu", action="store_true", help="그래픽카드가 있어도 CPU만 사용")
    ap.add_argument("--redo", action="store_true", help="이미 번역된 페이지도 다시 번역")
    args = ap.parse_args(argv)

    srcs = [Path(p).expanduser().resolve() for p in args.inputs]
    for s in srcs:
        if not s.exists():
            sys.exit(f"입력을 찾을 수 없습니다: {s}")

    gpu = detect_gpu(args.cpu)
    print(f"원문: {LANG_NAMES[args.lang]} · 번역: {args.engine} · {'GPU' if gpu else 'CPU'} 사용")
    font_path = get_font_path(args.font)
    ocr = Ocr(args.lang, gpu)
    translator = Translator(args.engine, args.lang, args.ollama_model, args.ollama_url)
    for s in srcs:
        out = Path(args.output) if args.output and len(srcs) == 1 else default_output(s)
        run_job(s, out, ocr, translator, font_path, args.max_font, args.redo)


if __name__ == "__main__":
    main()
