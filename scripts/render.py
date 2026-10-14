"""6단계: 장면 + 자막 + 음성 → 1080x1920 세로 영상 (A/B/C형 각각).

사용법:
    python scripts/render.py                    # A, B, C 모두
    python scripts/render.py --formats C        # C형만

입력: input/원본.*, output/script_A|B|C.json, audio/C/voice_report.json (C형), config/render.json
결과:
    output/shorts_A.mp4, shorts_B.mp4, shorts_C.mp4
    frames/review/A/ …  시작·중간·끝·자막이 바뀌는 시점의 프레임 + 한눈에보기.jpg
    output/render_report.json   형식별 검사 결과(길이·해상도·음성 트랙)와 오류

한 형식이 실패해도 다른 형식의 완성 파일은 지우지 않는다. 새 영상은 임시 파일로 만들고
검사를 통과했을 때만 기존 파일과 바꾼다.
"""
import argparse
import json
import logging
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from applog import setup_logging
from extract_facts import save_json_atomic
from step1 import PROJECT_ROOT, find_font

OUTPUT_DIR = PROJECT_ROOT / "output"
REVIEW_DIR = PROJECT_ROOT / "frames" / "review"
RENDER_CONFIG = PROJECT_ROOT / "config" / "render.json"
TEMPLATES = PROJECT_ROOT / "config" / "templates.json"
REPORT_FILE = OUTPUT_DIR / "render_report.json"
VOICE_REPORT = PROJECT_ROOT / "audio" / "C" / "voice_report.json"
FORMATS = ("A", "B", "C")

log = logging.getLogger("shorts.render")


class RenderError(Exception):
    pass


def find_input_video():
    found = sorted((PROJECT_ROOT / "input").glob("원본.*"), key=lambda p: p.stat().st_mtime, reverse=True)
    found = [p for p in found if p.suffix.lower() in {".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi"}]
    if not found:
        raise RenderError("원본 영상이 없습니다 (input/원본.mp4).")
    return found[0]


def run(cmd, what):
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        tail = "\n".join(result.stderr.strip().splitlines()[-12:])
        raise RenderError(f"{what} 실패 (ffmpeg):\n{tail}")
    return result.stdout


def probe(path):
    out = json.loads(run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format",
                          "-show_streams", str(path)], "영상 정보 읽기"))
    video = next((s for s in out["streams"] if s["codec_type"] == "video"), None)
    return {
        "duration": float(out["format"].get("duration", 0)),
        "width": video and video.get("width"), "height": video and video.get("height"),
        "codec": video and video.get("codec_name"),
        "fps": video and video.get("r_frame_rate"),
        "has_audio": any(s["codec_type"] == "audio" for s in out["streams"]),
    }


# ---------- 자막 그림 ----------

def hex_rgba(value):
    value = value.lstrip("#")
    rgba = [int(value[i:i + 2], 16) for i in (0, 2, 4)]
    return tuple(rgba + [int(value[6:8], 16) if len(value) == 8 else 255])


def layout_lines(text, font_path, size, max_width, min_size=44):
    """한 줄에 맞추되, 작게 해도 안 되면 띄어쓰기 기준 두 줄로 나눈다."""
    while size >= min_size:
        font = ImageFont.truetype(str(font_path), size)
        if font.getlength(text) <= max_width:
            return font, [text]
        size -= 4
    font = ImageFont.truetype(str(font_path), min_size)
    words = text.split(" ")
    best = None
    for i in range(1, len(words)):
        lines = [" ".join(words[:i]), " ".join(words[i:])]
        width = max(font.getlength(line) for line in lines)
        if best is None or width < best[0]:
            best = (width, lines)
    if best is None or best[0] > max_width:
        raise RenderError(f"자막이 너무 길어 안전 영역에 들어가지 않습니다: \"{text}\"")
    return font, best[1]


