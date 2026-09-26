"""Frame-by-frame video face swap using the same pipeline as photos."""

from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path
from typing import Callable, List, Optional, Tuple

import cv2
import numpy as np

from .masks import preserve_expression
from .pipeline import FaceSwapPipeline

ProgressCallback = Callable[[int, int, str], None]
CancelPredicate = Callable[[], bool]


def _imread_unicode(path: str | Path) -> np.ndarray:
    with open(path, "rb") as f:
        data = np.frombuffer(f.read(), np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None:
        raise IOError(f"could not read image: {path}")
    return img


def _ffmpeg_exe() -> Optional[str]:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return shutil.which("ffmpeg")


def probe_video(path: str | Path) -> dict:
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise IOError(f"could not open video: {path}")
    info = {
        "fps": cap.get(cv2.CAP_PROP_FPS) or 0.0,
        "frames": int(cap.get(cv2.CAP_PROP_FRAME_COUNT)),
        "width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
        "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
    }
    cap.release()
    if info["fps"] > 0 and info["frames"] > 0:
        info["duration_sec"] = info["frames"] / info["fps"]
    else:
        info["duration_sec"] = 0.0
    return info


def _free_path(path: Path) -> Path:
    """path가 이미 있거나 못 쓸 때 옆에 번호를 붙인 빈 경로를 찾는다."""
    for i in range(1, 1000):
        cand = path.with_name(f"{path.stem}_{i}{path.suffix}")
        if not cand.exists():
            return cand
    return path.with_name(f"{path.stem}_{int(time.time())}{path.suffix}")


def _deliver_output(
    tmp_video: Path,
    output_path: Path,
    source_video: Path,
    ffmpeg: Optional[str],
) -> tuple[Path, Optional[str]]:
    """처리 결과를 최종 위치로 옮긴다.

    오래 걸린 작업이므로 결과를 절대 잃지 않는 것이 최우선이다. 원하는
    경로에 못 쓰면 옆에 번호를 붙여서라도 반드시 남긴다.
    반환: (실제 저장된 경로, 경고 문구 또는 None)
    """
    problems: List[str] = []

    # 1순위: 원본 음성까지 합쳐서 저장
    if ffmpeg:
        result = subprocess.run(
            [
                ffmpeg, "-y",
                "-i", str(tmp_video),
                "-i", str(source_video),
                "-c:v", "copy",
                "-c:a", "aac",
                "-map", "0:v:0",
                "-map", "1:a:0?",
                "-shortest",
                str(output_path),
            ],
            capture_output=True,
        )
        if result.returncode == 0 and output_path.exists():
            return output_path, None
        problems.append(
            "음성 합치기 실패: "
            + result.stderr.decode("utf-8", errors="replace").strip()[-300:]
        )

    # 2순위: 음성 없이 영상만 그 경로에 저장
    try:
        shutil.copy2(tmp_video, output_path)
        if problems:
            return output_path, ("원본 음성을 합치지 못해 영상만 저장했어요.\n"
                                 + "\n".join(problems))
        return output_path, (
            "ffmpeg이 없어 원본 음성 없이 영상만 저장했어요.\n"
            "음성까지 넣으려면 PowerShell에서:\n"
            "  .\\.venv\\Scripts\\python.exe -m pip install imageio-ffmpeg"
        )
    except Exception as e:
        problems.append(f"지정한 경로에 저장 실패: {e}")

    # 3순위: 어디든 남긴다. 여기서 포기하면 작업 결과가 통째로 사라진다.
    alt = _free_path(output_path)
    try:
        shutil.copy2(tmp_video, alt)
        return alt, (
            f"지정한 경로에 저장할 수 없어 다른 이름으로 저장했어요:\n{alt}\n\n"
            "원래 경로에 못 쓴 이유는 보통 둘 중 하나예요.\n"
            "  · 저장 경로를 원본 영상과 같은 파일로 지정함\n"
            "  · 그 파일이 다른 프로그램(플레이어 등)에서 열려 있음\n\n"
            + "\n".join(problems)
        )
    except Exception as e:
        problems.append(f"대체 경로에도 저장 실패: {e}")

    raise RuntimeError(
        "처리는 끝났지만 결과를 저장하지 못했어요.\n\n" + "\n".join(problems)
    )


def process_video(
    target_video_path: str | Path,
    output_video_path: str | Path,
    frame_fn: Callable[[np.ndarray], np.ndarray],
    resize_height: Optional[int] = None,
    progress: Optional[ProgressCallback] = None,
    cancel: Optional[CancelPredicate] = None,
) -> Tuple[Path, Optional[str]]:
    """동영상을 프레임 단위로 frame_fn에 통과시켜 저장한다.

    프레임을 어떻게 바꿀지만 frame_fn이 정하고, 읽기·크기 조정·쓰기·진행
    보고·취소·원본 음성 합치기·저장 실패 대비는 전부 여기서 처리한다.
    스왑과 모자이크가 같은 안전장치를 공유하도록 하기 위한 공통 루프다.

    반환: (실제로 저장된 경로, 경고 문구 또는 None)
    """
    output_video_path = Path(output_video_path)

    # 같은 파일을 읽으면서 덮어쓸 수는 없다. 처리를 다 끝낸 뒤 저장 단계에서
    # 실패하면 오래 걸린 작업이 통째로 날아가므로 시작 전에 막는다.
    try:
        same_file = Path(target_video_path).resolve() == output_video_path.resolve()
    except OSError:
        same_file = False
    if same_file:
        raise ValueError(
            "저장 경로가 원본 동영상과 같은 파일이에요.\n"
            "원본을 읽으면서 같은 파일에 덮어쓸 수는 없어요.\n"
            "다른 이름으로 저장 경로를 지정해주세요."
        )

    cap = cv2.VideoCapture(str(target_video_path))
    if not cap.isOpened():
        raise IOError(f"동영상을 열 수 없어요: {target_video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    src_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    src_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    if resize_height and resize_height > 0 and resize_height < src_height:
        out_height = resize_height
        out_width = int(round(src_width * (out_height / src_height)))
        if out_width % 2 == 1:
            out_width += 1
    else:
        out_height = src_height
        out_width = src_width

    output_video_path = Path(output_video_path)
    output_video_path.parent.mkdir(parents=True, exist_ok=True)

    # 중간 결과를 저장 폴더 옆에 둔다. 임시 폴더에 두면 프로세스가 강제 종료될 때
    # (메모리 부족 등) 처리분이 통째로 사라지지만, 여기에 두면 .partial 파일로
    # 남아 건질 수 있다. 저장 폴더에 못 쓰는 경우도 수십 분 뒤가 아니라 지금 드러난다.
    tmp_video = output_video_path.with_name(output_video_path.stem + ".partial.mp4")
    saved_path: Optional[Path] = None
    warning: Optional[str] = None
    try:
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(str(tmp_video), fourcc, fps, (out_width, out_height))
        if not writer.isOpened():
            cap.release()
            raise IOError(
                f"결과 파일을 만들 수 없어요: {tmp_video}\n"
                "저장 폴더에 쓰기 권한이 있는지, 경로가 올바른지 확인해주세요."
            )

        frame_idx = 0
        need_resize = (out_width, out_height) != (src_width, src_height)
        # 화질 개선을 켜면 프레임당 수 초가 걸린다. 프레임 수 기준으로 보고하면
        # 갱신이 너무 뜸해지므로 경과 시간 기준으로 보고한다.
        last_report = 0.0
        report_interval = 0.5
        try:
            while True:
                if cancel and cancel():
                    if progress:
                        progress(frame_idx, total_frames, "취소됨")
                    raise RuntimeError("사용자가 취소했어요.")

                ret, frame = cap.read()
                if not ret:
                    break

                if need_resize:
                    frame = cv2.resize(frame, (out_width, out_height), interpolation=cv2.INTER_AREA)

                frame = frame_fn(frame)

                writer.write(frame)
                frame_idx += 1
                if progress:
                    now = time.monotonic()
                    if (now - last_report >= report_interval
                            or frame_idx == 1
                            or frame_idx == total_frames):
                        last_report = now
                        progress(frame_idx, total_frames,
                                 f"프레임 처리 중 {frame_idx}/{total_frames}")
        finally:
            cap.release()
            writer.release()

        if progress:
            progress(frame_idx, total_frames, "결과 저장 중...")
        saved_path, warning = _deliver_output(
            tmp_video, output_video_path, Path(target_video_path), _ffmpeg_exe()
        )
    finally:
        # 저장까지 끝났으면 중간 파일은 지운다.
        # 중간에 죽거나 실패하면 .partial 파일이 남아 건질 수 있다.
        if saved_path is not None:
            try:
                tmp_video.unlink(missing_ok=True)
            except Exception:
                pass

    if progress:
        progress(total_frames, total_frames, "완료")
    return saved_path, warning


def swap_video(
    pipeline: FaceSwapPipeline,
    source_image_path: str | Path,
    target_video_path: str | Path,
    output_video_path: str | Path,
    replace_all: bool = False,
    target_mode: Optional[str] = None,
    resize_height: Optional[int] = None,
    source_face=None,
    enhancer=None,
    enhance_blend: float = 0.8,
    preserve_mouth: float = 0.0,
    preserve_eyes: float = 0.0,
    progress: Optional[ProgressCallback] = None,
    cancel: Optional[CancelPredicate] = None,
) -> Tuple[Path, Optional[str]]:
    """동영상의 얼굴을 바꿔 저장한다.

    반환: (실제로 저장된 경로, 경고 문구 또는 None). 지정한 경로에 쓸 수
    없으면 다른 이름으로라도 저장하고 그 사정을 경고로 돌려준다.
    """
    # target_mode 우선: largest / all / female / male.
    # 미지정 시 기존 replace_all 로 결정(all 또는 largest).
    if target_mode is None:
        target_mode = "all" if replace_all else "largest"

    if source_face is not None:
        # 여러 장에서 미리 만들어 둔 평균 정체성을 그대로 사용
        src_face = source_face
    else:
        src_img = _imread_unicode(source_image_path)
        src_faces = pipeline.detector.detect(src_img)
        if not src_faces:
            raise RuntimeError("소스 사진에서 얼굴을 찾지 못했어요.")
        src_face = pipeline.detector.select(src_faces, "largest")

    keep_expression = preserve_mouth > 0.0 or preserve_eyes > 0.0

    def frame_fn(frame: np.ndarray) -> np.ndarray:
        tgt_faces = pipeline.detector.detect(frame)
        if not tgt_faces:
            return frame
        to_replace = pipeline.detector.select_targets(tgt_faces, target_mode)
        if not to_replace:
            return frame

        original = frame.copy() if keep_expression else None
        for tf in to_replace:
            frame = pipeline.swapper.swap(frame, tf, src_face)

        if keep_expression:
            # 입·눈을 원본 픽셀로 되돌려 말하고 깜빡이는 움직임을 살린다.
            # 화질 개선 전에 해야 되살린 부분까지 같이 다듬어져 자연스럽다.
            frame = preserve_expression(
                frame, original, to_replace,
                mouth=preserve_mouth, eyes=preserve_eyes,
            )

        if enhancer is not None:
            # 스왑된 얼굴 자리를 그대로 다시 정렬해 화질 복원
            frame = enhancer.enhance_faces(frame, to_replace, blend=enhance_blend)
        return frame

    return process_video(
        target_video_path=target_video_path,
        output_video_path=output_video_path,
        frame_fn=frame_fn,
        resize_height=resize_height,
        progress=progress,
        cancel=cancel,
    )
