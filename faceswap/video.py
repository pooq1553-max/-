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


def concat_videos(
    input_paths: list[str | Path],
    output_path: str | Path,
    reencode: bool = False,
) -> Path:
    """Concatenate multiple videos into output_path.

    Fast mode uses the concat demuxer with `-c copy` (all inputs must share
    codec / resolution / fps / audio params). Re-encode mode uses the concat
    filter with libx264+aac and handles mixed inputs.
    """
    if not input_paths:
        raise ValueError("합칠 동영상이 없어요.")
    if len(input_paths) < 2:
        raise ValueError("두 개 이상의 동영상이 필요해요.")
    ffmpeg = _ffmpeg_exe()
    if not ffmpeg:
        raise RuntimeError(
            "ffmpeg을 찾을 수 없어요. PowerShell에서:\n"
            "  .\\.venv\\Scripts\\python.exe -m pip install imageio-ffmpeg"
        )
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    inputs = [Path(p).resolve() for p in input_paths]
    for p in inputs:
        if not p.exists():
            raise FileNotFoundError(f"파일이 없어요: {p}")

    if not reencode:
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as tf:
            listfile = Path(tf.name)
            for p in inputs:
                escaped = str(p).replace("'", r"'\''")
                tf.write(f"file '{escaped}'\n")
        try:
            cmd = [
                ffmpeg, "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", str(listfile),
                "-c", "copy",
                str(output_path),
            ]
            result = subprocess.run(cmd, capture_output=True)
            if result.returncode != 0:
                raise RuntimeError(
                    "빠른 합치기 실패. 동영상들의 해상도/코덱/fps가 서로 달라서일 가능성 큼.\n"
                    "'화질 강제 통일' 옵션을 켜고 다시 시도하세요.\n\n"
                    + result.stderr.decode("utf-8", errors="replace")[-600:]
                )
        finally:
            try:
                listfile.unlink()
            except Exception:
                pass
    else:
        cmd = [ffmpeg, "-y"]
        for p in inputs:
            cmd += ["-i", str(p)]
        n = len(inputs)
        streams = "".join(f"[{i}:v:0][{i}:a:0?]" for i in range(n))
        filter_expr = f"{streams}concat=n={n}:v=1:a=1[v][a]"
        cmd += [
            "-filter_complex", filter_expr,
            "-map", "[v]",
            "-map", "[a]",
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-c:a", "aac",
            str(output_path),
        ]
        result = subprocess.run(cmd, capture_output=True)
        if result.returncode != 0:
            raise RuntimeError(
                "재인코딩 합치기 실패:\n"
                + result.stderr.decode("utf-8", errors="replace")[-800:]
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
    target_mode: Optional[str] = None,
    resize_height: Optional[int] = None,
    source_face=None,
    enhancer=None,
    enhance_blend: float = 0.8,
    progress: Optional[ProgressCallback] = None,
    cancel: Optional[CancelPredicate] = None,
) -> Path:
    # target_mode 우선: largest / all / female / male.
    # 미지정 시 기존 replace_all 로 결정(all 또는 largest).
    if target_mode is None:
        target_mode = "all" if replace_all else "largest"
    if source_face is not None:
        # 여러 장에서 미리 만들어 둔 평균 정체성을 그대로 사용
        src_face = source_face
    else:
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
    src_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    src_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    if resize_height and resize_height > 0 and resize_height < src_height:
        out_height = resize_height
        out_width = int(round(src_width * (out_height / src_height)))
        if out_width % 2 == 1:
            out_width += 1
    else:
        out_height = src_height
        out_width = src_width

    output_video_path = Path(output_video_path)
    output_video_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="faceswap_") as td:
        tmp_video = Path(td) / "video_no_audio.mp4"
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(str(tmp_video), fourcc, fps, (out_width, out_height))
        if not writer.isOpened():
            cap.release()
            raise IOError("VideoWriter 초기화 실패")

        frame_idx = 0
        need_resize = (out_width, out_height) != (src_width, src_height)
        try:
            while True:
                if cancel and cancel():
                    if progress:
                        progress(frame_idx, total_frames, "취소됨")
                    raise RuntimeError("사용자가 취소했어요.")

                ret, frame = cap.read()
                if not ret:
                    break

                if need_resize:
                    frame = cv2.resize(frame, (out_width, out_height), interpolation=cv2.INTER_AREA)

                tgt_faces = pipeline.detector.detect(frame)
                if tgt_faces:
                    to_replace = pipeline.detector.select_targets(tgt_faces, target_mode)
                    for tf in to_replace:
                        frame = pipeline.swapper.swap(frame, tf, src_face)
                    if enhancer is not None and to_replace:
                        # 스왑된 얼굴 자리를 그대로 다시 정렬해 화질 복원
                        frame = enhancer.enhance_faces(frame, to_replace, blend=enhance_blend)

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
