"""백업·복원 테스트."""
import json
import tempfile
import unittest
from pathlib import Path

import helpers  # noqa: F401  (scripts/ 경로 추가)
import backup_tool as backup


class BackupTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.root, self.code = base / "data_root", base / "code_root"
        for p, text in {
            "data/facts.json": '{"facts": {"가격": {"value": "9,000원"}}}',
            "data/approvals.json": "{}",
            "data/jobs/j1.json": '{"id": "j1"}',
            "input/description.txt": "설명글 원본",
            "output/script_A.json": '{"format": "A"}',
            "audio/C/voice_report.json": "{}",
            ".env": "GEMINI_API_KEY=AIzaSECRET",
        }.items():
            (self.root / p).parent.mkdir(parents=True, exist_ok=True)
            (self.root / p).write_text(text, encoding="utf-8")
        (self.root / "input" / "원본.mp4").write_bytes(b"video")
        (self.root / "output" / "shorts_A.mp4").write_bytes(b"video")
        (self.root / "audio" / "C" / "cue_01.wav").write_bytes(b"wav")
        for p in ("scripts/a.py", "config/templates.json", ".env"):
            (self.code / p).parent.mkdir(parents=True, exist_ok=True)
            (self.code / p).write_text("print(1)" if p.endswith(".py") else "{}", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def files_in(self, dest):
        return set(json.loads((dest / "manifest.json").read_text(encoding="utf-8"))["files"])

    def test_backup_excludes_key_videos_and_audio(self):
        dest = backup.create(self.root, self.code)
        files = self.files_in(dest)
        self.assertIn("data/data/facts.json", files)
        self.assertIn("data/input/description.txt", files)
        self.assertIn("code/scripts/a.py", files)
        self.assertFalse(any(".env" in f for f in files))
        self.assertFalse(any(f.endswith((".mp4", ".wav")) for f in files))
        self.assertEqual(backup.verify(dest.name, self.root)[1], [])

    def test_restore_brings_back_data_and_saves_current_first(self):
        dest = backup.create(self.root, self.code)
        facts = self.root / "data" / "facts.json"
        facts.write_text('{"facts": "망가진 값"}', encoding="utf-8")
        (self.root / "input" / "description.txt").unlink()
        restored, safety = backup.restore(dest.name, self.root, self.code)
        self.assertEqual(facts.read_text(encoding="utf-8"), '{"facts": {"가격": {"value": "9,000원"}}}')
        self.assertEqual((self.root / "input" / "description.txt").read_text(encoding="utf-8"), "설명글 원본")
        self.assertIn("data/facts.json", restored)
        self.assertNotIn("scripts/a.py", restored)  # 코드는 --with-code 일 때만
        saved = (safety / "data" / "data" / "facts.json").read_text(encoding="utf-8")
        self.assertEqual(saved, '{"facts": "망가진 값"}')
        self.assertEqual((self.root / ".env").read_text(encoding="utf-8"), "GEMINI_API_KEY=AIzaSECRET")

    def test_restore_with_code(self):
        dest = backup.create(self.root, self.code)
        (self.code / "scripts" / "a.py").write_text("망가짐", encoding="utf-8")
        backup.restore(dest.name, self.root, self.code, with_code=True)
        self.assertEqual((self.code / "scripts" / "a.py").read_text(encoding="utf-8"), "print(1)")

    def test_damaged_backup_is_not_restored(self):
        dest = backup.create(self.root, self.code)
        (dest / "data" / "data" / "facts.json").write_text("손상", encoding="utf-8")
        _, problems = backup.verify(dest.name, self.root)
        self.assertTrue(problems)
        with self.assertRaises(backup.BackupError):
            backup.restore(dest.name, self.root, self.code)
        self.assertIn("9,000원", (self.root / "data" / "facts.json").read_text(encoding="utf-8"))

    def test_list_only_complete_backups(self):
        a = backup.create(self.root, self.code, label="one")
        (self.root / "backup" / ".half.tmp").mkdir()
        (self.root / "backup" / "code_20261013_234702").mkdir()  # 단계 0 방식의 예전 백업 (목록에서만 제외)
        self.assertEqual(backup.list_backups(self.root), [a.name])


if __name__ == "__main__":
    unittest.main()
