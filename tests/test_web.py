"""웹 화면(API) 테스트. 진짜 프로젝트 폴더가 아니라 임시 폴더에서 돈다."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

from helpers import ROOT, make_root, make_video

sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

import jobs  # noqa: E402
import make_scripts as ms  # noqa: E402
from web.app import create_app  # noqa: E402


def slow_steps(_video=None):
    return [("scenes", "느린 단계", [sys.executable, "-c", "import time; time.sleep(1.5)"])]


class WebTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = make_root(self.tmp.name)
        self.manager = jobs.JobManager(self.root, slow_steps)
        self.client = TestClient(create_app(self.root, self.manager))
        self.video = make_video(Path(self.tmp.name) / "clip.mp4", scenes=("testsrc2",), seconds=1)

    def tearDown(self):
        job = self.manager.active()
        if job:
            self.manager.wait(job["id"], 20)
        self.tmp.cleanup()

    def upload(self, path, name="clip.mp4"):
        with open(path, "rb") as f:
            return self.client.post("/api/upload", files={"file": (name, f, "video/mp4")})

    def ready(self):
        self.assertEqual(self.upload(self.video).status_code, 200)
        self.assertEqual(self.client.post("/api/description", json={"text": "설명글"}).status_code, 200)

    def test_page_is_served(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("제작 시작", r.text)

    def test_upload_valid_video_is_saved_as_input(self):
        r = self.upload(self.video, "내 영상.MOV")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["name"], "원본.mov")
        self.assertTrue((self.root / "input" / "원본.mov").is_file())

    def test_upload_rejects_non_video(self):
        bad = Path(self.tmp.name) / "fake.mp4"
        bad.write_bytes(b"this is not a video")
        self.assertEqual(self.upload(bad).status_code, 400)
        self.assertEqual(self.upload(self.video, "notes.txt").status_code, 400)
        self.assertEqual(list((self.root / "input").glob("원본.*")), [])
        self.assertEqual(list((self.root / "input").glob(".upload*")), [])

    def test_description_is_saved_to_input_file(self):
        self.assertEqual(self.client.post("/api/description", json={"text": "  "}).status_code, 400)
        r = self.client.post("/api/description", json={"text": "부산 바다국밥 후기"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual((self.root / "input" / "description.txt").read_text(encoding="utf-8").strip(),
                         "부산 바다국밥 후기")

    def test_start_requires_video_and_description(self):
        self.assertEqual(self.client.post("/api/jobs", json={}).status_code, 400)
        self.upload(self.video)
        self.assertEqual(self.client.post("/api/jobs", json={}).status_code, 400)

    def test_double_click_start_returns_409_and_single_job(self):
        self.ready()
        first = self.client.post("/api/jobs", json={})
        second = self.client.post("/api/jobs", json={})
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 409)
        self.assertEqual(second.json()["detail"]["job"]["id"], first.json()["id"])
        self.assertEqual(len(self.manager.all_jobs()), 1)

    def test_inputs_locked_while_running(self):
        self.ready()
        self.client.post("/api/jobs", json={})
        self.assertEqual(self.upload(self.video).status_code, 409)
        self.assertEqual(self.client.post("/api/description", json={"text": "바꿈"}).status_code, 409)
        self.assertEqual(self.client.put("/api/facts", json={"values": {"가격": "1원"}}).status_code, 409)

    def test_upload_and_description_reach_pipeline(self):
        self.ready()
        job = self.client.post("/api/jobs", json={}).json()
        self.assertEqual(job["video"], "원본.mp4")
        steps = jobs.default_steps(job["video"])
        self.assertIn("input/원본.mp4", steps[0][2])  # 장면 나누기가 올린 영상을 씀
        self.assertTrue(any("extract_facts.py" in part for part in steps[1][2]))

    def test_facts_edit_marks_human_and_is_used_by_scripts(self):
        r = self.client.put("/api/facts", json={"values": {"가격": "9,000원", "가게명": ""}})
        self.assertEqual(r.status_code, 200)
        doc = json.loads((self.root / "data" / "facts.json").read_text(encoding="utf-8"))
        self.assertEqual(doc["facts"]["가격"]["status"], "사람이 확인함")
        values, _, skipped = ms.verified_values(doc)
        self.assertEqual(values, {"가격": "9,000원"})
        self.assertEqual(self.client.put("/api/facts", json={"values": {"없는항목": "x"}}).status_code, 400)

    def test_approval_needs_checks_and_follows_file(self):
        out = self.root / "output"
        (out / "shorts_C.mp4").write_bytes(self.video.read_bytes())
        (out / "render_report.json").write_text(json.dumps({"formats": {"C": {"status": "ok"}}}), encoding="utf-8")
        r = self.client.post("/api/approve", json={"format": "C", "checked_video": True, "checked_facts": True})
        self.assertEqual(r.status_code, 400)
        self.assertIn("음성을 직접 들어", r.json()["detail"])
        r = self.client.post("/api/approve", json={"format": "C", "checked_video": True, "checked_facts": True,
                                                   "checked_voice": True})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue((out / r.json()["approved"]["approved_copy"]).is_file())
        self.assertTrue((self.root / "backup" / r.json()["backup"] / "manifest.json").is_file())
        self.assertTrue(self.client.get("/api/state").json()["approvals"]["C"]["valid"])
        (out / "shorts_C.mp4").write_bytes(b"changed")  # 다시 렌더링되면 승인은 무효
        self.assertFalse(self.client.get("/api/state").json()["approvals"]["C"]["valid"])

    def test_cannot_approve_failed_render(self):
        (self.root / "output" / "render_report.json").write_text(
            json.dumps({"formats": {"A": {"status": "failed"}}}), encoding="utf-8")
        r = self.client.post("/api/approve", json={"format": "A", "checked_video": True, "checked_facts": True})
        self.assertEqual(r.status_code, 400)

    def test_state_lists_three_formats(self):
        s = self.client.get("/api/state").json()
        self.assertEqual(sorted(s["results"]), ["A", "B", "C"])
        self.assertEqual(s["fields"], ["가게명", "메뉴명", "가격", "지역", "특징"])


if __name__ == "__main__":
    unittest.main()
