"""extract_facts.py 테스트. 실제 Gemini 를 부르지 않고 가짜 응답으로 검사한다.

실행: python -m unittest discover -s tests -v
"""
import io
import json
import sys
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import extract_facts as ef  # noqa: E402

DESCRIPTION = (ROOT / "tests" / "fixtures" / "description_food.txt").read_text(encoding="utf-8")
FIELDS = ["가게명", "메뉴명", "가격", "지역", "특징"]
FAKE_KEY = "AIzaFAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKE123"


def item(field, value, evidence):
    return {"field": field, "value": value, "evidence": evidence}


GOOD_ANSWER = {"items": [
    item("가게명", "바다국밥", "부산 해운대구 중동에 있는 '바다국밥'에 다녀왔습니다."),
    item("메뉴명", "돼지국밥", "대표 메뉴는 돼지국밥이고"),
    item("가격", "9,000원", "가격은 9,000원이에요."),
    item("지역", "부산 해운대구 중동", "부산 해운대구 중동에 있는"),
    item("특징", "부추를 무한으로 리필", "부추를 무한으로 리필해 줘서 좋았어요."),
]}


class VerifyTest(unittest.TestCase):
    def test_real_evidence_is_accepted(self):
        facts = ef.verify_all(FIELDS, GOOD_ANSWER, DESCRIPTION)
        for field in FIELDS:
            self.assertEqual(facts[field]["status"], ef.STATUS_OK, field)
        self.assertEqual(facts["가격"]["value"], "9,000원")

    def test_evidence_not_in_description_is_rejected(self):
        """근거 없는 값 거부: 설명글에 없는 문장을 근거로 대면 값을 비우고 확인 필요."""
        answer = {"items": [item("가격", "8,000원", "가격은 8,000원이에요.")]}
        fact = ef.verify_all(["가격"], answer, DESCRIPTION)["가격"]
        self.assertEqual(fact["status"], ef.STATUS_REVIEW)
        self.assertIsNone(fact["value"])
        self.assertIn("설명글에 그대로 있지 않음", fact["reason"])

    def test_invented_value_with_real_evidence_is_rejected(self):
        """근거 문장은 진짜인데 값을 지어낸 경우(전화번호)도 거부."""
        answer = {"items": [item("가게명", "바다국밥 본점 051-123-4567", "'바다국밥'에 다녀왔습니다.")]}
        fact = ef.verify_all(["가게명"], answer, DESCRIPTION)["가게명"]
        self.assertEqual(fact["status"], ef.STATUS_REVIEW)
        self.assertIsNone(fact["value"])

    def test_value_without_evidence_is_rejected(self):
        answer = {"items": [item("지역", "부산", "")]}
        fact = ef.verify_all(["지역"], answer, DESCRIPTION)["지역"]
        self.assertEqual(fact["status"], ef.STATUS_REVIEW)
        self.assertIsNone(fact["value"])
        self.assertEqual(fact["rejected_value"], "부산")

    def test_not_found_and_missing_fields_need_review(self):
        answer = {"items": [item("영업시간", "", "")]}
        facts = ef.verify_all(["영업시간", "주차"], answer, DESCRIPTION)
        self.assertEqual(facts["영업시간"]["reason"], "설명글에서 찾지 못함")
        self.assertEqual(facts["주차"]["reason"], "AI 가 이 항목에 답하지 않음")
        for fact in facts.values():
            self.assertIsNone(fact["value"])

    def test_line_break_and_spacing_differences_still_match(self):
        answer = {"items": [item("특징", "24시간 영업", "24시간   영업하고,\n부추를")]}
        fact = ef.verify_all(["특징"], answer, DESCRIPTION)["특징"]
        self.assertEqual(fact["status"], ef.STATUS_OK)


class SafetyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.desc = self.dir / "description.txt"
        self.desc.write_text(DESCRIPTION, encoding="utf-8")
        self.fields = self.dir / "fields.txt"
        self.fields.write_text("\n".join(FIELDS), encoding="utf-8")
        self.out = self.dir / "facts.json"
        self.old = '{"기존": "내용"}'
        self.out.write_text(self.old, encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def run_main(self):
        argv = ["extract_facts.py", "--description", str(self.desc),
                "--fields", str(self.fields), "--output", str(self.out)]
        buf = io.StringIO()
        with mock.patch.object(sys, "argv", argv), \
                mock.patch.object(ef, "get_gemini_api_key", return_value=FAKE_KEY), \
                mock.patch.object(ef, "get_env_value", return_value=""), redirect_stdout(buf):
            ef.main()
        return buf.getvalue()

    def test_success_writes_structured_json(self):
        with mock.patch.object(ef, "call_gemini", return_value=GOOD_ANSWER):
            printed = self.run_main()
        data = json.loads(self.out.read_text(encoding="utf-8"))
        self.assertEqual(data["fields"], FIELDS)
        for fact in data["facts"].values():
            self.assertEqual(set(fact) >= {"value", "evidence", "status"}, True)
        self.assertNotIn(FAKE_KEY, printed)

    def test_api_failure_keeps_existing_file(self):
        error = ef.ExtractError(f"Gemini 호출 실패 key={FAKE_KEY}")
        with mock.patch.object(ef, "call_gemini", side_effect=error):
            with self.assertRaises(ef.ExtractError) as ctx:
                self.run_main()
        self.assertEqual(self.out.read_text(encoding="utf-8"), self.old)
        self.assertNotIn(FAKE_KEY, str(ctx.exception))

    def test_failed_write_keeps_existing_file_and_no_temp_left(self):
        with self.assertRaises(TypeError):
            ef.save_json_atomic({"bad": object()}, self.out)
        self.assertEqual(self.out.read_text(encoding="utf-8"), self.old)
        self.assertEqual([p.name for p in self.dir.glob("*.tmp")], [])

    def test_http_error_message_has_no_key_and_key_not_in_url(self):
        seen = {}

        def fake_urlopen(request, timeout):
            seen["url"] = request.full_url
            raise urllib.error.HTTPError(request.full_url, 429, "Too Many", {}, io.BytesIO(b"{}"))

        with mock.patch.object(ef.urllib.request, "urlopen", fake_urlopen):
            with self.assertRaises(ef.ExtractError) as ctx:
                ef.call_gemini("prompt", FAKE_KEY, "gemini-test")
        self.assertIn("429", str(ctx.exception))
        self.assertNotIn(FAKE_KEY, str(ctx.exception))
        self.assertNotIn(FAKE_KEY, seen["url"])

    def test_broken_ai_response_is_an_error_not_a_guess(self):
        payload = io.BytesIO(json.dumps({"candidates": [{"content": {"parts": [{"text": "그냥 글"}]}}]}).encode())
        with mock.patch.object(ef.urllib.request, "urlopen", return_value=mock.MagicMock(
                __enter__=lambda s: payload, __exit__=lambda *a: False)):
            with self.assertRaises(ef.ExtractError):
                ef.call_gemini("prompt", FAKE_KEY, "gemini-test")


if __name__ == "__main__":
    unittest.main()
