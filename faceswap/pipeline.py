from __future__ import annotations

from pathlib import Path
from typing import List, Optional

import cv2
import numpy as np

from .detector import DetectedFace, FaceDetector
from .swapper import FaceSwapper


class FaceSwapPipeline:
    def __init__(
        self,
        swap_model_path: str | Path,
        detector_name: str = "buffalo_l",
        providers: Optional[List[str]] = None,
        det_size: int = 640,
    ):
        self.detector = FaceDetector(model_name=detector_name, providers=providers, det_size=det_size)
        self.swapper = FaceSwapper(model_path=swap_model_path, providers=providers)

    @staticmethod
    def _load(path: str | Path) -> np.ndarray:
        path = Path(path)
        with open(path, "rb") as f:
            data = np.frombuffer(f.read(), np.uint8)
        img = cv2.imdecode(data, cv2.IMREAD_COLOR)
        if img is None:
            raise FileNotFoundError(f"could not decode image: {path}")
        return img

    @staticmethod
    def _save(image_bgr: np.ndarray, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        ext = path.suffix if path.suffix else ".jpg"
        ok, buf = cv2.imencode(ext, image_bgr)
        if not ok:
            raise IOError(f"could not encode image: {path}")
        with open(path, "wb") as f:
            f.write(buf.tobytes())

    def swap_files(
        self,
        source_path: str | Path,
        target_path: str | Path,
        output_path: str | Path,
        source_face_selector: str = "largest",
        target_face_selector: str = "all",
        source_face_index: int = 0,
        target_face_index: int = 0,
    ) -> Path:
        source_img = self._load(source_path)
        target_img = self._load(target_path)

        source_faces = self.detector.detect(source_img)
        if not source_faces:
            raise RuntimeError(f"no face detected in source image: {source_path}")
        source_face = self.detector.select(source_faces, source_face_selector, source_face_index)
        if source_face is None:
            raise RuntimeError(f"source face selection returned nothing (strategy={source_face_selector})")

        target_faces = self.detector.detect(target_img)
        if not target_faces:
            raise RuntimeError(f"no face detected in target image: {target_path}")

        if target_face_selector == "all":
            picked: List[DetectedFace] = target_faces
        else:
            one = self.detector.select(target_faces, target_face_selector, target_face_index)
            if one is None:
                raise RuntimeError(f"target face selection returned nothing (strategy={target_face_selector})")
            picked = [one]

        result = target_img
        for tf in picked:
            result = self.swapper.swap(result, tf, source_face)

        out = Path(output_path)
        self._save(result, out)
        return out
