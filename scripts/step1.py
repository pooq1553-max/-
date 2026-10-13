"""1단계: 원본 영상 앞부분(최대 30초)을 잘라 자막 한 줄을 올린 세로 쇼츠를 만든다.

사용법:
    python scripts/step1.py                       # input/원본.mp4 → output/step1.mp4
    python scripts/step1.py --text "자막 문구"
    python scripts/step1.py --input input/다른영상.mp4

규격: 1080x1920, 30fps, H.264(+AAC 음성). 원본이 짧으면 있는 길이만큼만 만든다.
원본 비율이 9:16과 다르면 화면을 꽉 채우도록 확대한 뒤 가운데를 잘라낸다.
"""
import argparse
import json
import os
import platform
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INPUT_DIR = PROJECT_ROOT / "input"
OUTPUT_DIR = PROJECT_ROOT / "output"
DEFAULT_INPUT = INPUT_DIR / "원본.mp4"
DEFAULT_OUTPUT = OUTPUT_DIR / "step1.mp4"
SUBTITLE_FILE = INPUT_DIR / "자막.txt"
DEFAULT_TEXT = "여기에 자막이 들어갑니다"

WIDTH, HEIGHT, FPS = 1080, 1920, 30
MAX_SECONDS = 30.0

# 한글이 나오는 글꼴 후보 (프로젝트 fonts/ → Windows → Mac → Linux 순)
FONT_CANDIDATES = [
    PROJECT_ROOT / "fonts" / "font.ttf",
    Path("C:/Windows/Fonts/malgunbd.ttf"),
    Path("C:/Windows/Fonts/malgun.ttf"),
    Path("/System/Library/Fonts/AppleSDGothicNeo.ttc"),
    Path("/usr/share/fonts/truetype/nanum/NanumGothicExtraBold.ttf"),
    Path("/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf"),
    Path("/usr/share/fonts/truetype/nanum/NanumGothic.ttf"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"),
    Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"),
]


class StepError(Exception):
    """사용자에게 그대로 보여 줄 수 있는 오류."""


def run(cmd):
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        tail = "\n".join(result.stderr.strip().splitlines()[-15:])
        raise StepError(f"{Path(cmd[0]).name} 실행 중 오류:\n{tail}")
    return result.stdout


def probe(path):
    out = run(["ffprobe", "-v", "error", "-print_format", "json",
               "-show_format", "-show_streams", str(path)])
    info = json.loads(out)
    video = next((s for s in info["streams"] if s.get("codec_type") == "video"), None)
    if video is None:
        raise StepError(f"{path.name} 안에 영상이 없습니다. 영상 파일이 맞는지 확인하세요.")
    has_audio = any(s.get("codec_type") == "audio" for s in info["streams"])
    duration = float(info["format"].get("duration") or video.get("duration") or 0)
    width, height = int(video["width"]), int(video["height"])
    # 휴대폰 영상은 가로로 저장하고 '90도 회전' 표시만 붙이는 경우가 있음
    rotation = 0
    for side in video.get("side_data_list", []):
        if "rotation" in side:
            rotation = int(side["rotation"])
    rotation = int(video.get("tags", {}).get("rotate", rotation))
    if abs(rotation) % 180 == 90:
        width, height = height, width
    return {"duration": duration, "width": width, "height": height, "has_audio": has_audio,
            "codec": video.get("codec_name"), "fps": video.get("r_frame_rate")}


def find_font():
    for path in FONT_CANDIDATES:
        if path.is_file():
            return path
    raise StepError("한글 글꼴을 찾지 못했습니다. 아무 한글 .ttf 파일을 fonts/font.ttf 로 넣어 주세요.")


def make_subtitle_png(text, path):
    """자막 한 줄을 투명 배경 PNG(1080x1920)로 그린다. 길면 글자 크기를 줄여 한 줄에 맞춘다."""
    font_path = find_font()
    max_width = WIDTH - 120
    size = 80
    while True:
        font = ImageFont.truetype(str(font_path), size)
        left, top, right, bottom = font.getbbox(text, stroke_width=6)
        if right - left <= max_width or size <= 36:
            break
        size -= 4
    if right - left > max_width:
        raise StepError(f"자막이 너무 길어 한 줄에 들어가지 않습니다 ({len(text)}자). 더 짧게 적어 주세요.")

    image = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    text_w, text_h = right - left, bottom - top
    x = (WIDTH - text_w) // 2 - left
    y = int(HEIGHT * 0.72) - top  # 화면 아래쪽 1/4 지점 (쇼츠 버튼에 가리지 않는 높이)
    pad = 28
    draw.rounded_rectangle(
        [x + left - pad, y + top - pad, x + right + pad, y + bottom + pad],
        radius=24, fill=(0, 0, 0, 140))
    draw.text((x, y), text, font=font, fill="white", stroke_width=6, stroke_fill="black")
    image.save(path)
    return font_path


def open_folder(folder):
    """파일 탐색기(Finder)로 폴더를 연다. 화면이 없는 환경이면 조용히 넘어간다."""
    try:
        if platform.system() == "Windows":
            os.startfile(folder)  # type: ignore[attr-defined]
        elif platform.system() == "Darwin":
            subprocess.run(["open", str(folder)], check=False)
        elif os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"):
            subprocess.run(["xdg-open", str(folder)], check=False)
        else:
            return False
        return True
    except OSError:
        return False


def seconds_text(sec):
    return f"{sec:.0f}" if abs(sec - round(sec)) < 0.05 else f"{sec:.1f}"


def main():
    parser = argparse.ArgumentParser(description="원본 영상 → 30초 세로 쇼츠 (자막 한 줄)")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--text", help=f"자막 문구 (없으면 {SUBTITLE_FILE.name} 또는 기본 문구)")
    parser.add_argument("--no-open", action="store_true", help="끝난 뒤 폴더를 열지 않음")
    args = parser.parse_args()

    INPUT_DIR.mkdir(exist_ok=True)
    OUTPUT_DIR.mkdir(exist_ok=True)
    src = args.input if args.input.is_absolute() else PROJECT_ROOT / args.input
    dst = args.output if args.output.is_absolute() else PROJECT_ROOT / args.output

    if not src.is_file():
        print(f"원본 영상이 없습니다: {src}")
        print(f"이 폴더에 영상을 넣고 이름을 '{DEFAULT_INPUT.name}' 으로 바꾼 뒤 다시 실행하세요.")
        if not args.no_open:
            open_folder(INPUT_DIR)
        return 1

    if args.text:
        text = args.text.strip()
    elif SUBTITLE_FILE.is_file():
        text = SUBTITLE_FILE.read_text(encoding="utf-8-sig").strip().splitlines()[0]
    else:
        text = DEFAULT_TEXT

    info = probe(src)
    print(f"원본: {info['width']}x{info['height']}, {seconds_text(info['duration'])}초, "
          f"음성 {'있음' if info['has_audio'] else '없음'}")
    if info["duration"] <= 0:
        raise StepError("원본 영상 길이를 읽지 못했습니다. 파일이 손상됐을 수 있습니다.")

    length = min(MAX_SECONDS, info["duration"])
    if info["duration"] < MAX_SECONDS:
        print(f"→ 원본이 {seconds_text(info['duration'])}초라 {seconds_text(length)}초 영상이에요.")

    src_ratio = info["width"] / info["height"]
    target_ratio = WIDTH / HEIGHT
    if src_ratio > target_ratio + 0.01:
        side = "양옆이" if info["width"] > info["height"] else "좌우가 조금"
        print(f"→ 원본이 세로 화면보다 넓어서, 화면을 꽉 채우도록 확대한 뒤 가운데를 잘랐어요. {side} 잘립니다.")
    elif src_ratio < target_ratio - 0.01:
        print("→ 원본이 세로 화면보다 길쭉해서, 확대한 뒤 위아래가 조금 잘립니다.")

    with tempfile.TemporaryDirectory() as tmp:
        sub_png = Path(tmp) / "subtitle.png"
        font_path = make_subtitle_png(text, sub_png)
        print(f"자막: \"{text}\" (글꼴: {font_path.name})")

        video_filter = (
            f"[0:v]scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,"
            f"crop={WIDTH}:{HEIGHT},setsar=1,fps={FPS}[bg];"
            f"[bg][1:v]overlay=0:0,format=yuv420p[v]"
        )
        cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
               "-i", str(src), "-loop", "1", "-i", str(sub_png),
               "-filter_complex", video_filter, "-map", "[v]"]
        if info["has_audio"]:
            cmd += ["-map", "0:a:0", "-c:a", "aac", "-b:a", "128k", "-ar", "44100"]
        cmd += ["-t", f"{length:.3f}", "-r", str(FPS),
                "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                "-profile:v", "high", "-pix_fmt", "yuv420p",
                "-movflags", "+faststart", str(dst)]
        print("영상 만드는 중… (길이에 따라 몇십 초 걸릴 수 있어요)")
        run(cmd)

    result = probe(dst)
    print()
    print("완성! ffprobe 확인 결과")
    print(f"  파일: {dst}")
    print(f"  크기: {result['width']}x{result['height']}")
    print(f"  길이: {seconds_text(result['duration'])}초")
    print(f"  코덱: {result['codec']}, 프레임: {result['fps']}")
    if (result["width"], result["height"]) != (WIDTH, HEIGHT) or result["codec"] != "h264":
        raise StepError("결과 영상 규격이 목표(1080x1920, H.264)와 다릅니다.")
    if not args.no_open and not open_folder(dst.parent):
        print(f"(이 컴퓨터는 화면이 없어서 폴더를 열지 못했어요. 위치: {dst.parent})")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except StepError as e:
        print(f"\n오류: {e}")
        sys.exit(1)
