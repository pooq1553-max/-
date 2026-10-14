"""2단계: 영상을 장면 단위로 나누고, 장면마다 대표 사진 2장과 정보를 저장한다.

사용법:
    python scripts/scenes.py                      # input/원본.mp4
    python scripts/scenes.py --input input/다른영상.mp4 --threshold 27

결과:
    frames/scene_001_a.jpg, scene_001_b.jpg …   장면마다 대표 사진 2장 (장면의 1/3, 2/3 지점)
    frames/한눈에보기.jpg                        모든 대표 사진을 한 장에 모은 것
    output/scenes.json                           장면 정보 (번호, 시간, 종류, 설명, 숫자 특징, 제외 여부)
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import cv2
from scenedetect import ContentDetector, detect

import winsafe
from scene_analyzers import ANALYZERS
from step1 import DEFAULT_INPUT, PROJECT_ROOT, StepError, open_folder

FRAMES_DIR = PROJECT_ROOT / "frames"
SCENES_JSON = PROJECT_ROOT / "output" / "scenes.json"
SAMPLE_COUNT = 6  # 숫자 특징 계산용으로 장면마다 읽는 프레임 수


class Video:
    def __init__(self, path):
        self.cap = cv2.VideoCapture(str(path))
        if not self.cap.isOpened():
            raise StepError(f"영상을 열 수 없습니다: {path}")
        self.fps = self.cap.get(cv2.CAP_PROP_FPS) or 30.0
        self.frame_count = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))

    def frame_at(self, index):
        index = max(0, min(index, self.frame_count - 1))
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, index)
        ok, frame = self.cap.read()
        return frame if ok else None

    def close(self):
        self.cap.release()


def find_scenes(path, threshold, video):
    found = detect(str(path), ContentDetector(threshold=threshold))
    if not found:  # 장면 전환이 없으면 영상 전체가 한 장면
        return [(0, video.frame_count)]
    return [(start.frame_num, end.frame_num) for start, end in found]


def mmss(seconds):
    m, s = divmod(seconds, 60)
    return f"{int(m):02d}:{s:04.1f}"


def make_contact_sheet(scenes, path):
    """대표 사진을 장면 순서대로 한 장에 모은다 (한 줄에 장면 2개 = 사진 4장)."""
    thumbs = []
    for scene in scenes:
        for photo in scene["photos"]:
            img = winsafe.imread(FRAMES_DIR / photo)
            img = cv2.resize(img, (240, round(img.shape[0] * 240 / img.shape[1])))
            label = f"#{scene['idx']} {mmss(scene['start'])}"
            if scene["excluded"]:
                label += " X"
            cv2.rectangle(img, (0, 0), (240, 26), (0, 0, 0), -1)
            cv2.putText(img, label, (6, 19), cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                        (80, 80, 255) if scene["excluded"] else (255, 255, 255), 1, cv2.LINE_AA)
            thumbs.append(img)
    height = max(t.shape[0] for t in thumbs)
    thumbs = [cv2.copyMakeBorder(t, 0, height - t.shape[0], 0, 0, cv2.BORDER_CONSTANT) for t in thumbs]
    per_row = 4
    blank = thumbs[0] * 0
    rows = []
    for i in range(0, len(thumbs), per_row):
        row = thumbs[i:i + per_row]
        row += [blank] * (per_row - len(row))
        rows.append(cv2.hconcat(row))
    winsafe.imwrite(path, cv2.vconcat(rows), [cv2.IMWRITE_JPEG_QUALITY, 85])


def analyze_video(video_path, video, analyzer, threshold):
    """장면을 나누고, 장면마다 대표 사진 2장과 특징을 계산한다."""
    print("장면 나누는 중… (영상 길이에 따라 시간이 걸려요)")
    ranges = find_scenes(video_path, threshold, video)
    print(f"장면 {len(ranges)}개 발견. 장면마다 사진 뽑고 특징 계산 중…")

    scenes = []
    for idx, (first, last) in enumerate(ranges, start=1):
        length = max(1, last - first)
        photos = []
        for tag, pos in (("a", 1 / 3), ("b", 2 / 3)):
            frame = video.frame_at(first + int(length * pos))
            if frame is None:
                raise StepError(f"{idx}번 장면의 사진을 읽지 못했습니다.")
            name = f"scene_{idx:03d}_{tag}.jpg"
            winsafe.imwrite(FRAMES_DIR / name, frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
            photos.append(name)

        samples, motion_pairs = [], []
        for k in range(SAMPLE_COUNT):
            pos = first + int(length * (k + 0.5) / SAMPLE_COUNT)
            a = video.frame_at(pos)
            b = video.frame_at(min(pos + 1, last - 1))
            if a is None:
                continue
            samples.append(a)
            if b is not None and pos + 1 < last:
                motion_pairs.append((a, b))

        start, end = first / video.fps, last / video.fps
        info = {"idx": idx, "start": round(start, 2), "end": round(end, 2),
                "duration": round(end - start, 2), "photos": photos}
        result = analyzer.analyze({**info, "samples": samples, "motion_pairs": motion_pairs})
        scenes.append({
            "idx": idx,
            "start": info["start"],
            "end": info["end"],
            "duration": info["duration"],
            "shot_type": result["shot_type"],
            "description": result["description"],
            "features": result["features"],
            "excluded": result["excluded"],
            "exclude_reason": result["exclude_reason"],
            "photos": photos,
        })
    return scenes


def main():
    parser = argparse.ArgumentParser(description="영상 → 장면 나누기 + 대표 사진 + scenes.json")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--threshold", type=float, default=27.0,
                        help="장면 전환 민감도. 낮을수록 장면을 더 잘게 나눔 (기본 27)")
    parser.add_argument("--analyzer", choices=sorted(ANALYZERS), default="numeric",
                        help="장면을 읽는 방식 (지금은 numeric 만 있음)")
    parser.add_argument("--no-open", action="store_true", help="끝난 뒤 폴더를 열지 않음")
    args = parser.parse_args()

    src = args.input if args.input.is_absolute() else PROJECT_ROOT / args.input
    if not src.is_file():
        print(f"원본 영상이 없습니다: {src}")
        print(f"input 폴더에 영상을 '{DEFAULT_INPUT.name}' 이름으로 넣은 뒤 다시 실행하세요.")
        if not args.no_open:
            open_folder(src.parent)
        return 1

    FRAMES_DIR.mkdir(exist_ok=True)
    SCENES_JSON.parent.mkdir(exist_ok=True)
    for old in list(FRAMES_DIR.glob("scene_*.jpg")) + [FRAMES_DIR / "한눈에보기.jpg"]:
        winsafe.unlink(old)  # 이전 실행의 사진이 섞이지 않게

    analyzer = ANALYZERS[args.analyzer]()
    # 윈도우의 OpenCV 는 한글 파일 이름(원본.mp4)을 못 열어서 영어 이름의 연결 파일로 연다
    with winsafe.ascii_path(src, FRAMES_DIR) as video_path:
        video = Video(video_path)
        try:
            scenes = analyze_video(video_path, video, analyzer, args.threshold)
        finally:
            video.close()

    data = {
        "source": src.name,
        "created": datetime.now().isoformat(timespec="seconds"),
        "analyzer": analyzer.name,
        "fps": round(video.fps, 3),
        "scene_count": len(scenes),
        "scenes": scenes,
    }
    SCENES_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    make_contact_sheet(scenes, FRAMES_DIR / "한눈에보기.jpg")

    excluded = [s for s in scenes if s["excluded"]]
    print()
    print(f"완성! 장면 {len(scenes)}개 (제외 표시 {len(excluded)}개)")
    print(f"  첫 장면:   {mmss(scenes[0]['start'])} ~ {mmss(scenes[0]['end'])}")
    print(f"  마지막 장면: {mmss(scenes[-1]['start'])} ~ {mmss(scenes[-1]['end'])}")
    for s in excluded:
        print(f"  제외: {s['idx']}번 ({mmss(s['start'])}) - {s['exclude_reason']}")
    print(f"  사진: {FRAMES_DIR} (장면당 2장, 전체 모음: 한눈에보기.jpg)")
    print(f"  정보: {SCENES_JSON}")
    if not args.no_open and not open_folder(FRAMES_DIR):
        print(f"(이 컴퓨터는 화면이 없어서 폴더를 열지 못했어요. 위치: {FRAMES_DIR})")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except StepError as e:
        print(f"\n오류: {e}")
        sys.exit(1)
