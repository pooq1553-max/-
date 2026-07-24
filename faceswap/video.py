"""Frame-by-frame video face swap using the same pipeline as photos."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable, Optional

import cv2
import numpy as np

from .pipeline import FaceSwapPipeline

ProgressCallback = Callable[[int, int, str], None]
CancelPredicate = Callable[[], bool]


def _imread_unicode(path: str | Path) -> np.ndarray:
    with open(path, "rb") as f:
        data = np.frombuffer(f.read(), np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None:
        raise IOError(f"could not read image: {path}")
    return img


def _ffmpeg_exe() -> Optional[str]:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return shutil.which("ffmpeg")


def trim_video(
    input_path: str | Path,
    output_path: str | Path,
    start_sec: float,
    end_sec: float,
    reencode: bool = False,
) -> Path:
    """Cut [start_sec, end_sec] from input_path into output_path using ffmpeg.

    Stream-copy mode is fast but aligned to the nearest keyframe; reencode
    mode is frame-accurate but slower.
    """
    if end_sec <= start_sec:
        raise ValueError("끝 시간이 시작 시간보다 뒤여야 해요.")
    ffmpeg = _ffmpeg_exe()
    if not ffmpeg:
        raise RuntimeError(
            "ffmpeg을 찾을 수 없어요. PowerShell에서 다음을 실행:\n"
            "  .\\.venv\\Scripts\\python.exe -m pip install imageio-ffmpeg"
        )
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    duration = end_sec - start_sec
    if reencode:
        cmd = [
            ffmpeg, "-y",
            "-ss", f"{start_sec:.3f}",
            "-i", str(input_path),
            "-t", f"{duration:.3f}",
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-c:a", "aac",
            str(output_path),
        ]
    else:
        cmd = [
            ffmpeg, "-y",
            "-ss", f"{start_sec:.3f}",
            "-i", str(input_path),
            "-t", f"{duration:.3f}",
            "-c", "copy",
            "-avoid_negative_ts", "make_zero",
            str(output_path),
        ]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(
            "ffmpeg 실행 실패:\n" + result.stderr.decode("utf-8", errors="replace")[-800:]
        )
    return output_path


def probe_video(path: str | Path) -> dict:
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise IOError(f"could not open video: {path}")
    info = {
        "fps": cap.get(cv2.CAP_PROP_FPS) or 0.0,
        "frames": int(cap.get(cv2.CAP_PROP_FRAME_COUNT)),
        "width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
        "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
    }
    cap.release()
    if info["fps"] > 0 and info["frames"] > 0:
        info["duration_sec"] = info["frames"] / info["fps"]
    else:
        info["duration_sec"] = 0.0
    return info


def swap_video(
    pipeline: FaceSwapPipeline,
    source_image_path: str | Path,
    target_video_path: str | Path,
    output_video_path: str | Path,
    replace_all: bool = False,
    progress: Optional[ProgressCallback] = None,
    cancel: Optional[CancelPredicate] = None,
) -> Path:
    src_img = _imread_unicode(source_image_path)
    src_faces = pipeline.detector.detect(src_img)
    if not src_faces:
        raise RuntimeError("소스 사진에서 얼굴을 찾지 못했어요.")
    src_face = pipeline.detector.select(src_faces, "largest")

    cap = cv2.VideoCapture(str(target_video_path))
    if not cap.isOpened():
        raise IOError(f"동영상을 열 수 없어요: {target_video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    output_video_path = Path(output_video_path)
    output_video_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="faceswap_") as td:
        tmp_video = Path(td) / "video_no_audio.mp4"
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(str(tmp_video), fourcc, fps, (width, height))
        if not writer.isOpened():
            cap.release()
            raise IOError("VideoWriter 초기화 실패")

        frame_idx = 0
        try:
            while True:
                if cancel and cancel():
                    if progress:
                        progress(frame_idx, total_frames, "취소됨")
                    raise RuntimeError("사용자가 취소했어요.")

                ret, frame = cap.read()
                if not ret:
                    break

                tgt_faces = pipeline.detector.detect(frame)
                if tgt_faces:
                    to_replace = (
                        tgt_faces
                        if replace_all
                        else [pipeline.detector.select(tgt_faces, "largest")]
                    )
                    for tf in to_replace:
                        frame = pipeline.swapper.swap(frame, tf, src_face)

                writer.write(frame)
                frame_idx += 1
                if progress and (frame_idx % 2 == 0 or frame_idx == total_frames):
                    progress(frame_idx, total_frames, f"프레임 처리 중 {frame_idx}/{total_frames}")
        finally:
            cap.release()
            writer.release()

        ffmpeg = _ffmpeg_exe()
        if ffmpeg:
            if progress:
                progress(frame_idx, total_frames, "원본 음성 합치는 중...")
            try:
                subprocess.run(
                    [
                        ffmpeg, "-y",
                        "-i", str(tmp_video),
                        "-i", str(target_video_path),
                        "-c:v", "copy",
                        "-c:a", "aac",
                        "-map", "0:v:0",
                        "-map", "1:a:0?",
                        "-shortest",
                        str(output_video_path),
                    ],
                    check=True,
                    capture_output=True,
                )
            except subprocess.CalledProcessError:
                shutil.copy2(tmp_video, output_video_path)
        else:
            shutil.copy2(tmp_video, output_video_path)

    if progress:
        progress(total_frames, total_frames, "완료")
    return output_video_path
