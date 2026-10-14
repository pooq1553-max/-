"""윈도우 안전장치 테스트: 사용 중인 파일 재시도, 한글 경로 우회."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
from helpers import make_root, make_video

import scenes
import winsafe


class RetryTest(unittest.TestCase):
    def test_replace_waits_until_file_is_free(self):
        with tempfile.TemporaryDirectory() as tmp:
            src, dst = Path(tmp) / "a.tmp", Path(tmp) / "b.mp4"
            src.write_text("new")
            dst.write_text("old")
            real = winsafe.os.replace
            calls = {"n": 0}

            def busy_twice(a, b):
                calls["n"] += 1
                if calls["n"] <= 2:
                    raise PermissionError(13, "사용 중", str(b))
                return real(a, b)

            with mock.patch.object(winsafe.os, "replace", busy_twice):
                winsafe.replace(src, dst, seconds=5)
            self.assertEqual(dst.read_text(), "new")
            self.assertEqual(calls["n"], 3)

    def test_gives_clear_message_if_still_busy(self):
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp) / "shorts_A.mp4"
            dst.write_text("old")
            with mock.patch.object(winsafe.os, "replace", side_effect=PermissionError(13, "x", str(dst))):
                with self.assertRaises(winsafe.FileBusyError) as ctx:
                    winsafe.replace(Path(tmp) / "a", dst, seconds=0.5)
            self.assertIn("재생 중인", str(ctx.exception))
            self.assertEqual(dst.read_text(), "old")


class KoreanPathTest(unittest.TestCase):
    def test_image_read_write_with_korean_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            img = np.full((20, 30, 3), 128, np.uint8)
            path = Path(tmp) / "한눈에보기.jpg"
            winsafe.imwrite(path, img)
            back = winsafe.imread(path)
            self.assertEqual(back.shape, (20, 30, 3))

    def test_ascii_alias_for_korean_video_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "원본.mp4"
            video.write_bytes(b"data")
            with winsafe.ascii_path(video, Path(tmp) / "work") as p:
                self.assertTrue(str(p).isascii())
                self.assertEqual(p.read_bytes(), b"data")
            self.assertFalse(p.exists())
            self.assertTrue(video.exists())
            plain = Path(tmp) / "plain.mp4"
            with winsafe.ascii_path(plain, Path(tmp) / "work") as p:
                self.assertEqual(p, plain)

    def test_scene_split_only_gives_ascii_paths_to_opencv(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(tmp)
            src = make_video(root / "input" / "원본.mp4", seconds=2)
            seen = []
            real_capture = scenes.cv2.VideoCapture
            real_detect = scenes.detect

            def capture(path, *a):
                seen.append(path)
                return real_capture(path, *a)

            def detect(path, *a, **k):
                seen.append(path)
                return real_detect(path, *a, **k)

            with mock.patch.multiple(scenes, FRAMES_DIR=root / "frames", SCENES_JSON=root / "output" / "scenes.json",
                                     detect=detect), \
                    mock.patch.object(scenes.cv2, "VideoCapture", capture), \
                    mock.patch("sys.argv", ["scenes.py", "--input", str(src), "--no-open"]):
                self.assertEqual(scenes.main(), 0)
            self.assertTrue(seen)
            self.assertTrue(all(str(p).isascii() for p in seen), seen)
            self.assertTrue((root / "frames" / "한눈에보기.jpg").is_file())
            self.assertEqual(list((root / "frames").glob(".source_video*")), [])


if __name__ == "__main__":
    unittest.main()
