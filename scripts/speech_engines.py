"""음성 만들기(TTS)와 받아쓰기(STT) 엔진. 둘은 서로 모르는 독립 부품이다.

새 엔진을 붙이려면 TTSEngine 또는 STTEngine 을 상속해 한 함수만 채우고
TTS_ENGINES / STT_ENGINES 에 이름을 등록한 뒤 config/voice.json 에서 이름을 바꾸면 된다.
"""
import subprocess
import wave
from pathlib import Path

import numpy as np

from config import CODE_ROOT, PROJECT_ROOT

# 모델은 데이터 폴더에 없으면 코드 폴더의 models/ 를 쓴다 (테스트용 임시 폴더에서도 동작)
MODELS_DIR = PROJECT_ROOT / "models" if (PROJECT_ROOT / "models").is_dir() else CODE_ROOT / "models"


class EngineError(Exception):
    pass


def write_wav(path, samples, sample_rate):
    pcm = (np.clip(np.asarray(samples, dtype=np.float32), -1, 1) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(sample_rate))
        w.writeframes(pcm.tobytes())


def read_pcm16k(path):
    """어떤 음성 파일이든 16kHz 모노 float 배열로 (ffmpeg 사용)."""
    out = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ar", "16000", "-ac", "1",
                          "-f", "s16le", "-"], capture_output=True)
    if out.returncode != 0:
        raise EngineError(f"음성 파일을 읽지 못했습니다: {path.name}")
    return np.frombuffer(out.stdout, np.int16).astype(np.float32) / 32768


def _need(path, how):
    if not path.exists():
        raise EngineError(f"모델 파일이 없습니다: {path}\n{how}")
    return path


# ---------------- TTS ----------------

class TTSEngine:
    name = "base"
    description = ""

    def synthesize(self, text, out_path):
        """text 를 읽어 out_path(.wav)에 저장한다."""
        raise NotImplementedError


class SherpaKssTTS(TTSEngine):
    """sherpa-onnx + vits-mimic3 ko_KO KSS (로컬, 약 80MB, 음질은 보통)."""

    name = "sherpa_kss"
    description = "sherpa-onnx VITS 한국어(KSS, 여성) - 로컬"
    MODEL = MODELS_DIR / "vits-mimic3-ko_KO-kss_low"
    HOW = ("python scripts/download_models.py 로 내려받으세요 "
           "(github.com/k2-fsa/sherpa-onnx releases: tts-models/vits-mimic3-ko_KO-kss_low).")

    def __init__(self, speed=1.0, tts_noise_scale=0.0, **_):
        import sherpa_onnx
        d = self.MODEL
        config = sherpa_onnx.OfflineTtsConfig(model=sherpa_onnx.OfflineTtsModelConfig(
            vits=sherpa_onnx.OfflineTtsVitsModelConfig(
                model=str(_need(d / "ko_KO-kss_low.onnx", self.HOW)),
                tokens=str(_need(d / "tokens.txt", self.HOW)),
                data_dir=str(_need(d / "espeak-ng-data", self.HOW)),
                # 0 이면 같은 문장은 항상 같은 소리 (무작위성 없음). 시험해 보니 0 일 때 오인식이 가장 적었다.
                noise_scale=float(tts_noise_scale), noise_scale_w=float(tts_noise_scale)),
            num_threads=2))
        self.tts = sherpa_onnx.OfflineTts(config)
        self.speed = speed

    def synthesize(self, text, out_path):
        audio = self.tts.generate(text, sid=0, speed=self.speed)
        if len(audio.samples) == 0:
            raise EngineError(f"음성이 비어 있습니다: \"{text}\"")
        write_wav(out_path, audio.samples, audio.sample_rate)


class SupertonicTTS(TTSEngine):
    """Supertonic-3 (Supertone). 본인 PC 용. 첫 실행 때 Hugging Face 에서 모델 약 400MB 를 받는다.
    설치: pip install supertonic   (이 클라우드 환경에서는 Hugging Face 가 막혀 있어 실행 확인 못 함)"""

    name = "supertonic"
    description = "Supertonic-3 (로컬, 고음질, 첫 실행 시 모델 다운로드)"

    def __init__(self, speed=1.0, supertonic_voice="F1", supertonic_steps=8, **_):
        try:
            from supertonic import TTS
        except ImportError:
            raise EngineError("supertonic 패키지가 없습니다: pip install supertonic")
        try:
            self.tts = TTS(auto_download=True)
        except Exception as e:  # 다운로드 실패 등
            raise EngineError(f"Supertonic 모델을 불러오지 못했습니다: {e}")
        self.style = self.tts.get_voice_style(voice_name=supertonic_voice)
        self.speed, self.steps = speed, supertonic_steps

    def synthesize(self, text, out_path):
        wav, _ = self.tts.synthesize(text=text, voice_style=self.style, lang="ko",
                                     speed=self.speed, total_steps=self.steps)
        self.tts.save_audio(wav, str(out_path))


# ---------------- STT ----------------

class STTEngine:
    name = "base"
    description = ""

    def transcribe(self, wav_path):
        """음성 파일을 받아 적은 문장을 돌려준다."""
        raise NotImplementedError


class SherpaZipformerKoSTT(STTEngine):
    """sherpa-onnx zipformer 한국어 (로컬, int8, 약 75MB)."""

    name = "sherpa_zipformer_ko"
    description = "sherpa-onnx Zipformer 한국어 받아쓰기 - 로컬"
    MODEL = MODELS_DIR / "sherpa-onnx-zipformer-korean-2024-06-24"
    HOW = ("python scripts/download_models.py 로 내려받으세요 "
           "(github.com/k2-fsa/sherpa-onnx releases: asr-models/sherpa-onnx-zipformer-korean-2024-06-24).")

    def __init__(self, **_):
        import sherpa_onnx
        d = self.MODEL
        self.rec = sherpa_onnx.OfflineRecognizer.from_transducer(
            encoder=str(_need(d / "encoder-epoch-99-avg-1.int8.onnx", self.HOW)),
            decoder=str(_need(d / "decoder-epoch-99-avg-1.int8.onnx", self.HOW)),
            joiner=str(_need(d / "joiner-epoch-99-avg-1.int8.onnx", self.HOW)),
            tokens=str(_need(d / "tokens.txt", self.HOW)), num_threads=2)

    def transcribe(self, wav_path):
        stream = self.rec.create_stream()
        stream.accept_waveform(16000, read_pcm16k(Path(wav_path)))
        self.rec.decode_stream(stream)
        return stream.result.text.strip()


TTS_ENGINES = {e.name: e for e in (SherpaKssTTS, SupertonicTTS)}
STT_ENGINES = {e.name: e for e in (SherpaZipformerKoSTT,)}


def make_tts(name, **options):
    if name not in TTS_ENGINES:
        raise EngineError(f"모르는 TTS 엔진: {name} (가능: {', '.join(TTS_ENGINES)})")
    return TTS_ENGINES[name](**options)


def make_stt(name, **options):
    if name not in STT_ENGINES:
        raise EngineError(f"모르는 STT 엔진: {name} (가능: {', '.join(STT_ENGINES)})")
    return STT_ENGINES[name](**options)
