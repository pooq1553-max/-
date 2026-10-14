"""5단계: 대사(내레이션)를 음성으로 만들고, 받아쓰기(STT)로 다시 적어 대본과 비교한다.

사용법:
    python scripts/voice.py                 # 음성 만들기 + 받아쓰기 비교
    python scripts/voice.py --skip-stt      # 음성만 만들기
    python scripts/voice.py --check-only    # 이미 만든 음성을 받아쓰기로만 검사

입력: output/script_C.json (내레이션이 있는 형식), config/voice.json (엔진 선택)
결과: audio/C/cue_01.wav … , audio/C/voice_report.json

자동 비교는 '대본과 대략 같은 말을 했는지'만 본다. 발음·억양·자연스러움은 보장하지 못하므로
최종 음성은 반드시 직접 들어 보고 확인해야 한다.
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from extract_facts import FACTS_FILE, save_json_atomic
from make_scripts import verified_values
from speech_engines import EngineError, make_stt, make_tts
from step1 import PROJECT_ROOT

AUDIO_DIR = PROJECT_ROOT / "audio"
VOICE_CONFIG = PROJECT_ROOT / "config" / "voice.json"
SCRIPT_FILE = PROJECT_ROOT / "output" / "script_C.json"
LISTEN_NOTICE = "자동 비교는 발음 품질까지 보장하지 못합니다. 최종 음성은 반드시 직접 들어 보고 확인하세요."


class VoiceError(Exception):
    pass


# ---------- 비교용 글자 정리 ----------

DIGITS = "영일이삼사오육칠팔구"
SMALL_UNITS = ["", "십", "백", "천"]
BIG_UNITS = ["", "만", "억", "조"]


def number_to_korean(n):
    """12345 → 만이천삼백사십오 (한자어 읽기)."""
    if n == 0:
        return "영"
    out = ""
    for big_i in range(len(BIG_UNITS)):
        chunk = n % 10000
        n //= 10000
        if chunk:
            part = ""
            for i in range(4):
                d = chunk % 10
                chunk //= 10
                if d:
                    part = ("" if d == 1 and i > 0 else DIGITS[d]) + SMALL_UNITS[i] + part
            if big_i == 1 and part == "일":
                part = ""  # 만 (일만 X)
            out = part + BIG_UNITS[big_i] + out
        if n == 0:
            break
    return out


def normalize_speech(text):
    """비교용: 숫자를 한글 읽기로, 띄어쓰기·문장부호 제거."""
    text = re.sub(r"(?<=\d),(?=\d{3})", "", text or "")
    text = re.sub(r"\d+", lambda m: number_to_korean(int(m.group())), text)
    return re.sub(r"[^0-9A-Za-z가-힣]", "", text).lower()


def edit_distance(a, b):
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def compare(script_text, heard_text, important=(), threshold=0.15):
    """대본과 받아쓴 문장을 비교한다. 글자 차이 비율(CER)과 중요한 단어 누락을 본다."""
    ref, hyp = normalize_speech(script_text), normalize_speech(heard_text)
    cer = edit_distance(ref, hyp) / max(1, len(ref))
    missing = [w for w in important if normalize_speech(w) and normalize_speech(w) not in hyp]
    reasons = []
    if cer > threshold:
        reasons.append(f"글자 차이 {cer:.0%} (기준 {threshold:.0%} 초과)")
    if missing:
        reasons.append("중요 단어가 다르게 들림: " + ", ".join(missing))
    return {"cer": round(cer, 3), "missing_words": missing,
            "needs_review": bool(reasons), "review_reason": "; ".join(reasons)}


# ---------- 음성 파일 확인 ----------

def audio_duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nw=1:nk=1", str(path)], capture_output=True, text=True)
    try:
        return float(out.stdout.strip())
    except ValueError:
        return 0.0


def check_audio_file(path):
    if not path.is_file():
        raise VoiceError(f"음성 파일이 만들어지지 않았습니다: {path.name}")
    if path.stat().st_size < 1000:
        raise VoiceError(f"음성 파일이 너무 작습니다 (손상 의심): {path.name}")
    duration = audio_duration(path)
    if duration < 0.2:
        raise VoiceError(f"음성 길이가 비정상입니다 ({duration:.2f}초): {path.name}")
    return round(duration, 2)


# ---------- 단계 ----------

def load_config(path=VOICE_CONFIG):
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def generate(script, out_dir, tts):
    """모든 내레이션을 임시 폴더에 만든 뒤, 전부 성공했을 때만 out_dir 을 바꾼다."""
    cues = [c for c in script["cues"] if c.get("narration")]
    if not cues:
        raise VoiceError("내레이션이 있는 장면이 없습니다.")
    out_dir.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=out_dir.name + ".", dir=out_dir.parent))
    try:
        items = []
        for n, cue in enumerate(cues, 1):
            wav = tmp / f"cue_{n:02d}.wav"
            try:
                tts.synthesize(cue["narration"], wav)
            except EngineError:
                raise
            except Exception as e:
                raise VoiceError(f"{n}번 대사 음성 만들기 실패: {e}")
            items.append({"cue": n, "scene_idx": cue["scene_idx"], "text": cue["narration"],
                          "fields_used": cue.get("fields_used", []), "file": wav.name,
                          "duration": check_audio_file(wav)})
        if out_dir.exists():
            shutil.rmtree(out_dir)
        tmp.rename(out_dir)
        return items
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise


def check_with_stt(items, out_dir, stt, values, threshold):
    for item in items:
        heard = stt.transcribe(out_dir / item["file"])
        important = [values[f] for f in item.get("fields_used", []) if f in values]
        item["heard"] = heard
        item.update(compare(item["text"], heard, important, threshold))
    return items


def main():
    parser = argparse.ArgumentParser(description="내레이션 → 음성(TTS) → 받아쓰기(STT) 비교")
    parser.add_argument("--script", type=Path, default=SCRIPT_FILE)
    parser.add_argument("--facts", type=Path, default=FACTS_FILE)
    parser.add_argument("--out", type=Path, default=AUDIO_DIR / "C")
    parser.add_argument("--skip-stt", action="store_true")
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    resolve = lambda p: p if p.is_absolute() else PROJECT_ROOT / p
    out_dir, report_path = resolve(args.out), resolve(args.out) / "voice_report.json"
    config = load_config()
    options = {k: v for k, v in config.items() if not k.startswith("_")}

    if args.check_only:
        if not report_path.is_file():
            raise VoiceError("먼저 음성을 만들어야 합니다 (voice_report.json 없음).")
        report = json.loads(report_path.read_text(encoding="utf-8"))
        items = report["items"]
    else:
        script_path = resolve(args.script)
        if not script_path.is_file():
            raise VoiceError(f"대본이 없습니다: {script_path} (먼저 make_scripts.py 실행)")
        script = json.loads(script_path.read_text(encoding="utf-8"))
        tts_name = config.get("tts_engine", "sherpa_kss")
        print(f"음성 엔진: {tts_name}")
        tts = make_tts(tts_name, **options)
        items = generate(script, out_dir, tts)
        report = {"format": script.get("format", "C"), "tts_engine": tts_name, "items": items}
        for it in items:
            print(f"  {it['file']}  {it['duration']:.2f}초  \"{it['text']}\"")
        print(f"음성 {len(items)}개 저장, 합계 {sum(i['duration'] for i in items):.1f}초 → {out_dir}")

    if not args.skip_stt:
        stt_name = config.get("stt_engine", "sherpa_zipformer_ko")
        threshold = float(config.get("review_cer", 0.15))
        print(f"\n받아쓰기 엔진: {stt_name} (검토 기준: 글자 차이 {threshold:.0%})")
        stt = make_stt(stt_name, **options)
        facts_path = resolve(args.facts)
        values = verified_values(json.loads(facts_path.read_text(encoding="utf-8")))[0] \
            if facts_path.is_file() else {}
        check_with_stt(items, out_dir, stt, values, threshold)
        report["stt_engine"] = stt_name
        for it in items:
            mark = "검토 필요" if it["needs_review"] else "비슷함"
            print(f"  [{mark}] {it['file']}  차이 {it['cer']:.0%}")
            print(f"      대본: {it['text']}\n      들림: {it['heard']}")
            if it["needs_review"]:
                print(f"      이유: {it['review_reason']}")

    report["created"] = datetime.now().isoformat(timespec="seconds")
    report["needs_review_count"] = sum(1 for i in items if i.get("needs_review"))
    report["notice"] = LISTEN_NOTICE
    save_json_atomic(report, report_path)
    print(f"\n보고서: {report_path}")
    print(f"※ {LISTEN_NOTICE}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (VoiceError, EngineError) as e:
        print(f"\n오류: {e}")
        sys.exit(1)
