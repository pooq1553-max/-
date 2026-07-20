from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .pipeline import FaceSwapPipeline

DEFAULT_MODEL_PATH = Path(__file__).resolve().parent.parent / "models" / "inswapper_128.onnx"


def _providers(device: str) -> list[str]:
    device = device.lower()
    if device == "cpu":
        return ["CPUExecutionProvider"]
    if device == "cuda":
        return ["CUDAExecutionProvider", "CPUExecutionProvider"]
    if device == "coreml":
        return ["CoreMLExecutionProvider", "CPUExecutionProvider"]
    raise SystemExit(f"unknown device: {device} (expected cpu / cuda / coreml)")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="faceswap",
        description="Swap the face from --source onto the body/scene in --target.",
    )
    p.add_argument("--source", "-s", required=True, help="image containing the face to copy from")
    p.add_argument("--target", "-t", required=True, help="image whose face(s) will be replaced")
    p.add_argument("--output", "-o", required=True, help="path to write the result image")
    p.add_argument("--model", default=str(DEFAULT_MODEL_PATH), help="path to inswapper_128.onnx")
    p.add_argument("--device", default="cpu", choices=["cpu", "cuda", "coreml"], help="execution provider")
    p.add_argument("--det-size", type=int, default=640, help="detector input size (square)")
    p.add_argument(
        "--source-face",
        default="largest",
        choices=["largest", "first", "index"],
        help="which face in the source image to use",
    )
    p.add_argument(
        "--target-face",
        default="all",
        choices=["all", "largest", "first", "index"],
        help="which face(s) in the target image to replace",
    )
    p.add_argument("--source-face-index", type=int, default=0, help="0-based index if --source-face=index")
    p.add_argument("--target-face-index", type=int, default=0, help="0-based index if --target-face=index")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    pipeline = FaceSwapPipeline(
        swap_model_path=args.model,
        providers=_providers(args.device),
        det_size=args.det_size,
    )

    out = pipeline.swap_files(
        source_path=args.source,
        target_path=args.target,
        output_path=args.output,
        source_face_selector=args.source_face,
        target_face_selector=args.target_face,
        source_face_index=args.source_face_index,
        target_face_index=args.target_face_index,
    )
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