def draw_subtitle(text, style, is_hook, cfg, path):
    """자막을 안전 영역(safe_area) 안에 그린 투명 PNG."""
    W, H, safe = cfg["width"], cfg["height"], cfg["safe_area"]
    box_w = W - safe["left"] - safe["right"]
    size = style.get("hook_font_size", style["font_size"]) if is_hook else style["font_size"]
    color = style.get("hook_text", style["text"]) if is_hook else style["text"]
    stroke, pad, gap = max(3, size // 14), 26, 12
    font, lines = layout_lines(text, find_font(), size, box_w - 2 * pad - 2 * stroke - 4)
    heights = [font.getbbox(line, stroke_width=stroke) for line in lines]
    line_h = max(b[3] - b[1] for b in heights)
    block_h = line_h * len(lines) + gap * (len(lines) - 1) + 2 * pad
    block_w = max(font.getlength(line) for line in lines) + 2 * pad + 2 * stroke
    cx = safe["left"] + box_w / 2
    if style["position"] == "top":
        top = safe["top"] + 40
    else:
        top = H - safe["bottom"] - block_h - 20
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    rect = [cx - block_w / 2, top, cx + block_w / 2, top + block_h]
    d.rounded_rectangle(rect, radius=22, fill=hex_rgba(style["box"]))
    y = top + pad
    for line, bbox in zip(lines, heights):
        d.text((cx - font.getlength(line) / 2, y - bbox[1]), line, font=font,
               fill=hex_rgba(color), stroke_width=stroke, stroke_fill=(0, 0, 0, 255))
        y += line_h + gap
    img.save(path)
    # 안전 영역 밖으로 나가지 않았는지 확인
    if rect[0] < safe["left"] - 1 or rect[2] > W - safe["right"] + 1 or \
            rect[1] < safe["top"] - 1 or rect[3] > H - safe["bottom"] + 1:
        raise RenderError(f"자막이 안전 영역 밖으로 나갑니다: \"{text}\"")
    return rect


# ---------- 구간 만들기 ----------

def plan_segments(fmt, script, cfg, voice_items=None):
    """장면마다 보여 줄 길이와 음성 파일을 정한다."""
    seg_cfg = cfg["segment"][fmt]
    segments = []
    for n, cue in enumerate(script["cues"]):
        scene_len = max(0.1, cue["end"] - cue["start"])
        seg = {"cue": cue, "start": cue["start"], "scene_len": scene_len, "narration": None}
        if fmt == "C":
            if voice_items is None or n >= len(voice_items):
                raise RenderError("C형 내레이션 음성이 없습니다. 먼저 voice.py 를 실행하세요.")
            item = voice_items[n]
            if item["text"] != cue.get("narration"):
                raise RenderError(f"{n + 1}번 음성이 현재 대본과 다릅니다. voice.py 를 다시 실행하세요.")
            seg["narration"] = item
            seg["duration"] = round(max(seg_cfg["min"], item["duration"] + seg_cfg["pad"]), 2)
        else:
            seg["duration"] = round(min(seg_cfg["max"], max(seg_cfg["min"], scene_len)), 2)
        segments.append(seg)
    return segments


def render_segment(src, src_info, seg, sub_png, out, fmt, cfg, audio_dir):
    d = seg["duration"]
    take = min(d, seg["scene_len"])
    W, H, fps = cfg["width"], cfg["height"], cfg["fps"]
    cmd = ["ffmpeg", "-y", "-v", "error", "-ss", f"{seg['start']:.3f}", "-t", f"{take:.3f}", "-i", str(src),
           "-loop", "1", "-t", f"{d:.3f}", "-i", str(sub_png)]
    vf = (f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1,fps={fps},"
          f"tpad=stop_mode=clone:stop_duration={d:.3f},trim=duration={d:.3f},setpts=PTS-STARTPTS[bg];"
          f"[bg][1:v]overlay=0:0,format=yuv420p[v]")
    af_tail = f"aresample=44100,aformat=channel_layouts=stereo,apad,atrim=0:{d:.3f}"
    next_input = 2
    if fmt == "C":
        cmd += ["-i", str(audio_dir / seg["narration"]["file"])]
        narr = f"[{next_input}:a]adelay=150|150,{af_tail}[n]"
        next_input += 1
        if src_info["has_audio"]:
            vol = cfg["segment"]["C"].get("original_audio_volume", 0.12)
            af = f"{narr};[0:a]volume={vol},{af_tail}[o];[n][o]amix=inputs=2:normalize=0:duration=first[a]"
        else:
            af = narr.replace("[n]", "[a]")
    elif src_info["has_audio"]:
        af = f"[0:a]{af_tail}[a]"
    else:
        cmd += ["-f", "lavfi", "-t", f"{d:.3f}", "-i", "anullsrc=r=44100:cl=stereo"]
        af = f"[{next_input}:a]{af_tail}[a]"
    cmd += ["-filter_complex", f"{vf};{af}", "-map", "[v]", "-map", "[a]", "-t", f"{d:.3f}",
            "-r", str(fps), "-c:v", "libx264", "-preset", cfg["preset"], "-crf", str(cfg["crf"]),
            "-pix_fmt", "yuv420p", "-video_track_timescale", "15360",
            "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2", str(out)]
    run(cmd, f"장면 {seg['cue']['scene_idx']} 구간 렌더링")


def check_video(info, expected, cfg):
    checks = {
        "resolution_1080x1920": (info["width"], info["height"]) == (cfg["width"], cfg["height"]),
        "codec_h264": info["codec"] == "h264",
        "has_audio_track": info["has_audio"],
        "duration_matches_plan": abs(info["duration"] - expected) <= 0.35,
        "duration_within_limit": 0 < info["duration"] <= cfg["max_total_seconds"],
    }
    return checks


def extract_review_frames(video, segments, duration, out_dir):
    """시작·중간·끝 + 자막이 바뀌는 시점의 프레임을 저장하고 한 장으로 모은다."""
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    points = [("시작", 0.1), ("중간", duration / 2), ("끝", max(0.1, duration - 0.15))]
    t = 0.0
    for n, seg in enumerate(segments, 1):
        points.append((f"자막{n}", t + min(0.4, seg["duration"] / 2)))
        t += seg["duration"]
    points.sort(key=lambda p: p[1])
    saved = []
    for label, sec in points:
        name = f"{sec:06.2f}s_{label}.jpg"
        run(["ffmpeg", "-y", "-v", "error", "-ss", f"{sec:.3f}", "-i", str(video), "-frames:v", "1",
             "-q:v", "3", str(out_dir / name)], f"{label} 프레임 추출")
        saved.append(name)
    thumbs = [Image.open(out_dir / n).convert("RGB").resize((270, 480)) for n in saved]
    cols = 5
    rows = (len(thumbs) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * 270, rows * 510), "black")
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.truetype(str(find_font()), 20)
    for i, (thumb, name) in enumerate(zip(thumbs, saved)):
        x, y = (i % cols) * 270, (i // cols) * 510
        sheet.paste(thumb, (x, y + 30))
        draw.text((x + 6, y + 4), name[:-4], font=font, fill="white")
    sheet.save(out_dir / "한눈에보기.jpg", quality=85)
    return saved


def render_format(fmt, src, src_info, cfg, max_chars):
    script_path = OUTPUT_DIR / f"script_{fmt}.json"
    if not script_path.is_file():
        raise RenderError(f"대본이 없습니다: {script_path.name} (먼저 make_scripts.py 실행)")
    script = json.loads(script_path.read_text(encoding="utf-8"))
    for cue in script["cues"]:
        if max_chars and len(cue["subtitle"]) > max_chars:
            raise RenderError(f"자막이 기준({max_chars}자)보다 깁니다: \"{cue['subtitle']}\"")
        if cue["end"] > src_info["duration"] + 0.5:
            raise RenderError(f"장면 {cue['scene_idx']} 시간이 원본 영상보다 깁니다. 장면 나누기를 다시 하세요.")
    voice_items, audio_dir = None, VOICE_REPORT.parent
    if fmt == "C":
        if not VOICE_REPORT.is_file():
            raise RenderError("C형 음성이 없습니다. 먼저 voice.py 를 실행하세요.")
        voice_items = json.loads(VOICE_REPORT.read_text(encoding="utf-8"))["items"]
    segments = plan_segments(fmt, script, cfg, voice_items)
    expected = round(sum(s["duration"] for s in segments), 2)
    style = cfg["styles"][fmt]

    work = Path(tempfile.mkdtemp(prefix=f".render_{fmt}_", dir=OUTPUT_DIR))
    final = OUTPUT_DIR / f"shorts_{fmt}.mp4"
    try:
        parts = []
        for n, seg in enumerate(segments, 1):
            png = work / f"sub_{n:02d}.png"
            draw_subtitle(seg["cue"]["subtitle"], style, seg["cue"]["role"] == "hook", cfg, png)
            part = work / f"part_{n:02d}.mp4"
            render_segment(src, src_info, seg, png, part, fmt, cfg, audio_dir)
            parts.append(part)
        listing = work / "list.txt"
        listing.write_text("".join(f"file '{p.name}'\n" for p in parts), encoding="utf-8")
        joined = work / f"shorts_{fmt}.mp4"
        run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(listing),
             "-c", "copy", "-movflags", "+faststart", str(joined)], "구간 합치기")
        info = probe(joined)
        checks = check_video(info, expected, cfg)
        failed = [k for k, ok in checks.items() if not ok]
        if failed:
            raise RenderError(f"완성 영상 검사 실패: {', '.join(failed)} "
                              f"(길이 {info['duration']:.2f}s/예상 {expected}s, {info['width']}x{info['height']}, "
                              f"음성 {'있음' if info['has_audio'] else '없음'})")
        frames = extract_review_frames(joined, segments, info["duration"], REVIEW_DIR / fmt)
        tmp_final = OUTPUT_DIR / f".shorts_{fmt}.mp4.tmp"
        shutil.move(str(joined), tmp_final)
        tmp_final.replace(final)  # 검사를 통과한 뒤에만 기존 파일과 바꿈
    finally:
        shutil.rmtree(work, ignore_errors=True)
    warnings = []
    if info["duration"] > cfg["warn_total_seconds"]:
        warnings.append(f"{cfg['warn_total_seconds']}초보다 깁니다")
    if fmt == "C":
        review = [i["file"] for i in voice_items if i.get("needs_review")]
        if review:
            warnings.append(f"받아쓰기 검토 필요 음성: {', '.join(review)}")
    return {"status": "ok", "file": final.name, "format_label": script.get("format_label", fmt),
            "duration": round(info["duration"], 2), "expected_duration": expected,
            "width": info["width"], "height": info["height"], "codec": info["codec"],
            "fps": info["fps"], "has_audio": info["has_audio"], "checks": checks,
            "review_frames": f"frames/review/{fmt}", "frame_files": frames, "warnings": warnings,
            "error": ""}


