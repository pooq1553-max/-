"""음성(TTS)·받아쓰기(STT) 테스트."""
import tempfile
import unittest
from pathlib import Path

from helpers import MODELS_READY, make_tone

import speech_engines as se
import voice


class NumberAndCompareTest(unittest.TestCase):
    def test_number_to_korean(self):
        cases = {0: "영", 7: "칠", 10: "십", 15: "십오", 9000: "구천", 10000: "만", 12345: "만이천삼백사십오",
                 110000: "십일만", 1000000: "백만", 100000000: "일억"}
        for n, expected in cases.items():
            self.assertEqual(voice.number_to_korean(n), expected, n)

    def test_normalize_reads_numbers_and_drops_spaces(self):
        self.assertEqual(voice.normalize_speech("가격은 9,000원이에요."), "가격은구천원이에요")

    def test_same_sentence_does_not_need_review(self):
        r = voice.compare("가격은 9,000원이에요.", "가격은구천원이에요", important=["9,000원"])
        self.assertFalse(r["needs_review"])
        self.assertEqual(r["cer"], 0)

    def test_big_difference_needs_review(self):
        r = voice.compare("대표 메뉴는 돼지국밥이에요.", "대포 메뉴 뭐지", threshold=0.15)
        self.assertTrue(r["needs_review"])
        self.assertIn("글자 차이", r["review_reason"])

    def test_misheard_important_word_needs_review_even_if_small_cer(self):
        r = voice.compare("오늘은 부산 해운대구 중동에 있는 돼지국밥 맛집을 소개할게요.",
                          "오늘은부산태운되고중동에있는돼지국밥맛집을소개할게요",
                          important=["부산 해운대구 중동"], threshold=0.15)
        self.assertLess(r["cer"], 0.15)
        self.assertTrue(r["needs_review"])
        self.assertEqual(r["missing_words"], ["부산 해운대구 중동"])


class FakeTTS(se.TTSEngine):
    name = "fake"

    def __init__(self, fail_on=None):
        self.calls, self.fail_on = 0, fail_on

    def synthesize(self, text, out_path):
        self.calls += 1
        if self.calls == self.fail_on:
            raise RuntimeError("가짜 실패")
        make_tone(out_path, 1.0 + 0.1 * len(text) / 10)


class FakeSTT(se.STTEngine):
    name = "fake"

    def __init__(self, answers):
        self.answers = answers

    def transcribe(self, wav_path):
        return self.answers.pop(0)


SCRIPT = {"format": "C", "cues": [
    {"scene_idx": 1, "narration": "가게 이름은 바다국밥이에요.", "fields_used": ["가게명"]},
    {"scene_idx": 2, "narration": "가격은 9,000원이에요.", "fields_used": ["가격"]},
]}


class GenerateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name) / "audio" / "C"

    def tearDown(self):
        self.tmp.cleanup()

    def test_files_are_created_and_duration_checked(self):
        items = voice.generate(SCRIPT, self.out, FakeTTS())
        self.assertEqual([i["file"] for i in items], ["cue_01.wav", "cue_02.wav"])
        for i in items:
            self.assertTrue((self.out / i["file"]).is_file())
            self.assertGreater(i["duration"], 0.5)

    def test_failure_keeps_previous_audio_and_leaves_no_temp(self):
        voice.generate(SCRIPT, self.out, FakeTTS())
        before = (self.out / "cue_01.wav").read_bytes()
        with self.assertRaises(voice.VoiceError):
            voice.generate(SCRIPT, self.out, FakeTTS(fail_on=2))
        self.assertEqual((self.out / "cue_01.wav").read_bytes(), before)
        self.assertEqual([p.name for p in self.out.parent.iterdir()], ["C"])

    def test_broken_audio_file_is_rejected(self):
        bad = Path(self.tmp.name) / "bad.wav"
        bad.write_bytes(b"RIFF" + b"\0" * 2000)
        with self.assertRaises(voice.VoiceError):
            voice.check_audio_file(bad)

    def test_stt_is_independent_and_flags_differences(self):
        items = voice.generate(SCRIPT, self.out, FakeTTS())
        stt = FakeSTT(["가게이름은바다국밥이에요", "가격은팔천원이에요"])
        voice.check_with_stt(items, self.out, stt, {"가게명": "바다국밥", "가격": "9,000원"}, 0.15)
        self.assertFalse(items[0]["needs_review"])
        self.assertTrue(items[1]["needs_review"])
        self.assertIn("9,000원", items[1]["missing_words"])

    def test_unknown_engine_names_are_errors(self):
        with self.assertRaises(se.EngineError):
            se.make_tts("없는엔진")
        with self.assertRaises(se.EngineError):
            se.make_stt("없는엔진")

    def test_engine_registries_are_separate(self):
        self.assertTrue(set(se.TTS_ENGINES).isdisjoint(se.STT_ENGINES))
        self.assertIn("supertonic", se.TTS_ENGINES)


@unittest.skipUnless(MODELS_READY, "로컬 음성 모델 없음 (python scripts/download_models.py)")
class RealEngineTest(unittest.TestCase):
    def test_round_trip_with_local_models(self):
        with tempfile.TemporaryDirectory() as tmp:
            wav = Path(tmp) / "t.wav"
            se.make_tts("sherpa_kss").synthesize("가게 이름은 바다국밥이에요.", wav)
            duration = voice.check_audio_file(wav)
            heard = se.make_stt("sherpa_zipformer_ko").transcribe(wav)
        self.assertGreater(duration, 0.5)
        self.assertLess(voice.compare("가게 이름은 바다국밥이에요.", heard)["cer"], 0.2, heard)

    def test_same_text_gives_same_audio(self):
        """무작위성을 0으로 두어 같은 문장은 항상 같은 소리 → 검사 결과도 매번 같음."""
        tts = se.make_tts("sherpa_kss")
        with tempfile.TemporaryDirectory() as tmp:
            a, b = Path(tmp) / "a.wav", Path(tmp) / "b.wav"
            tts.synthesize("가격은 9,000원이에요.", a)
            tts.synthesize("가격은 9,000원이에요.", b)
            self.assertEqual(a.read_bytes(), b.read_bytes())


if __name__ == "__main__":
    unittest.main()
