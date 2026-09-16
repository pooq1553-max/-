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

        prov = providers or ["CPUExecutionProvider"]
        # 메모리 아레나를 끄지 않으면 긴 영상 처리 중 사용량이 계속 불어나
        # 프로세스가 강제 종료된다. insightface 버전에 따라 sess_options를
        # 받지 않을 수 있으므로 실패하면 기본 방식으로 되돌린다.
        try:
            import onnxruntime
            so = onnxruntime.SessionOptions()
            so.enable_cpu_mem_arena = False
            self.swapper = insightface.model_zoo.get_model(
                str(model_path), sess_options=so, providers=prov
            )
        except Exception:
            self.swapper = insightface.model_zoo.get_model(
                str(model_path), providers=prov
            )

    def swap(self, target_image_bgr: np.ndarray, target_face: DetectedFace, source_face: DetectedFace) -> np.ndarray:
        return self.swapper.get(target_image_bgr, target_face.raw, source_face.raw, paste_back=True)