def load_report():
    try:
        return json.loads(REPORT_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"formats": {}}


def render_all(formats, src=None):
    cfg = json.loads(RENDER_CONFIG.read_text(encoding="utf-8"))
    templates = json.loads(TEMPLATES.read_text(encoding="utf-8")) if TEMPLATES.is_file() else {}
    src = src or find_input_video()
    src_info = probe(src)
    # 이전 실행이 중간에 꺼져 남은 임시 파일 정리 (완성 파일은 건드리지 않음)
    for leftover in list(OUTPUT_DIR.glob(".render_*")) + list(OUTPUT_DIR.glob(".shorts_*.mp4.tmp")):
        shutil.rmtree(leftover, ignore_errors=True) if leftover.is_dir() else leftover.unlink(missing_ok=True)
    report = load_report()
    report.setdefault("formats", {})
    for fmt in formats:
        started = datetime.now().isoformat(timespec="seconds")
        print(f"[{fmt}형] 렌더링 중…")
        try:
            result = render_format(fmt, src, src_info, cfg, templates.get(fmt, {}).get("max_subtitle_chars"))
            print(f"[{fmt}형] 완성: {result['file']}  {result['duration']}초  "
                  f"{result['width']}x{result['height']}  음성 {'있음' if result['has_audio'] else '없음'}")
            for w in result["warnings"]:
                print(f"   주의: {w}")
        except Exception as e:  # 한 형식이 실패해도 다음 형식은 계속
            log.exception("%s형 렌더링 실패", fmt)
            previous = report["formats"].get(fmt, {})
            keep = (OUTPUT_DIR / f"shorts_{fmt}.mp4").is_file()
            result = {**previous, "status": "failed", "error": str(e),
                      "previous_file_kept": keep}
            print(f"[{fmt}형] 실패: {e}")
            if keep:
                print(f"   (이전에 만든 shorts_{fmt}.mp4 는 그대로 둡니다)")
        result["rendered_at"] = started
        result["source"] = src.name
        report["formats"][fmt] = result
        save_json_atomic(report, REPORT_FILE)  # 형식마다 바로 기록
    return report


def main():
    parser = argparse.ArgumentParser(description="장면+자막+음성 → 세로 쇼츠 A/B/C")
    parser.add_argument("--formats", nargs="+", choices=FORMATS, default=list(FORMATS))
    parser.add_argument("--input", type=Path)
    args = parser.parse_args()
    src = None
    if args.input:
        src = args.input if args.input.is_absolute() else PROJECT_ROOT / args.input
    report = render_all(args.formats, src)
    statuses = [report["formats"][f]["status"] for f in args.formats]
    ok = statuses.count("ok")
    print(f"\n완성 {ok}/{len(statuses)}개. 확인용 프레임: frames/review/<형식>/한눈에보기.jpg")
    print("※ 자막·화면은 프레임으로, 음성은 직접 들어서 최종 확인하세요.")
    return 0 if ok == len(statuses) else (2 if ok else 1)


if __name__ == "__main__":
    setup_logging()
    try:
        sys.exit(main())
    except RenderError as e:
        print(f"\n오류: {e}")
        sys.exit(1)
