from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import numpy as np


@dataclass
class DetectedFace:
    bbox: np.ndarray
    kps: np.ndarray
    det_score: float
    embedding: np.ndarray
    raw: object
    gender: int = -1  # 0 = 여성, 1 = 남성, -1 = 알 수 없음

    @property
    def area(self) -> float:
        x1, y1, x2, y2 = self.bbox
        return float(max(0.0, x2 - x1) * max(0.0, y2 - y1))

    @property
    def is_female(self) -> bool:
        return self.gender == 0

    @property
    def is_male(self) -> bool:
        return self.gender == 1


class FaceDetector:
    def __init__(self, model_name: str = "buffalo_l", providers: Optional[List[str]] = None, det_size: int = 640):
        import insightface

        self.app = insightface.app.FaceAnalysis(
            name=model_name,
            providers=providers or ["CPUExecutionProvider"],
        )
        self.app.prepare(ctx_id=0, det_size=(det_size, det_size))

    @staticmethod
    def _read_gender(f) -> int:
        g = getattr(f, "gender", None)
        if g is None:
            sex = getattr(f, "sex", None)
            if sex == "F":
                return 0
            if sex == "M":
                return 1
            return -1
        try:
            return int(g)
        except (TypeError, ValueError):
            return -1

    def detect(self, image_bgr: np.ndarray) -> List[DetectedFace]:
        faces = self.app.get(image_bgr)
        return [
            DetectedFace(
                bbox=np.asarray(f.bbox, dtype=np.float32),
                kps=np.asarray(f.kps, dtype=np.float32),
                det_score=float(getattr(f, "det_score", 0.0)),
                embedding=np.asarray(getattr(f, "normed_embedding", getattr(f, "embedding", None)), dtype=np.float32),
                raw=f,
                gender=self._read_gender(f),
            )
            for f in faces
        ]

    def select_targets(self, faces: List[DetectedFace], mode: str = "largest") -> List[DetectedFace]:
        """교체 대상 얼굴 목록 반환.

        mode: largest(가장 큰 얼굴 하나) / all(모두) / female(여성) / male(남성)
        """
        if not faces:
            return []
        if mode == "largest":
            best = max(faces, key=lambda f: f.area)
            return [best]
        if mode == "all":
            return list(faces)
        if mode == "female":
            return [f for f in faces if f.is_female]
        if mode == "male":
            return [f for f in faces if f.is_male]
        raise ValueError(f"unknown target mode: {mode}")

    def select(self, faces: List[DetectedFace], strategy: str = "largest", index: int = 0) -> Optional[DetectedFace]:
        if not faces:
            return None
        if strategy == "largest":
            return max(faces, key=lambda f: f.area)
        if strategy == "first":
            return faces[0]
        if strategy == "index":
            if index < 0 or index >= len(faces):
                return None
            return faces[index]
        raise ValueError(f"unknown face selection strategy: {strategy}")
