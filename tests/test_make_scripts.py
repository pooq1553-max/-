"""make_scripts.py 테스트: 세 형식이 따로 나오고, 검증 안 된 이름·숫자가 들어가지 않는지.

실행: python -m unittest discover -s tests -v
"""
import copy
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import make_scripts as ms  # noqa: E402

FIX = ROOT / "tests" / "fixtures"
TEMPLATES = json.loads((ROOT / "config" / "templates.json").read_text(encoding="utf-8"))
FACTS = json.loads((FIX / "facts_food.json").read_text(encoding="utf-8"))
SCENES = [s for s in json.loads((FIX / "scenes_6.json").read_text(encoding="utf-8"))["scenes"]
          if not s["excluded"]]


def build(facts=FACTS, templates=TEMPLATES, scenes=SCENES):
    values, unverified, skipped = ms.verified_values(facts)
    return {fmt: ms.make_document(fmt, templates[fmt], values, unverified, skipped, scenes, {})
            for fmt in ms.FORMATS}


def all_text(doc):
    return " ".join([doc["title"]] + [c["subtitle"] + " " + c.get("narration", "") for c in doc["cues"]])


class JosaTest(unittest.TestCase):
    def test_josa(self):
        self.assertEqual(ms.attach_josa("바다국밥", "이"), "바다국밥이")
        self.assertEqual(ms.attach_josa("돼지국밥", "이에요"), "돼지국밥이에요")
        self.assertEqual(ms.attach_josa("피자", "이에요"), "피자예요")
        self.assertEqual(ms.attach_josa("서울", "으로"), "서울로")
        self.assertEqual(ms.attach_josa("9,000", "은"), "9,000은")   # 영 → 받침 있음
        self.assertEqual(ms.attach_josa("5", "은"), "5는")           # 오 → 받침 없음


class FormatTest(unittest.TestCase):
    def test_three_formats_are_labeled_and_different(self):
        docs = build()
        self.assertEqual([d["format"] for d in docs.values()], ["A", "B", "C"])
        self.assertEqual(len({d["format_label"] for d in docs.values()}), 3)
        self.assertNotEqual(docs["A"]["cues"][0]["subtitle"], docs["B"]["cues"][0]["subtitle"])
        self.assertNotIn("narration", docs["A"]["cues"][0])
        self.assertTrue(all("narration" in c for c in docs["C"]["cues"]))

    def test_excluded_scene_is_never_used(self):
        for doc in build().values():
            self.assertNotIn(3, [c["scene_idx"] for c in doc["cues"]])

    def test_hook_first_scene_outro_last_scene(self):
        for doc in build().values():
            self.assertEqual(doc["cues"][0]["role"], "hook")
            self.assertEqual(doc["cues"][0]["scene_idx"], SCENES[0]["idx"])
            self.assertEqual(doc["cues"][-1]["role"], "outro")
            self.assertEqual(doc["cues"][-1]["scene_idx"], SCENES[-1]["idx"])

    def test_too_few_scenes_drops_body_lines(self):
        docs = build(scenes=SCENES[:3])
        self.assertEqual(len(docs["A"]["cues"]), 3)
        self.assertTrue(docs["A"]["dropped_lines"])


class NoInventionTest(unittest.TestCase):
    def test_unverified_value_never_appears(self):
        for doc in build().values():
            self.assertNotIn("051-123-4567", all_text(doc))
            self.assertIn("전화번호", doc["skipped_fields"])

    def test_without_verified_price_no_number_appears(self):
        facts = copy.deepcopy(FACTS)
        facts["facts"]["가격"] = {"value": None, "evidence": None, "status": "확인 필요",
                                 "reason": "근거 없음", "rejected_value": "9,000원"}
        for doc in build(facts=facts).values():
            self.assertNotRegex(all_text(doc), r"\d")

    def test_nothing_verified_still_uses_only_fixed_phrases(self):
        facts = {"facts": {k: {"value": None, "status": "확인 필요", "reason": "x"} for k in FACTS["facts"]}}
        for doc in build(facts=facts).values():
            text = all_text(doc)
            for value in ("바다국밥", "돼지국밥", "부산", "9,000원"):
                self.assertNotIn(value, text)

    def test_template_with_hardcoded_number_is_refused(self):
        bad = copy.deepcopy(TEMPLATES)
        bad["A"]["hook"].insert(0, "단돈 5,000원 맛집")
        self.assertTrue(ms.check_templates(bad))
        self.assertEqual(ms.check_templates(TEMPLATES), [])

    def test_invented_number_in_output_is_caught(self):
        values, unverified, _ = ms.verified_values(FACTS)
        doc = build()["A"]
        doc["cues"][1]["subtitle"] = "돼지국밥 10,000원"
        self.assertTrue(ms.check_document(doc, values, unverified))


class SaveTest(unittest.TestCase):
    def test_failure_writes_nothing(self):
        """C형이 실패하면 A, B 도 저장하지 않는다."""
        bad = copy.deepcopy(TEMPLATES)
        bad["C"]["outro"] = [{"subtitle": "{없는항목}", "narration": "{없는항목}"}]
        with tempfile.TemporaryDirectory() as tmp:
            tpl = Path(tmp) / "t.json"
            tpl.write_text(json.dumps(bad, ensure_ascii=False), encoding="utf-8")
            argv = ["make_scripts.py", "--facts", str(FIX / "facts_food.json"),
                    "--scenes", str(FIX / "scenes_6.json"), "--templates", str(tpl), "--output-dir", tmp]
            with mock.patch.object(sys, "argv", argv), redirect_stdout(io.StringIO()):
                with self.assertRaises(ms.ScriptError):
                    ms.main()
            self.assertEqual(list(Path(tmp).glob("script_*")), [])

    def test_success_writes_six_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            argv = ["make_scripts.py", "--facts", str(FIX / "facts_food.json"),
                    "--scenes", str(FIX / "scenes_6.json"), "--output-dir", tmp]
            with mock.patch.object(sys, "argv", argv), redirect_stdout(io.StringIO()):
                ms.main()
            names = sorted(p.name for p in Path(tmp).glob("script_*"))
            self.assertEqual(names, [f"script_{f}.{e}" for f in "ABC" for e in ("json", "txt")])
            data = json.loads((Path(tmp) / "script_B.json").read_text(encoding="utf-8"))
            self.assertEqual(data["format"], "B")


if __name__ == "__main__":
    unittest.main()
