"""얼굴 부위 마스크 — 스왑 결과에 원본의 일부를 되살릴 때 쓴다.

inswapper는 얼굴을 128x128로 줄여 처리하고 눈·코 중심의 마스크로 되붙인다.
그래서 입을 크게 벌리는 것 같은 큰 표정 변화가 잘 따라오지 않고, 소스
사진의 다문 입이 섞여 들어온다. 이건 벡터를 다듬어서 고칠 수 있는 문제가
아니라 모델 구조에서 오는 한계다.

대신 입(또는 눈) 영역만 원본 프레임 픽셀로 되돌리면 말하고 깜빡이는
움직임이 원본 그대로 살아난다. 68점 랜드마크는 buffalo_l에 이미 들어
있으므로 추가 모델이 필요 없다.
"""

from __future__ import annotations

from typing import Optional

import cv2
import numpy as np

# 표준 68점 배치에서의 부위별 인덱스
MOUTH = slice(48, 68)       # 바깥 입술 12점 + 안쪽 입술 8점
LEFT_EYE = slice(36, 42)
RIGHT_EYE = slice(42, 48)


def _landmarks(face) -> Optional[np.ndarray]:
    lm = getattr(face, "landmark_68", None)
    if lm is None:
        return None
    arr = np.asarray(lm, dtype=np.float32)
    if arr.ndim != 2 or arr.shape[0] != 68:
        return None
    return arr


def _poly_mask(points: np.ndarray, shape, expand: float, feather: float) -> Optional[np.ndarray]:
    """점들을 감싸는 부드러운 마스크(0~1)를 만든다.

    expand: 중심에서 바깥으로 넓히는 비율. 입은 벌릴 때 턱까지 움직이므로
            점만 딱 덮으면 경계에서 원본과 스왑이 어긋나 보인다.
    feather: 경계를 흐리는 정도. 부위 크기에 비례해 정한다.
    """
    h, w = shape[:2]
    pts = np.asarray(points, dtype=np.float32)
    if pts.shape[0] < 3:
        return None

    center = pts.mean(axis=0)
    pts = center + (pts - center) * (1.0 + max(0.0, expand))

    hull = cv2.convexHull(pts.astype(np.int32))
    mask = np.zeros((h, w), dtype=np.uint8)
    cv2.fillConvexPoly(mask, hull, 255)

    span = float(max(np.ptp(pts[:, 0]), np.ptp(pts[:, 1])))
    k = max(3, int(span * max(0.0, feather))) | 1  # 커널은 홀수여야 한다
    blurred = cv2.GaussianBlur(mask, (k, k), 0).astype(np.float32) / 255.0
    return np.clip(blurred, 0.0, 1.0)


def mouth_mask(face, shape, expand: float = 0.35, feather: float = 0.45) -> Optional[np.ndarray]:
    """입 영역 마스크. 랜드마크가 없으면 None."""
    lm = _landmarks(face)
    if lm is None:
        return None
    return _poly_mask(lm[MOUTH], shape, expand, feather)


def eyes_mask(face, shape, expand: float = 0.55, feather: float = 0.5) -> Optional[np.ndarray]:
    """양쪽 눈 영역 마스크 (깜빡임·시선을 원본대로 두고 싶을 때)."""
    lm = _landmarks(face)
    if lm is None:
        return None
    h, w = shape[:2]
    out = np.zeros((h, w), dtype=np.float32)
    for part in (LEFT_EYE, RIGHT_EYE):
        m = _poly_mask(lm[part], shape, expand, feather)
        if m is not None:
            out = np.maximum(out, m)
    return out if out.max() > 0 else None


def restore_region(
    swapped_bgr: np.ndarray,
    original_bgr: np.ndarray,
    mask: np.ndarray,
    strength: float = 1.0,
) -> np.ndarray:
    """마스크 영역을 원본 픽셀로 되돌린다.

    strength 1.0이면 그 부분이 완전히 원본, 낮추면 스왑 결과와 섞인다.
    """
    if mask is None:
        return swapped_bgr
    alpha = (np.clip(mask, 0.0, 1.0) * float(np.clip(strength, 0.0, 1.0)))[..., None]
    merged = original_bgr.astype(np.float32) * alpha + swapped_bgr.astype(np.float32) * (1.0 - alpha)
    return merged.astype(np.uint8)


def preserve_expression(
    swapped_bgr: np.ndarray,
    original_bgr: np.ndarray,
    faces,
    mouth: float = 0.0,
    eyes: float = 0.0,
) -> np.ndarray:
    """스왑된 프레임에서 입/눈을 원본 움직임으로 되살린다.

    mouth, eyes 는 각각 0~1 강도. 0이면 건드리지 않는다.
    """
    if mouth <= 0.0 and eyes <= 0.0:
        return swapped_bgr

    out = swapped_bgr
    for f in faces:
        if mouth > 0.0:
            m = mouth_mask(f, out.shape)
            out = restore_region(out, original_bgr, m, mouth)
        if eyes > 0.0:
            m = eyes_mask(f, out.shape)
            out = restore_region(out, original_bgr, m, eyes)
    return out
