"""GFPGAN(ONNX) 기반 얼굴 화질 개선.

inswapper는 128x128 얼굴 패치를 만들기 때문에 고해상도 영상에서는 얼굴만
살짝 뭉개져 보인다. 스왑된 얼굴을 512x512로 정렬해 GFPGAN에 통과시킨 뒤
원래 자리에 부드럽게 합성해서 선명도를 되살린다.

공식 gfpgan 패키지(torch + basicsr) 대신 ONNX 런타임을 쓴다. 이미 스왑에
쓰고 있는 onnxruntime 하나면 되고 추가 의존성이 없다.
"""

from __future__ import annotations

import urllib.request
from pathlib import Path
from typing import Callable, List, Optional

import cv2
import numpy as np

ENHANCER_FILENAME = "gfpgan_1.4.onnx"

# 미러는 수시로 바뀔 수 있어 여러 곳을 순서대로 시도한다.
# 해시 대신 실제로 ONNX를 열어 입력 형상을 확인하는 방식으로 무결성을 검증한다.
ENHANCER_URLS = [
    "https://github.com/facefusion/facefusion-assets/releases/download/models/gfpgan_1.4.onnx",
    "https://huggingface.co/facefusion/models/resolve/main/gfpgan_1.4.onnx",
    "https://huggingface.co/countfloyd/deepfake/resolve/main/GFPGANv1.4.onnx",
]

DownloadProgress = Callable[[int, int], None]


def default_models_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "models"


def enhancer_model_path(models_dir: str | Path | None = None) -> Path:
    base = Path(models_dir) if models_dir else default_models_dir()
    return base / ENHANCER_FILENAME


def verify_enhancer_model(path: str | Path) -> bool:
    """ONNX를 실제로 열어 512x512 얼굴 입력을 받는 모델인지 확인."""
    try:
        import onnxruntime
        sess = onnxruntime.InferenceSession(
            str(path), providers=["CPUExecutionProvider"]
        )
        shape = sess.get_inputs()[0].shape
        # 기대 형상: [1, 3, 512, 512] (배치/동적 축은 문자열일 수 있음)
        return len(shape) == 4 and shape[-1] == 512 and shape[-2] == 512
    except Exception:
        return False


def download_enhancer(
    models_dir: str | Path | None = None,
    progress: Optional[DownloadProgress] = None,
) -> Path:
    """화질 개선 모델을 내려받는다 (약 330MB). 실패 시 RuntimeError."""
    dest = enhancer_model_path(models_dir)
    dest.parent.mkdir(parents=True, exist_ok=True)

    if dest.exists() and verify_enhancer_model(dest):
        return dest

    tmp = dest.with_suffix(dest.suffix + ".part")
    errors: List[str] = []
    for url in ENHANCER_URLS:
        try:
            with urllib.request.urlopen(url, timeout=60) as resp, tmp.open("wb") as out:
                total = int(resp.headers.get("Content-Length", "0"))
                seen = 0
                while True:
                    chunk = resp.read(1 << 20)
                    if not chunk:
                        break
                    out.write(chunk)
                    seen += len(chunk)
                    if progress:
                        progress(seen, total)
            tmp.replace(dest)
            if verify_enhancer_model(dest):
                return dest
            errors.append(f"{url}: 받은 파일이 올바른 모델이 아님")
            dest.unlink(missing_ok=True)
        except Exception as e:
            errors.append(f"{url}: {e}")
            tmp.unlink(missing_ok=True)

    raise RuntimeError(
        "화질 개선 모델을 자동으로 받지 못했어요.\n"
        f"아래 파일을 직접 받아서 여기에 두세요:\n{dest}\n\n"
        "시도한 주소:\n" + "\n".join(f"  · {e}" for e in errors)
    )


class FaceEnhancer:
    """스왑된 얼굴 하나를 정렬 → 복원 → 원위치 합성."""

    def __init__(self, model_path: str | Path, providers: Optional[List[str]] = None):
        import onnxruntime

        model_path = Path(model_path)
        if not model_path.exists():
            raise FileNotFoundError(f"화질 개선 모델이 없어요: {model_path}")

        self.session = onnxruntime.InferenceSession(
            str(model_path), providers=providers or ["CPUExecutionProvider"]
        )
        self.input_name = self.session.get_inputs()[0].name
        self.output_name = self.session.get_outputs()[0].name
        self.size = 512
        self._mask_cache: Optional[np.ndarray] = None

    # ------------------------------------------------------------ internals
    @staticmethod
    def _preprocess(face_bgr: np.ndarray) -> np.ndarray:
        rgb = cv2.cvtColor(face_bgr, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        rgb = (rgb - 0.5) / 0.5          # [0,1] -> [-1,1]
        chw = rgb.transpose(2, 0, 1)     # HWC -> CHW
        return chw[None, ...].astype(np.float32)

    @staticmethod
    def _postprocess(out: np.ndarray) -> np.ndarray:
        arr = out[0] if out.ndim == 4 else out
        arr = np.clip(arr, -1.0, 1.0)
        arr = (arr + 1.0) / 2.0 * 255.0  # [-1,1] -> [0,255]
        hwc = arr.transpose(1, 2, 0)
        return cv2.cvtColor(hwc.astype(np.uint8), cv2.COLOR_RGB2BGR)

    def _soft_mask(self) -> np.ndarray:
        """가장자리가 부드럽게 사라지는 마스크 (경계선 안 보이게)."""
        if self._mask_cache is not None:
            return self._mask_cache
        size = self.size
        mask = np.zeros((size, size), dtype=np.float32)
        pad = int(size * 0.08)
        mask[pad:size - pad, pad:size - pad] = 1.0
        blur = int(size * 0.12) | 1  # 홀수여야 함
        mask = cv2.GaussianBlur(mask, (blur, blur), 0)
        self._mask_cache = np.clip(mask, 0.0, 1.0)
        return self._mask_cache

    # ---------------------------------------------------------------- public
    def enhance(self, image_bgr: np.ndarray, kps: np.ndarray, blend: float = 0.8) -> np.ndarray:
        """kps 위치의 얼굴 하나를 개선한 새 이미지를 반환.

        blend: 1.0이면 복원 결과 그대로, 낮출수록 원본을 섞어 자연스럽게.
        """
        from insightface.utils import face_align

        h, w = image_bgr.shape[:2]
        aligned, M = face_align.norm_crop2(image_bgr, kps, self.size)

        out = self.session.run([self.output_name], {self.input_name: self._preprocess(aligned)})[0]
        enhanced = self._postprocess(out)

        blend = float(np.clip(blend, 0.0, 1.0))
        if blend < 1.0:
            enhanced = cv2.addWeighted(enhanced, blend, aligned, 1.0 - blend, 0.0)

        inv = cv2.invertAffineTransform(M)
        back = cv2.warpAffine(enhanced, inv, (w, h), borderMode=cv2.BORDER_CONSTANT, borderValue=0)
        mask = cv2.warpAffine(self._soft_mask(), inv, (w, h),
                              borderMode=cv2.BORDER_CONSTANT, borderValue=0)
        alpha = np.clip(mask, 0.0, 1.0)[..., None]

        merged = back.astype(np.float32) * alpha + image_bgr.astype(np.float32) * (1.0 - alpha)
        return merged.astype(np.uint8)

    def enhance_faces(self, image_bgr: np.ndarray, faces, blend: float = 0.8) -> np.ndarray:
        result = image_bgr
        for f in faces:
            kps = getattr(f, "kps", None)
            if kps is None:
                continue
            result = self.enhance(result, kps, blend=blend)
        return result
