"""Download the pretrained weights needed by the faceswap CLI.

Weights are large and licensed separately, so they are not committed to git.
Run this script once after `pip install -r requirements.txt`.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import urllib.request
from pathlib import Path

MODEL_FILENAME = "inswapper_128.onnx"
MODEL_SHA256 = "e4a3f08c753cb72d04e10aa0f7dbe3deebbf39567d4ead6dce08e98aa49e16af"
MODEL_URLS = [
    "https://huggingface.co/deepinsight/inswapper/resolve/main/inswapper_128.onnx",
    "https://huggingface.co/ezioruan/inswapper_128.onnx/resolve/main/inswapper_128.onnx",
]


def _sha256(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def _download(url: str, dest: Path) -> None:
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url, timeout=60) as resp, tmp.open("wb") as out:
        total = int(resp.headers.get("Content-Length", "0"))
        seen = 0
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            out.write(chunk)
            seen += len(chunk)
            if total:
                pct = seen * 100 / total
                print(f"\r  {seen / 1e6:6.1f} / {total / 1e6:6.1f} MB ({pct:5.1f}%)", end="", flush=True)
            else:
                print(f"\r  {seen / 1e6:6.1f} MB", end="", flush=True)
    print()
    tmp.replace(dest)


def fetch_swap_model(models_dir: Path, verify: bool = True) -> Path:
    models_dir.mkdir(parents=True, exist_ok=True)
    dest = models_dir / MODEL_FILENAME
    if dest.exists() and verify and _sha256(dest) == MODEL_SHA256:
        print(f"{dest} already present, checksum OK")
        return dest

    last_err: Exception | None = None
    for url in MODEL_URLS:
        try:
            print(f"downloading {url}")
            _download(url, dest)
            break
        except Exception as e:
            last_err = e
            print(f"  failed: {e}")
    else:
        raise SystemExit(
            "\ncould not download the swap model automatically.\n"
            f"place the file manually at: {dest}\n"
            f"expected sha256: {MODEL_SHA256}\n"
            f"last error: {last_err}"
        )

    if verify:
        got = _sha256(dest)
        if got != MODEL_SHA256:
            dest.unlink(missing_ok=True)
            raise SystemExit(
                f"checksum mismatch: expected {MODEL_SHA256}, got {got}. "
                "delete the file and retry."
            )
    print(f"saved {dest}")
    return dest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--models-dir",
        default=str(Path(__file__).resolve().parent / "models"),
        help="where to place downloaded models",
    )
    parser.add_argument("--no-verify", action="store_true", help="skip sha256 verification")
    parser.add_argument(
        "--enhancer",
        action="store_true",
        help="also download the GFPGAN face-enhancement model (~330MB)",
    )
    args = parser.parse_args()

    fetch_swap_model(Path(args.models_dir), verify=not args.no_verify)

    if args.enhancer:
        from faceswap.enhance import download_enhancer

        print("\ndownloading face enhancement model (GFPGAN)...")

        def _prog(seen, total):
            if total:
                print(f"\r  {seen / 1e6:6.1f} / {total / 1e6:6.1f} MB", end="", flush=True)
            else:
                print(f"\r  {seen / 1e6:6.1f} MB", end="", flush=True)

        path = download_enhancer(Path(args.models_dir), progress=_prog)
        print(f"\nsaved {path}")

    print(
        "\nnote: InsightFace's detector weights (buffalo_l) are downloaded lazily "
        "the first time the CLI runs, into ~/.insightface/."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
