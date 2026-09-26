"""얼굴 모자이크 처리 (사진 / 동영상).

스왑의 반대편 기능이다. 검출한 얼굴 영역을 픽셀화하거나 흐리게 만들어
가린다. 프레임 루프와 저장 안전장치는 video.process_video를 그대로 쓴다.

대상 고르기에는 기준 인물 기능이 있다. 기준 사진을 주면 그 사람만 가리거나,
반대로 그 사람만 남기고 나머지를 전부 가릴 수 있다. 후자가 영상에 찍힌
남들의 얼굴을 지울 때 쓰기 좋다.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Tuple

import cv2
import numpy as np

from .detector import DetectedFace, FaceDetector
from .video import CancelPredicate, ProgressCallback, process_video

# 대상 고르기 방식
TARGET_MODES = ("all", "largest", "female", "male", "match", "except_match")
STYLES = ("pixelate", "blur")


def _expand_box(
    bbox: np.ndarray, width: int, height: int, padding: float
) -> Tuple[int, int, int, int]:
    """검출 상자를 padding 비율만큼 넓히고 화면 안으로 자른다.

    검출 상자는 눈·코·입 위주라 이마와 턱이 잘린다. 그대로 가리면 가장자리가
    남아 사람이 식별되므로 조금 넉넉하게 잡는다.
    """
    x1, y1, x2, y2 = (float(v) for v in bbox[:4])
    bw, bh = x2 - x1, y2 - y1
    px, py = bw * padding, bh * padding
    return (
        max(0, int(round(x1 - px))),
        max(0, int(round(y1 - py))),
        min(width, int(round(x2 + px))),
        min(height, int(round(y2 + py))),
    )


def apply_mosaic(
    image_bgr: np.ndarray,
    bbox: np.ndarray,
    style: str = "pixelate",
    strength: float = 0.5,
    shape: str = "ellipse",
    padding: float = 0.15,
) -> np.ndarray:
    """얼굴 한 곳을 가린 새 이미지를 반환한다.

    strength 0~1. 클수록 더 굵게 뭉갠다.
    shape가 ellipse면 타원으로 가려 네모 자국이 덜 튄다.
    """
    h, w = image_bgr.shape[:2]
    x1, y1, x2, y2 = _expand_box(bbox, w, h, padding)
    if x2 - x1 < 2 or y2 - y1 < 2:
        return image_bgr

    region = image_bgr[y1:y2, x1:x2]
    rh, rw = region.shape[:2]
    strength = float(np.clip(strength, 0.0, 1.0))

    if style == "blur":
        # 커널이 영역 크기에 비례해야 얼굴이 크든 작든 비슷하게 가려진다
        k = max(3, int(min(rw, rh) * (0.15 + 0.45 * strength))) | 1
        covered = cv2.GaussianBlur(region, (k, k), 0)
    else:
        # 가로로 몇 칸으로 쪼갤지. 칸이 적을수록 굵은 모자이크가 된다.
        blocks = max(2, int(round(16 - 13 * strength)))
        small_w = min(rw, blocks)
        small_h = max(1, min(rh, int(round(small_w * rh / rw))))  # 칸을 정사각형에 가깝게
        small = cv2.resize(region, (small_w, small_h), interpolation=cv2.INTER_AREA)
        covered = cv2.resize(small, (rw, rh), interpolation=cv2.INTER_NEAREST)

    out = image_bgr.copy()
    if shape == "rect":
        out[y1:y2, x1:x2] = covered
        return out

    mask = np.zeros((rh, rw), dtype=np.uint8)
    cv2.ellipse(mask, (rw // 2, rh // 2), (rw // 2, rh // 2), 0, 0, 360, 255, -1)
    # 경계를 살짝 흐려 타원 테두리가 도드라지지 않게 한다
    feather = max(3, int(min(rw, rh) * 0.08)) | 1
    alpha = (cv2.GaussianBlur(mask, (feather, feather), 0).astype(np.float32) / 255.0)[..., None]
    out[y1:y2, x1:x2] = (covered * alpha + region * (1.0 - alpha)).astype(np.uint8)
    return out


def _unit(vec: np.ndarray) -> Optional[np.ndarray]:
    if vec is None or getattr(vec, "size", 0) == 0:
        return None
    n = float(np.linalg.norm(vec))
    return (vec / n).astype(np.float32) if n > 1e-6 else None


def select_mosaic_targets(
    detector: FaceDetector,
    faces: List[DetectedFace],
    mode: str = "all",
    reference_embedding: Optional[np.ndarray] = None,
    match_threshold: float = 0.35,
) -> List[DetectedFace]:
    """가릴 얼굴 목록을 고른다.

    match / except_match 는 reference_embedding(단위 벡터)이 필요하다.
    """
    if not faces:
        return []
    if mode in ("all", "largest", "female", "male"):
        return detector.select_targets(faces, mode)

    if mode not in ("match", "except_match"):
        raise ValueError(f"unknown mosaic target mode: {mode}")
    if reference_embedding is None:
        raise ValueError("기준 인물 사진이 필요해요.")

    ref = _unit(np.asarray(reference_embedding, dtype=np.float32))
    if ref is None:
        raise ValueError("기준 인물의 얼굴 특징을 읽지 못했어요.")

    picked: List[DetectedFace] = []
    for f in faces:
        u = _unit(f.embedding)
        is_same = u is not None and float(np.dot(u, ref)) >= match_threshold
        if (mode == "match") == is_same:
            picked.append(f)
    return picked


def modules_for_mode(mode: str) -> List[str]:
    """이 대상 모드에 실제로 필요한 검출기 모듈만 돌려준다.

    모자이크는 얼굴 위치만 있으면 되므로 기본은 검출 모델 하나다. 성별로
    고를 때만 genderage, 기준 인물을 쓸 때만 recognition이 추가로 필요하다.
    스왑 모델(inswapper)은 어느 경우에도 필요 없다.
    """
    if mode in ("female", "male"):
        return FaceDetector.MODULES_GENDER
    if mode in ("match", "except_match"):
        return FaceDetector.MODULES_IDENTITY
    return FaceDetector.MODULES_DETECT_ONLY


def mosaic_image(
    detector: FaceDetector,
    image_bgr: np.ndarray,
    mode: str = "all",
    reference_embedding: Optional[np.ndarray] = None,
    match_threshold: float = 0.35,
    style: str = "pixelate",
    strength: float = 0.5,
    shape: str = "ellipse",
    padding: float = 0.15,
) -> Tuple[np.ndarray, int]:
    """사진 한 장의 얼굴을 가린다. 반환: (결과 이미지, 가린 얼굴 수)"""
    faces = detector.detect(image_bgr)
    targets = select_mosaic_targets(
        detector, faces, mode, reference_embedding, match_threshold
    )
    out = image_bgr
    for f in targets:
        out = apply_mosaic(out, f.bbox, style, strength, shape, padding)
    return out, len(targets)


def mosaic_video(
    detector: FaceDetector,
    target_video_path: str | Path,
    output_video_path: str | Path,
    mode: str = "all",
    reference_embedding: Optional[np.ndarray] = None,
    match_threshold: float = 0.35,
    style: str = "pixelate",
    strength: float = 0.5,
    shape: str = "ellipse",
    padding: float = 0.15,
    resize_height: Optional[int] = None,
    progress: Optional[ProgressCallback] = None,
    cancel: Optional[CancelPredicate] = None,
) -> Tuple[Path, Optional[str]]:
    """동영상 속 얼굴을 프레임마다 가려 저장한다.

    반환: (실제로 저장된 경로, 경고 문구 또는 None)
    """
    if mode not in TARGET_MODES:
        raise ValueError(f"unknown mosaic target mode: {mode}")
    if style not in STYLES:
        raise ValueError(f"unknown mosaic style: {style}")
    if mode in ("match", "except_match") and reference_embedding is None:
        raise ValueError("이 모드에는 기준 인물 사진이 필요해요.")

    ref = None
    if reference_embedding is not None:
        ref = _unit(np.asarray(reference_embedding, dtype=np.float32))

    def frame_fn(frame: np.ndarray) -> np.ndarray:
        faces = detector.detect(frame)
        if not faces:
            return frame
        targets = select_mosaic_targets(
            detector, faces, mode, ref, match_threshold
        )
        for f in targets:
            frame = apply_mosaic(frame, f.bbox, style, strength, shape, padding)
        return frame

    return process_video(
        target_video_path=target_video_path,
        output_video_path=output_video_path,
        frame_fn=frame_fn,
        resize_height=resize_height,
        progress=progress,
        cancel=cancel,
    )
