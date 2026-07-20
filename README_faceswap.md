# faceswap

CLI face-swap tool: takes a face from `--source`, replaces the face(s) in `--target`, writes the result.

Uses [InsightFace](https://github.com/deepinsight/insightface)'s `buffalo_l` for detection/landmarks and the `inswapper_128.onnx` swap model (SimSwap-family, ONNX).

## Quick start — Windows one-click

1. 이 레포를 ZIP으로 받아서 압축 풀기 (또는 `git clone`)
2. 폴더에서 **`setup.bat` 더블클릭** (Python·라이브러리·모델 자동 설치, 5~10분)
3. 바탕화면에 생긴 **FaceSwap** 아이콘 더블클릭 → 브라우저에 UI가 뜸
4. 사진 두 장 드래그해서 올리고 **스왑 실행** 버튼

앱 종료는 콘솔 창을 닫으면 됨. 사진은 100% 로컬 처리, 어디로도 안 올라감.

자세한 Windows 설치 안내와 트러블슈팅은 [WINDOWS.md](./WINDOWS.md).

## Quick start — Colab (파이썬 설치 없이)

`faceswap_colab.ipynb`을 Google Colab에 열고 셀을 순서대로 실행. 사진 두 장
업로드 → 결과 자동 다운로드. (사진은 구글 Colab 서버로 잠깐 올라감.)

## Install (Linux/Mac, 수동)

```bash
pip install -r requirements.txt
python download_models.py
python app.py     # GUI (브라우저)
# 또는 CLI
python -m faceswap -s face.jpg -t body.jpg -o out.jpg
```

`download_models.py` fetches `inswapper_128.onnx` (~554 MB) into `./models/`. InsightFace's detector weights download themselves on first run.

## Usage

```bash
# put the face from face.jpg onto every face in group_photo.jpg
python -m faceswap --source face.jpg --target group_photo.jpg --output out.jpg

# only replace the largest face in the target
python -m faceswap -s face.jpg -t group_photo.jpg -o out.jpg --target-face largest

# CUDA if you have onnxruntime-gpu installed
python -m faceswap -s face.jpg -t body.jpg -o out.jpg --device cuda
```

### Options

| flag | default | meaning |
|---|---|---|
| `--source` / `-s` | (required) | image with the face to copy from |
| `--target` / `-t` | (required) | image whose face(s) will be replaced |
| `--output` / `-o` | (required) | where to write the result |
| `--model` | `./models/inswapper_128.onnx` | path to the ONNX swap model |
| `--device` | `cpu` | `cpu`, `cuda`, or `coreml` |
| `--det-size` | `640` | detector input size |
| `--source-face` | `largest` | `largest` / `first` / `index` |
| `--target-face` | `all` | `all` / `largest` / `first` / `index` |
| `--source-face-index` | `0` | index if `--source-face=index` |
| `--target-face-index` | `0` | index if `--target-face=index` |

### As a library

```python
from faceswap import FaceSwapPipeline

pipe = FaceSwapPipeline(swap_model_path="models/inswapper_128.onnx")
pipe.swap_files("face.jpg", "body.jpg", "out.jpg")
```

## Notes on quality

- inswapper produces a 128×128 face patch; on high-res targets you may see softening. Optional GFPGAN/CodeFormer post-processing can sharpen it — not included here to keep the surface small.
- Very off-angle or occluded target faces detect poorly. Try lowering `--det-size` or picking a clearer target.

## Responsible use

Only swap faces onto images with the consent of the people depicted. Do not use this to create sexual content of anyone, to impersonate real people, or to produce material meant to deceive. Many jurisdictions (KR, EU, US states) now criminalize non-consensual synthetic imagery — the legal responsibility for what you generate is yours.
