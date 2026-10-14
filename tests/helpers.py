"""테스트 공용 도구: 작은 시험 영상 만들기, 진짜 프로젝트 폴더를 건드리지 않는 임시 작업 폴더 만들기."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "tests" / "fixtures"
MODELS_READY = (ROOT / "models" / "vits-mimic3-ko_KO-kss_low").is_dir() and \
    (ROOT / "models" / "sherpa-onnx-zipformer-korean-2024-06-24").is_dir()

if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))


def make_video(path, scenes=("testsrc2", "smptebars", "rgbtestsrc"), seconds=3, audio=True,
               size="640x360"):
    """장면이 바뀌는 짧은 시험 영상. scenes 마다 seconds 초."""
    inputs, labels = [], []
    for i, src in enumerate(scenes):
        inputs += ["-f", "lavfi", "-i", f"{src}=s={size}:r=30:d={seconds}"]
        labels.append(f"[{i}:v]")
    filt = f"{''.join(labels)}concat=n={len(scenes)}:v=1:a=0[v]"
    cmd = ["ffmpeg", "-y", "-v", "error", *inputs]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=330:duration={seconds * len(scenes)}"]
    cmd += ["-filter_complex", filt, "-map", "[v]"]
    if audio:
        cmd += ["-map", f"{len(scenes)}:a", "-c:a", "aac"]
    cmd += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(path)]
    subprocess.run(cmd, check=True)
    return path


def make_tone(path, seconds=2.0):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                    f"sine=frequency=440:duration={seconds}", "-ar", "22050", "-ac", "1", str(path)], check=True)
    return path


def make_root(tmp, fast=True):
    """임시 작업 폴더에 config/ 를 복사하고 빈 폴더들을 만든다."""
    tmp = Path(tmp)
    shutil.copytree(ROOT / "config", tmp / "config")
    for d in ("input", "output", "frames", "audio", "data"):
        (tmp / d).mkdir(exist_ok=True)
    if fast:
        cfg_path = tmp / "config" / "render.json"
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        cfg["preset"] = "ultrafast"
        cfg_path.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    return tmp


def probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format",
                          "-show_streams", str(path)], capture_output=True, text=True, check=True)
    info = json.loads(out.stdout)
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    return {"duration": float(info["format"]["duration"]), "width": v["width"], "height": v["height"],
            "codec": v["codec_name"], "has_audio": any(s["codec_type"] == "audio" for s in info["streams"])}
