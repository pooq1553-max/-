from __future__ import annotations

from pathlib import Path
from typing import List, Optional

import numpy as np

from .detector import DetectedFace


class FaceSwapper:
    def __init__(self, model_path: str | Path, providers: Optional[List[str]] = None):
        import insightface

        model_path = Path(model_path)
        if not model_path.exists():
            raise FileNotFoundError(
                f"swap model not found at {model_path}. "
                "run `python download_models.py` first."
            )

        self.swapper = insightface.model_zoo.get_model(
            str(model_path),
            providers=providers or ["CPUExecutionProvider"],
        )

    def swap(self, target_image_bgr: np.ndarray, target_face: DetectedFace, source_face: DetectedFace) -> np.ndarray:
        return self.swapper.get(target_image_bgr, target_face.raw, source_face.raw, paste_back=True)
