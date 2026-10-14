"""렌더링 테스트: 세 형식 규격 검사, 한 형식 실패 시 다른 결과 보존, 자막 안전 영역."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from helpers import FIX, make_root, make_tone, make_video, probe

import make_scripts as ms
import render


def build_project(tmp, audio=True):
    root = make_root(tmp)
    src = make_video(root / "input" / "원본.mp4", scenes=("testsrc2", "smptebars", "rgbtestsrc", "testsrc"),
                     seconds=3, audio=audio)
    scenes = [{"idx": i + 1, "start": i * 3.0, "end": (i + 1) * 3.0, "excluded": False} for i in range(4)]
    facts = json.loads((FIX / "facts_food.json").read_text(encoding="utf-8"))
    templates = json.loads((root / "config" / "templates.json").read_text(encoding="utf-8"))
    values, unverified, skipped = ms.verified_values(facts)
    for fmt in "ABC":
        doc = ms.make_document(fmt, templates[fmt], values, unverified, skipped, scenes, {})
        (root / "output" / f"script_{fmt}.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    c = json.loads((root / "output" / "script_C.json").read_text(encoding="utf-8"))
    (root / "audio" / "C").mkdir(parents=True)
    items = []
    for n, cue in enumerate(c["cues"], 1):
        make_tone(root / "audio" / "C" / f"cue_{n:02d}.wav", 2.0)
        items.append({"cue": n, "scene_idx": cue["scene_idx"], "text": cue["narration"],
                      "file": f"cue_{n:02d}.wav", "duration": 2.0, "needs_review": n == 1})
    (root / "audio" / "C" / "voice_report.json").write_text(json.dumps({"items": items}, ensure_ascii=False),
                                                           encoding="utf-8")
    return root, src


def patched(root):
    return mock.patch.multiple(render, OUTPUT_DIR=root / "output", REVIEW_DIR=root / "frames" / "review",
                               RENDER_CONFIG=root / "config" / "render.json",
                               TEMPLATES=root / "config" / "templates.json",
                               REPORT_FILE=root / "output" / "render_report.json",
                               VOICE_REPORT=root / "audio" / "C" / "voice_report.json")


class RenderAllTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root, cls.src = build_project(cls.tmp.name)
        with patched(cls.root):
            cls.report = render.render_all(["A", "B", "C"], cls.src)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_three_videos_pass_automatic_checks(self):
        for fmt in "ABC":
            entry = self.report["formats"][fmt]
            self.assertEqual(entry["status"], "ok", entry.get("error"))
            info = probe(self.root / "output" / f"shorts_{fmt}.mp4")
            self.assertEqual((info["width"], info["height"]), (1080, 1920))
            self.assertEqual(info["codec"], "h264")
            self.assertTrue(info["has_audio"])
            self.assertAlmostEqual(info["duration"], entry["expected_duration"], delta=0.35)
            self.assertTrue(all(entry["checks"].values()))

    def test_c_length_follows_narration(self):
        c = self.report["formats"]["C"]
        # 내레이션 2초 + 여백 0.5초, 최소 1.8초 → 장면당 2.5초
        cues = len(json.loads((self.root / "output" / "script_C.json").read_text(encoding="utf-8"))["cues"])
        self.assertAlmostEqual(c["expected_duration"], 2.5 * cues, delta=0.01)
        self.assertIn("받아쓰기 검토 필요 음성: cue_01.wav", c["warnings"])

    def test_review_frames_saved(self):
        for fmt in "ABC":
            folder = self.root / "frames" / "review" / fmt
            names = [p.name for p in folder.iterdir()]
            self.assertIn("한눈에보기.jpg", names)
            self.assertTrue(any("시작" in n for n in names) and any("중간" in n for n in names)
                            and any("끝" in n for n in names))
            cues = len(json.loads((self.root / "output" / f"script_{fmt}.json").read_text(encoding="utf-8"))["cues"])
            self.assertEqual(sum("자막" in n for n in names), cues)

    def test_no_temp_files_left(self):
        leftovers = [p.name for p in (self.root / "output").iterdir() if p.name.startswith(".")]
        self.assertEqual(leftovers, [])


class FailureIsolationTest(unittest.TestCase):
    def test_failed_format_keeps_other_results_and_old_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, src = build_project(tmp)
            old_c = root / "output" / "shorts_C.mp4"
            old_c.write_bytes(b"OLD VIDEO")
            (root / "audio" / "C" / "voice_report.json").unlink()  # C형만 실패하게
            with patched(root):
                report = render.render_all(["A", "B", "C"], src)
            self.assertEqual(report["formats"]["A"]["status"], "ok")
            self.assertEqual(report["formats"]["B"]["status"], "ok")
            self.assertEqual(report["formats"]["C"]["status"], "failed")
            self.assertIn("음성이 없습니다", report["formats"]["C"]["error"])
            self.assertTrue(report["formats"]["C"]["previous_file_kept"])
            self.assertEqual(old_c.read_bytes(), b"OLD VIDEO")
            saved = json.loads((root / "output" / "render_report.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["formats"]["C"]["status"], "failed")

    def test_source_without_audio_still_gets_audio_track(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, src = build_project(tmp, audio=False)
            (root / "output" / ".render_A_crashed").mkdir()  # 이전에 꺼져서 남은 임시 폴더
            (root / "output" / ".shorts_A.mp4.tmp").write_bytes(b"x")
            with patched(root):
                report = render.render_all(["A"], src)
            self.assertEqual(report["formats"]["A"]["status"], "ok", report["formats"]["A"].get("error"))
            self.assertTrue(probe(root / "output" / "shorts_A.mp4")["has_audio"])
            self.assertEqual([p.name for p in (root / "output").iterdir() if p.name.startswith(".")], [])


class SubtitleTest(unittest.TestCase):
    def setUp(self):
        self.cfg = json.loads((Path(render.RENDER_CONFIG)).read_text(encoding="utf-8"))
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_subtitles_stay_inside_safe_area(self):
        safe = self.cfg["safe_area"]
        for fmt in "ABC":
            for text, hook in (("짧은 자막", False), ("위치는 부산 해운대구 중동", True)):
                rect = render.draw_subtitle(text, self.cfg["styles"][fmt], hook, self.cfg,
                                            Path(self.tmp.name) / "s.png")
                self.assertGreaterEqual(rect[0], safe["left"])
                self.assertLessEqual(rect[2], 1080 - safe["right"])
                self.assertGreaterEqual(rect[1], safe["top"])
                self.assertLessEqual(rect[3], 1920 - safe["bottom"])

    def test_text_that_cannot_fit_is_refused(self):
        with self.assertRaises(render.RenderError):
            render.draw_subtitle("가" * 60, self.cfg["styles"]["A"], False, self.cfg, Path(self.tmp.name) / "s.png")

    def test_check_video_flags_missing_audio_and_wrong_size(self):
        info = {"width": 720, "height": 1280, "codec": "h264", "has_audio": False, "duration": 10.0}
        checks = render.check_video(info, 10.0, self.cfg)
        self.assertFalse(checks["resolution_1080x1920"])
        self.assertFalse(checks["has_audio_track"])
        self.assertTrue(checks["duration_matches_plan"])


if __name__ == "__main__":
    unittest.main()
