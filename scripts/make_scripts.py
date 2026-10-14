"""4단계: 장면 정보 + 검증된 정보 → A/B/C 세 가지 형식의 제목·자막·내레이션 대본.

사용법:
    python scripts/make_scripts.py
    python scripts/make_scripts.py --facts tests/fixtures/facts_food.json --scenes output/scenes.json

입력:
    output/scenes.json     장면 정보 (제외 표시된 장면은 쓰지 않음)
    data/facts.json        검증된 정보 ('설명글에 있음'인 값만 사용, '확인 필요'는 버림)
    config/templates.json  미리 정한 문장 틀
결과 (형식마다 따로):
    output/script_A.json / script_A.txt   A형 - 짧은 자막 중심
    output/script_B.json / script_B.txt   B형 - 다른 훅과 자막 구성
    output/script_C.json / script_C.txt   C형 - 내레이션 + 자막 해설

AI 를 쓰지 않는다. 문장은 틀의 고정 글자 + 검증된 값으로만 만들고,
마지막에 숫자가 검증된 값에서만 나왔는지, 확인 필요 값이 섞이지 않았는지 코드로 다시 검사한다.
"""
import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

from extract_facts import FACTS_FILE, STATUS_OK, save_json_atomic
from step1 import PROJECT_ROOT

SCENES_FILE = PROJECT_ROOT / "output" / "scenes.json"
TEMPLATES_FILE = PROJECT_ROOT / "config" / "templates.json"
OUTPUT_DIR = PROJECT_ROOT / "output"
FORMATS = ("A", "B", "C")
MAX_TITLE_CHARS = 40
NARRATION_CHARS_PER_SEC = 6.5  # 한국어 보통 말 빠르기 (대략)

SLOT = re.compile(r"\{([^{}|]+)(?:\|([^{}]+))?\}")

# 받침 있을 때 / 없을 때
JOSA = {
    "은": ("은", "는"), "는": ("은", "는"),
    "이": ("이", "가"), "가": ("이", "가"),
    "을": ("을", "를"), "를": ("을", "를"),
    "과": ("과", "와"), "와": ("과", "와"),
    "이에요": ("이에요", "예요"), "예요": ("이에요", "예요"),
    "이고": ("이고", "고"), "고": ("이고", "고"),
    "으로": ("으로", "로"), "로": ("으로", "로"),
}
DIGIT_HAS_BATCHIM = {"0": True, "1": True, "2": False, "3": True, "4": False,
                     "5": False, "6": True, "7": True, "8": True, "9": False}


class ScriptError(Exception):
    pass


# ---------- 문장 만들기 ----------

def attach_josa(word, josa):
    pair = JOSA.get(josa)
    if pair is None:
        raise ScriptError(f"모르는 조사 표시: |{josa}")
    last = word.rstrip()[-1:] if word.strip() else ""
    if "가" <= last <= "힣":
        final = (ord(last) - 0xAC00) % 28
        if pair[0] == "으로" and final == 8:  # ㄹ 받침 + 로
            return word + "로"
        return word + (pair[0] if final else pair[1])
    if last in DIGIT_HAS_BATCHIM:
        return word + (pair[0] if DIGIT_HAS_BATCHIM[last] else pair[1])
    return word + f"{pair[0]}({pair[1]})"  # 영어 등: 둘 다 적어 둠


def render(template, values):
    """틀을 채운다. 필요한 값이 하나라도 없으면 None. (문장, 사용한 항목들) 반환."""
    used = []

    def fill(match):
        field, josa = match.group(1).strip(), match.group(2)
        if field not in values:
            raise KeyError(field)
        used.append(field)
        return attach_josa(values[field], josa.strip()) if josa else values[field]

    try:
        text = SLOT.sub(fill, template)
    except KeyError:
        return None, []
    return re.sub(r"\s+", " ", text).strip(), used


def render_item(item, values, max_chars):
    """틀 하나(자막만 또는 자막+내레이션)를 채운다. 실패하면 None."""
    if isinstance(item, str):
        item = {"subtitle": item}
    subtitle, used = render(item["subtitle"], values)
    if subtitle is None or len(subtitle) > max_chars:
        return None
    cue = {"subtitle": subtitle, "fields_used": sorted(set(used)), "template": item["subtitle"]}
    if "narration" in item:
        narration, used_n = render(item["narration"], values)
        if narration is None:
            return None
        cue["narration"] = narration
        cue["fields_used"] = sorted(set(used) | set(used_n))
    return cue


