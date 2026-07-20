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

    @property
    def area(self) -> float:
        x1, y1, x2, y2 = self.bbox
        return float(max(0.0, x2 - x1) * max(0.0, y2 - y1))


class FaceDetector:
    def __init__(self, model_name: str = "buffalo_l", providers: Optional[List[str]] = None, det_size: int = 640):
        import insightface

        self.app = insightface.app.FaceAnalysis(
            name=model_name,
            providers=providers or ["CPUExecutionProvider"],
        )
        self.app.prepare(ctx_id=0, det_size=(det_size, det_size))

    def detect(self, image_bgr: np.ndarray) -> List[DetectedFace]:
        faces = self.app.get(image_bgr)
        return [
            DetectedFace(
                bbox=np.asarray(f.bbox, dtype=np.float32),
                kps=np.asarray(f.kps, dtype=np.float32),
                det_score=float(getattr(f, "det_score", 0.0)),
                embedding=np.asarray(getattr(f, "normed_embedding", getattr(f, "embedding", None)), dtype=np.float32),
                raw=f,
            )
            for f in faces
        ]

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
