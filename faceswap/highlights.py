"""Auto highlight extraction from a video.

Combines three signals per second:
 - audio energy (peaks = something is happening)
 - largest-face area (segments where a face is prominent)
 - frame-difference (motion / scene change)

Sums them into a score curve, smooths over the desired clip length, and
picks non-overlapping top-N peaks.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable, List, Optional, Tuple

import cv2
import numpy as np

from .detector import FaceDetector
from .video import _ffmpeg_exe, trim_video

ProgressCallback = Callable[[float, str], None]


def _extract_audio_energy(video_path: str | Path, seconds: int) -> np.ndarray:
    """Return per-second RMS energy (length = seconds), normalized to 0..1."""
    ffmpeg = _ffmpeg_exe()
    if not ffmpeg:
        return np.zeros(seconds, dtype=np.float32)
    sr = 8000
    cmd = [
        ffmpeg, "-nostdin", "-loglevel", "error",
        "-i", str(video_path),
        "-ac", "1", "-ar", str(sr), "-f", "s16le", "-",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, check=False)
        if proc.returncode != 0 or not proc.stdout:
            return np.zeros(seconds, dtype=np.float32)
        audio = np.frombuffer(proc.stdout, dtype=np.int16).astype(np.float32)
    except Exception:
        return np.zeros(seconds, dtype=np.float32)

    per_sec = sr
    n = min(seconds, len(audio) // per_sec)
    if n <= 0:
        return np.zeros(seconds, dtype=np.float32)
    audio = audio[: n * per_sec].reshape(n, per_sec)
    rms = np.sqrt((audio ** 2).mean(axis=1))
    out = np.zeros(seconds, dtype=np.float32)
    out[:n] = rms
    mx = out.max()
    if mx > 0:
        out /= mx
    return out


def _sample_face_and_motion(
    video_path: str | Path,
    seconds: int,
    detector: FaceDetector,
    sample_every_sec: float = 1.5,
    progress: Optional[ProgressCallback] = None,
) -> Tuple[np.ndarray, np.ndarray]:
    """Return (face_score, motion_score) each of length `seconds` in [0..1]."""
    face = np.zeros(seconds, dtype=np.float32)
    motion = np.zeros(seconds, dtype=np.float32)

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return face, motion

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = total / fps if fps > 0 else seconds
    duration = min(duration, seconds)

    prev_gray = None
    t = 0.0
    steps = max(1, int(duration / sample_every_sec))
    step_i = 0
    while t < duration:
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ret, frame = cap.read()
        if not ret:
            break

        h, w = frame.shape[:2]
        small = cv2.resize(frame, (min(640, w), int(min(640, w) * h / w)),
                           interpolation=cv2.INTER_AREA)

        faces = detector.detect(small)
        if faces:
            largest = max(faces, key=lambda f: f.area)
            frame_area = small.shape[0] * small.shape[1]
            score = min(1.0, (largest.area / frame_area) * 20.0)
            face[int(t):int(min(seconds, t + sample_every_sec))] = score

        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        if prev_gray is not None and prev_gray.shape == gray.shape:
            diff = cv2.absdiff(gray, prev_gray).mean() / 255.0
            motion[int(t):int(min(seconds, t + sample_every_sec))] = min(1.0, diff * 5.0)
        prev_gray = gray

        step_i += 1
        if progress and step_i % 3 == 0:
            progress(step_i / steps, f"프레임 분석 {int(t)}s / {int(duration)}s")

        t += sample_every_sec

    cap.release()
    for arr in (face, motion):
        mx = arr.max()
        if mx > 0:
            arr /= mx
    return face, motion


def find_highlights(
    video_path: str | Path,
    detector: FaceDetector,
    num_clips: int = 5,
    clip_duration_sec: int = 60,
    weights: Tuple[float, float, float] = (0.5, 0.3, 0.2),
    progress: Optional[ProgressCallback] = None,
) -> List[Tuple[float, float]]:
    """Return list of (start_sec, end_sec) for up to num_clips highlights."""
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise IOError(f"동영상을 열 수 없어요: {video_path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()
    duration = int(total / fps) if fps > 0 else 0
    if duration <= 0:
        raise RuntimeError("동영상 길이를 알 수 없어요.")
    if clip_duration_sec >= duration:
        return [(0.0, float(duration))]

    if progress:
        progress(0.02, "음성 에너지 분석 중...")
    audio = _extract_audio_energy(video_path, duration)

    if progress:
        progress(0.1, "얼굴/움직임 샘플링 중...")

    def face_prog(p, msg):
        if progress:
            progress(0.1 + 0.7 * p, msg)

    face, motion = _sample_face_and_motion(video_path, duration, detector, progress=face_prog)

    wa, wf, wm = weights
    score = wa * audio + wf * face + wm * motion

    if progress:
        progress(0.85, "하이라이트 구간 선정 중...")

    window = np.ones(clip_duration_sec, dtype=np.float32) / clip_duration_sec
    if len(score) < clip_duration_sec:
        return [(0.0, float(duration))]
    smoothed = np.convolve(score, window, mode="valid")

    picks: List[Tuple[float, float]] = []
    temp = smoothed.copy()
    for _ in range(num_clips):
        idx = int(np.argmax(temp))
        if temp[idx] <= 1e-6:
            break
        start = float(idx)
        end = float(min(duration, idx + clip_duration_sec))
        picks.append((start, end))
        z0 = max(0, idx - clip_duration_sec + 1)
        z1 = min(len(temp), idx + clip_duration_sec)
        temp[z0:z1] = 0

    picks.sort(key=lambda x: x[0])
    if progress:
        progress(1.0, "완료")
    return picks


def extract_highlight_clips(
    video_path: str | Path,
    ranges: List[Tuple[float, float]],
    output_dir: str | Path,
    reencode: bool = True,
    progress: Optional[ProgressCallback] = None,
) -> List[Path]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(video_path).stem
    out_paths: List[Path] = []
    for i, (start, end) in enumerate(ranges, 1):
        if progress:
            progress(i / max(1, len(ranges)),
                     f"클립 저장 중 {i}/{len(ranges)} ({start:.0f}s ~ {end:.0f}s)")
        out = output_dir / f"{stem}_highlight_{i:02d}_{int(start)}s.mp4"
        trim_video(video_path, out, start, end, reencode=reencode)
        out_paths.append(out)
    return out_paths
