"""전체 흐름 테스트: 영상+설명글 → 장면 → 정보(가짜 Gemini) → 대본 → 음성(로컬) → 영상 3개.
그리고 기존 단계(step1, scenes)가 그대로 동작하는지도 확인한다. 임시 폴더(SHORTS_ROOT)에서 실행.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from helpers import FIX, MODELS_READY, ROOT, make_root, make_video, probe

import jobs


def run_script(root, name, *args):
    env = {**os.environ, "SHORTS_ROOT": str(root)}
    return subprocess.run([sys.executable, str(ROOT / "scripts" / name), *args], cwd=root, env=env,
                          capture_output=True, text=True, timeout=300)


class ExistingStepsTest(unittest.TestCase):
    """이전 단계 기능이 수정 후에도 그대로 동작하는지."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = make_root(self.tmp.name)
        make_video(self.root / "input" / "원본.mp4", seconds=3)

    def tearDown(self):
        self.tmp.cleanup()

    def test_step1_makes_vertical_clip(self):
        r = run_script(self.root, "step1.py", "--no-open", "--text", "테스트")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        info = probe(self.root / "output" / "step1.mp4")
        self.assertEqual((info["width"], info["height"]), (1080, 1920))
        self.assertAlmostEqual(info["duration"], 9.0, delta=0.2)

    def test_scenes_split_and_json(self):
        r = run_script(self.root, "scenes.py", "--no-open")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        data = json.loads((self.root / "output" / "scenes.json").read_text(encoding="utf-8"))
        self.assertEqual(data["scene_count"], 3)
        self.assertEqual(len(list((self.root / "frames").glob("scene_*.jpg"))), 6)

    def test_extract_facts_without_key_fails_cleanly(self):
        shutil.copy(FIX / "description_food.txt", self.root / "input" / "description.txt")
        r = run_script(self.root, "extract_facts.py")
        self.assertEqual(r.returncode, 1)
        self.assertIn(".env", r.stdout)
        self.assertFalse((self.root / "data" / "facts.json").exists())


@unittest.skipUnless(MODELS_READY, "로컬 음성 모델 없음 (python scripts/download_models.py)")
class FullPipelineTest(unittest.TestCase):
    def test_upload_to_three_videos(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(tmp)
            make_video(root / "input" / "원본.mp4", scenes=("testsrc2", "smptebars", "rgbtestsrc", "testsrc"),
                       seconds=3)
            shutil.copy(FIX / "description_food.txt", root / "input" / "description.txt")
            m = jobs.JobManager(root, env={"SHORTS_FAKE_GEMINI": "1"})
            job, created = m.start(video_name="원본.mp4")
            self.assertTrue(created)
            job = m.wait(job["id"], 600)
            self.assertEqual(job["status"], "done", job.get("error") + "\n" + m.log_text(job["id"])[-3000:])
            facts = json.loads((root / "data" / "facts.json").read_text(encoding="utf-8"))
            self.assertEqual(facts["facts"]["가게명"]["value"], "바다국밥")
            report = json.loads((root / "output" / "render_report.json").read_text(encoding="utf-8"))
            for fmt in "ABC":
                self.assertEqual(report["formats"][fmt]["status"], "ok")
                info = probe(root / "output" / f"shorts_{fmt}.mp4")
                self.assertEqual((info["width"], info["height"]), (1080, 1920))
                self.assertTrue(info["has_audio"])
            voice = json.loads((root / "audio" / "C" / "voice_report.json").read_text(encoding="utf-8"))
            self.assertTrue(all("heard" in i and "needs_review" in i for i in voice["items"]))


if __name__ == "__main__":
    unittest.main()
