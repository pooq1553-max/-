"""윈도우에서도 안전하게 파일을 다루는 도구.

1. 윈도우는 다른 프로그램(브라우저 재생 등)이 쓰고 있는 파일을 바꾸거나 지울 수 없다 → 잠깐씩 기다리며 다시 시도.
2. OpenCV 는 윈도우에서 한글이 들어간 파일 경로를 열거나 저장하지 못한다
   → 그림은 파이썬으로 읽고 쓰고, 영상은 영어 이름의 임시 연결 파일로 연다.
"""
import os
import shutil
import time
from contextlib import contextmanager
from pathlib import Path

import numpy as np

RETRY_SECONDS = 10.0


class FileBusyError(OSError):
    pass


def _retry(action, what, seconds=RETRY_SECONDS):
    end = time.time() + seconds
    while True:
        try:
            return action()
        except PermissionError as e:
            if time.time() >= end:
                raise FileBusyError(
                    f"{what} 파일을 다른 프로그램이 쓰고 있어 바꾸지 못했습니다. "
                    f"브라우저에서 재생 중인 영상·음성을 멈추고 다시 시도하세요. ({e.filename})") from e
            time.sleep(0.25)


def replace(src, dst, seconds=RETRY_SECONDS):
    _retry(lambda: os.replace(src, dst), Path(dst).name, seconds)


def unlink(path, seconds=RETRY_SECONDS):
    _retry(lambda: Path(path).unlink(missing_ok=True), Path(path).name, seconds)


def rmtree(path, seconds=RETRY_SECONDS):
    def go():
        if Path(path).exists():
            shutil.rmtree(path)
    _retry(go, Path(path).name, seconds)


def imread(path):
    import cv2
    data = np.fromfile(str(path), dtype=np.uint8)
    return cv2.imdecode(data, cv2.IMREAD_COLOR) if data.size else None


def imwrite(path, image, params=()):
    import cv2
    ok, buf = cv2.imencode(Path(path).suffix or ".jpg", image, list(params))
    if not ok:
        raise OSError(f"그림을 저장하지 못했습니다: {Path(path).name}")
    buf.tofile(str(path))


@contextmanager
def ascii_path(path, work_dir):
    """경로에 한글 등이 있으면 work_dir 안에 영어 이름의 연결(또는 복사본)을 만들어 그 경로를 준다."""
    path = Path(path)
    if str(path).isascii():
        yield path
        return
    work_dir = Path(work_dir)
    if not str(work_dir).isascii():
        raise OSError(f"프로그램 폴더 경로에 한글이 있어 영상을 열 수 없습니다: {work_dir}\n"
                      "C:\\shorts 처럼 영어로 된 폴더로 옮겨 주세요.")
    work_dir.mkdir(parents=True, exist_ok=True)
    alias = work_dir / f".source_video{path.suffix.lower()}"
    alias.unlink(missing_ok=True)
    try:
        os.link(path, alias)
    except OSError:
        shutil.copy2(path, alias)
    try:
        yield alias
    finally:
        try:
            alias.unlink(missing_ok=True)
        except OSError:
            pass
