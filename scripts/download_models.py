"""로컬 음성 모델(TTS·STT)을 models/ 에 내려받는다. 이미 있으면 건너뛴다.

사용법: python scripts/download_models.py
"""
import shutil
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

from step1 import PROJECT_ROOT

MODELS_DIR = PROJECT_ROOT / "models"
BASE = "https://github.com/k2-fsa/sherpa-onnx/releases/download/"
MODELS = {
    "vits-mimic3-ko_KO-kss_low": "tts-models/vits-mimic3-ko_KO-kss_low.tar.bz2",
    "sherpa-onnx-zipformer-korean-2024-06-24": "asr-models/sherpa-onnx-zipformer-korean-2024-06-24.tar.bz2",
}
# 받아쓰기는 int8 모델만 쓰므로 큰 원본 모델은 지운다
REMOVE_AFTER = ["encoder-epoch-99-avg-1.onnx", "decoder-epoch-99-avg-1.onnx", "joiner-epoch-99-avg-1.onnx"]


def main():
    MODELS_DIR.mkdir(exist_ok=True)
    for name, path in MODELS.items():
        target = MODELS_DIR / name
        if target.is_dir():
            print(f"있음: {name}")
            continue
        print(f"내려받는 중: {name} …")
        with tempfile.TemporaryDirectory(dir=MODELS_DIR) as tmp:
            archive = Path(tmp) / "m.tar.bz2"
            urllib.request.urlretrieve(BASE + path, archive)
            with tarfile.open(archive) as tar:
                tar.extractall(tmp, filter="data")
            shutil.move(str(Path(tmp) / name), target)  # 다 풀린 뒤에만 옮김
        for f in REMOVE_AFTER:
            (target / f).unlink(missing_ok=True)
        print(f"완료: {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