def first_fit(candidates, values, max_chars):
    for item in candidates:
        cue = render_item(item, values, max_chars)
        if cue:
            return cue
    return None


def build_lines(spec, values):
    max_chars = spec.get("max_subtitle_chars", 16)
    hook = first_fit(spec["hook"], values, max_chars)
    outro = first_fit(spec["outro"], values, max_chars)
    if hook is None or outro is None:
        raise ScriptError("훅이나 마무리 틀을 하나도 채우지 못했습니다. 값이 필요 없는 틀을 하나 이상 넣어 주세요.")
    seen = set(hook["fields_used"])
    body = []
    for item in spec["body"]:
        cue = render_item(item, values, max_chars)
        # 이미 나온 정보만 반복하는 줄은 건너뜀
        if cue and set(cue["fields_used"]) - seen:
            body.append(cue)
            seen |= set(cue["fields_used"])
    return hook, body, outro


def assign_to_scenes(hook, body, outro, scenes):
    """훅은 첫 장면, 마무리는 마지막 장면, 본문은 그 사이에 하나씩. 장면이 모자라면 본문 뒤쪽부터 뺀다."""
    if len(scenes) < 2:
        raise ScriptError(f"쓸 수 있는 장면이 {len(scenes)}개라 훅과 마무리를 나눌 수 없습니다 (최소 2개).")
    middle = scenes[1:-1]
    dropped = body[len(middle):]
    pairs = [("hook", hook, scenes[0])] + \
        [("body", cue, scene) for cue, scene in zip(body, middle)] + [("outro", outro, scenes[-1])]
    cues = [{"scene_idx": s["idx"], "start": s["start"], "end": s["end"], "role": role, **cue}
            for role, cue, s in pairs]
    used_idx = {c["scene_idx"] for c in cues}
    unused = [s["idx"] for s in scenes if s["idx"] not in used_idx]
    return cues, dropped, unused


# ---------- 검사 ----------

def check_document(doc, values, unverified):
    """만든 글에 검증 안 된 숫자·값이 섞이지 않았는지 코드로 확인한다."""
    texts = [doc["title"]] + [c["subtitle"] for c in doc["cues"]] + \
        [c.get("narration", "") for c in doc["cues"]]
    problems = []
    for text in texts:
        rest = text
        for value in sorted(values.values(), key=len, reverse=True):
            rest = rest.replace(value, " ")
        if re.search(r"\d", rest):
            problems.append(f"검증되지 않은 숫자: \"{text}\"")
        for bad in unverified:
            if len(bad) >= 2 and bad in text:
                problems.append(f"확인 필요 값이 들어감: \"{bad}\"")
    return problems


def check_templates(templates):
    """틀의 고정 글자에 숫자가 있으면 안 된다 (숫자는 검증된 값으로만)."""
    problems = []
    for fmt in FORMATS:
        spec = templates[fmt]
        for part in ("title", "hook", "body", "outro"):
            for item in spec[part]:
                for text in ([item] if isinstance(item, str) else item.values()):
                    if re.search(r"\d", SLOT.sub("", text)):
                        problems.append(f"{fmt}형 {part} 틀에 숫자가 직접 적혀 있음: \"{text}\"")
    return problems


# ---------- 입출력 ----------

def load_json(path, what):
    if not path.is_file():
        raise ScriptError(f"{what} 파일이 없습니다: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        raise ScriptError(f"{what} 파일이 깨져 있습니다 (JSON 아님): {path}")


def verified_values(facts_doc):
    values, unverified, skipped = {}, [], {}
    for field, fact in facts_doc.get("facts", {}).items():
        if fact.get("status") == STATUS_OK and fact.get("value"):
            values[field] = str(fact["value"]).strip()
        else:
            skipped[field] = fact.get("reason") or "확인 필요"
            if fact.get("rejected_value"):
                unverified.append(str(fact["rejected_value"]))
    return values, unverified, skipped


def make_document(fmt, spec, values, unverified, skipped, scenes, sources):
    hook, body, outro = build_lines(spec, values)
    cues, dropped, unused = assign_to_scenes(hook, body, outro, scenes)
    title = first_fit(spec["title"], values, MAX_TITLE_CHARS)
    if title is None:
        raise ScriptError(f"{fmt}형 제목 틀을 하나도 채우지 못했습니다.")
    if spec.get("voice"):
        for cue in cues:
            sec = round(len(cue["narration"].replace(" ", "")) / NARRATION_CHARS_PER_SEC, 1)
            cue["narration_seconds_est"] = sec
            cue["narration_fits_scene"] = sec <= cue["end"] - cue["start"]
    doc = {
        "format": fmt,
        "format_label": spec["label"],
        "voice": "내레이션 있음" if spec.get("voice") else "내레이션 없음 (자막만)",
        "created": datetime.now().isoformat(timespec="seconds"),
        "method": "문장 틀 + 검증된 값 (AI 사용 안 함)",
        "sources": sources,
        "title": title["subtitle"],
        "cues": cues,
        "dropped_lines": [c["subtitle"] for c in dropped],
        "unused_scenes": unused,
        "skipped_fields": skipped,
        "notice": "검증된 값은 '설명글에 적혀 있음'만 뜻합니다. 올리기 전에 실제 정보가 맞는지 직접 확인하세요.",
    }
    problems = check_document(doc, values, unverified)
    if problems:
        raise ScriptError(f"{fmt}형 검사 실패:\n  " + "\n  ".join(problems))
    doc["checks"] = {"numbers_only_from_verified_facts": True, "no_unverified_values": True}
    return doc


def to_text(doc):
    lines = [f"[{doc['format_label']}]", f"음성: {doc['voice']}", f"제목: {doc['title']}", ""]
    for c in doc["cues"]:
        time = f"{c['start']:.1f}~{c['end']:.1f}초"
        lines.append(f"{time:<12} 장면 {c['scene_idx']:<3} {c['role']:<6} 자막: {c['subtitle']}")
        if "narration" in c:
            fit = "" if c["narration_fits_scene"] else "  ⚠ 장면보다 김"
            lines.append(f"{'':28}내레이션: {c['narration']} (약 {c['narration_seconds_est']}초){fit}")
    if doc["dropped_lines"]:
        lines.append(f"\n장면이 모자라 뺀 자막: {', '.join(doc['dropped_lines'])}")
    if doc["unused_scenes"]:
        lines.append(f"자막 없이 보여 줄 장면: {', '.join(map(str, doc['unused_scenes']))}")
    if doc["skipped_fields"]:
        lines.append("쓰지 않은 항목(확인 필요): " +
                     ", ".join(f"{k}({v})" for k, v in doc["skipped_fields"].items()))
    lines.append(f"\n※ {doc['notice']}")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description="장면 + 검증된 정보 → A/B/C 형식 대본")
    parser.add_argument("--scenes", type=Path, default=SCENES_FILE)
    parser.add_argument("--facts", type=Path, default=FACTS_FILE)
    parser.add_argument("--templates", type=Path, default=TEMPLATES_FILE)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args()
    resolve = lambda p: p if p.is_absolute() else PROJECT_ROOT / p

    templates = load_json(resolve(args.templates), "문장 틀")
    problems = check_templates(templates)
    if problems:
        raise ScriptError("문장 틀 검사 실패:\n  " + "\n  ".join(problems))
    scenes_doc = load_json(resolve(args.scenes), "장면 정보(scenes.json)")
    facts_doc = load_json(resolve(args.facts), "검증된 정보(facts.json)")

    scenes = [s for s in scenes_doc.get("scenes", []) if not s.get("excluded")]
    values, unverified, skipped = verified_values(facts_doc)
    print(f"쓸 수 있는 장면 {len(scenes)}개, 검증된 항목 {len(values)}개 ({', '.join(values) or '없음'})")
    if skipped:
        print(f"확인 필요라서 쓰지 않는 항목: {', '.join(skipped)}")
    sources = {"scenes": str(resolve(args.scenes)), "facts": str(resolve(args.facts))}

    # 셋 다 먼저 만들고 검사가 모두 통과하면 저장 (하나라도 실패하면 아무것도 안 바꿈)
    docs = {fmt: make_document(fmt, templates[fmt], values, unverified, skipped, scenes, sources)
            for fmt in FORMATS}
    out_dir = resolve(args.output_dir)
    for fmt, doc in docs.items():
        save_json_atomic(doc, out_dir / f"script_{fmt}.json")
        (out_dir / f"script_{fmt}.txt").write_text(to_text(doc), encoding="utf-8")
        print(f"\n저장: script_{fmt}.json / .txt  ({doc['format_label']})")
        print(f"  제목: {doc['title']}")
        for c in doc["cues"]:
            print(f"  장면 {c['scene_idx']}: {c['subtitle']}" + (f"  / {c['narration']}" if "narration" in c else ""))
    print("\n※ 검증된 값은 '설명글에 적혀 있음'만 뜻합니다. 올리기 전에 실제 정보가 맞는지 확인하세요.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ScriptError as e:
        print(f"\n오류: {e}")
        sys.exit(1)
