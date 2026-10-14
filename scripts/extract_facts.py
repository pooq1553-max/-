"""3단계: 영상 설명글에서 필요한 정보를 Gemini로 뽑고, 근거가 설명글에 정말 있는지 코드로 검사한다.

사용법:
    python scripts/extract_facts.py                          # input/description.txt + config/fields.txt
    python scripts/extract_facts.py --fields config/다른항목.txt

결과: data/facts.json
    항목마다 value(값), evidence(설명글에서 그대로 옮긴 근거), status, reason
    status 는 둘 중 하나:
      "설명글에 있음" — 근거 문장이 설명글에 그대로 있고, 값도 그 문장 안에 있음
      "확인 필요"     — 근거가 없거나 검사에 실패함. 이때 value 는 비워 둔다(null).

주의: "설명글에 있음"은 설명글에 그렇게 적혀 있다는 뜻일 뿐, 실제로 맞는 정보라는 뜻이 아니다.
"""
import argparse
import json
import os
import re
import sys
import tempfile
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

from config import MissingKeyError, PROJECT_ROOT, get_env_value, get_gemini_api_key

DESCRIPTION_FILE = PROJECT_ROOT / "input" / "description.txt"
FIELDS_FILE = PROJECT_ROOT / "config" / "fields.txt"
FACTS_FILE = PROJECT_ROOT / "data" / "facts.json"
DEFAULT_MODEL = "gemini-2.5-flash"
API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

STATUS_OK = "설명글에 있음"
STATUS_REVIEW = "확인 필요"
STATUS_HUMAN = "사람이 확인함"  # 웹 화면에서 사람이 직접 입력·수정한 값


class ExtractError(Exception):
    """사용자에게 보여 줄 오류. 메시지에 API 키를 넣지 않는다."""


# ---------- 입력 읽기 ----------

def read_fields(path):
    if not path.is_file():
        raise ExtractError(f"항목 목록 파일이 없습니다: {path}")
    fields = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        name = line.strip()
        if name and not name.startswith("#") and name not in fields:
            fields.append(name)
    if not fields:
        raise ExtractError(f"{path.name} 에 항목이 없습니다. 한 줄에 하나씩 적어 주세요 (예: 가게명).")
    return fields


def read_description(path):
    if not path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
        raise ExtractError(f"설명글 파일을 만들었습니다: {path}\n이 파일에 영상 설명글을 붙여 넣고 저장한 뒤 다시 실행하세요.")
    text = path.read_text(encoding="utf-8-sig").strip()
    if not text:
        raise ExtractError(f"설명글 파일이 비어 있습니다: {path}\n영상 설명글을 붙여 넣고 저장한 뒤 다시 실행하세요.")
    return text


# ---------- Gemini 호출 ----------

def build_prompt(description, fields):
    field_lines = "\n".join(f"- {f}" for f in fields)
    return (
        "아래 [설명글]에서 [항목]마다 정보를 찾아라.\n"
        "규칙:\n"
        "1. evidence 에는 설명글의 문장 일부를 한 글자도 바꾸지 말고 그대로 복사한다.\n"
        "2. value 는 evidence 안에 있는 글자를 그대로 쓴다. 요약·번역·추측·계산하지 않는다.\n"
        "3. 설명글에 없는 정보는 value 와 evidence 를 빈 문자열(\"\")로 둔다. 상식으로 채우지 않는다.\n"
        "4. 항목 이름은 [항목]에 적힌 그대로 쓴다.\n\n"
        f"[항목]\n{field_lines}\n\n[설명글]\n{description}"
    )


RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "items": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "field": {"type": "STRING"},
                    "value": {"type": "STRING"},
                    "evidence": {"type": "STRING"},
                },
                "required": ["field", "value", "evidence"],
            },
        }
    },
    "required": ["items"],
}


def call_gemini(prompt, api_key, model, timeout=60):
    """Gemini 에 묻고 {"items": [...]} 를 돌려준다. 키는 주소가 아니라 헤더로만 보낸다."""
    body = json.dumps({
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0,
            "responseMimeType": "application/json",
            "responseSchema": RESPONSE_SCHEMA,
        },
    }).encode("utf-8")
    request = urllib.request.Request(
        API_URL.format(model=model), data=body, method="POST",
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = json.loads(e.read().decode("utf-8")).get("error", {}).get("message", "")
        except (ValueError, AttributeError):
            pass
        hint = {400: "요청 형식 또는 키 문제", 403: "키 권한 문제", 404: f"모델 이름({model})을 찾을 수 없음",
                429: "사용량 한도 초과 — 잠시 후 다시", 500: "Gemini 서버 오류", 503: "Gemini 서버 혼잡"}
        raise ExtractError(f"Gemini 호출 실패 (HTTP {e.code}, {hint.get(e.code, '알 수 없음')}) {detail}".strip())
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise ExtractError(f"Gemini 에 연결하지 못했습니다 (인터넷 연결 확인): {getattr(e, 'reason', e)}")
    except ValueError:
        raise ExtractError("Gemini 응답을 읽지 못했습니다 (JSON 아님).")

    try:
        text = payload["candidates"][0]["content"]["parts"][0]["text"]
        result = json.loads(text)
    except (KeyError, IndexError, TypeError, ValueError):
        reason = payload.get("promptFeedback", {}).get("blockReason") or \
            (payload.get("candidates") or [{}])[0].get("finishReason", "응답 형식이 예상과 다름")
        raise ExtractError(f"Gemini 응답에서 결과를 꺼내지 못했습니다 ({reason}).")
    if not isinstance(result, dict) or not isinstance(result.get("items"), list):
        raise ExtractError("Gemini 응답이 약속한 JSON 모양이 아닙니다.")
    return result


# ---------- 근거 검사 (AI 를 믿지 않고 코드로 확인) ----------

def normalize(text):
    """비교용: 유니코드 정리, 따옴표 통일, 연속 공백을 한 칸으로."""
    text = unicodedata.normalize("NFC", text or "")
    text = re.sub("[‘’`´]", "'", text)
    text = re.sub("[“”]", '"', text)
    return re.sub(r"\s+", " ", text).strip()


def _compact(text):
    return re.sub(r"\s+", "", normalize(text)).lower()


def verify_item(field, raw, description):
    """AI 가 준 항목 하나를 검사해 최종 결과를 돌려준다. 통과 못 하면 value 를 비운다."""
    def review(reason, rejected=None):
        out = {"value": None, "evidence": None, "status": STATUS_REVIEW, "reason": reason}
        if rejected:
            out["rejected_value"] = rejected  # 사람이 참고만 하도록 남김. 사용 금지.
        return out

    if raw is None:
        return review("AI 가 이 항목에 답하지 않음")
    value = normalize(str(raw.get("value") or ""))
    evidence = normalize(str(raw.get("evidence") or ""))

    if not value and not evidence:
        return review("설명글에서 찾지 못함")
    if not evidence:
        return review("근거(evidence)가 없음", value)
    if evidence not in normalize(description):
        return review("근거 문장이 설명글에 그대로 있지 않음", value)
    if not value:
        return review("근거는 있으나 값이 비어 있음")
    if _compact(value) not in _compact(evidence):
        return review("값이 근거 문장 안에 없음 (AI 가 바꾸거나 지어냈을 수 있음)", value)
    return {"value": value, "evidence": evidence, "status": STATUS_OK, "reason": ""}


def verify_all(fields, result, description):
    by_field = {}
    for item in result.get("items", []):
        if isinstance(item, dict) and isinstance(item.get("field"), str):
            by_field.setdefault(item["field"].strip(), item)  # 같은 항목이 두 번 오면 첫 번째만
    return {field: verify_item(field, by_field.get(field), description) for field in fields}


# ---------- 저장 (실패해도 기존 파일을 망가뜨리지 않음) ----------

def save_json_atomic(data, path):
    """임시 파일에 다 쓴 뒤 한 번에 바꿔치기한다. 중간에 실패하면 기존 파일은 그대로다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def extract(description, fields, ask, model):
    """ask(prompt) → AI 결과. 테스트에서는 가짜 ask 를 넣는다."""
    result = ask(build_prompt(description, fields))
    facts = verify_all(fields, result, description)
    return {
        "created": datetime.now().isoformat(timespec="seconds"),
        "model": model,
        "notice": "'설명글에 있음'은 설명글에 그렇게 적혀 있다는 뜻이며, 실제 사실인지는 사람이 확인해야 합니다.",
        "fields": fields,
        "facts": facts,
    }


def main():
    parser = argparse.ArgumentParser(description="설명글 → Gemini 정보 추출 → 근거 검사 → data/facts.json")
    parser.add_argument("--description", type=Path, default=DESCRIPTION_FILE)
    parser.add_argument("--fields", type=Path, default=FIELDS_FILE)
    parser.add_argument("--output", type=Path, default=FACTS_FILE)
    args = parser.parse_args()
    resolve = lambda p: p if p.is_absolute() else PROJECT_ROOT / p

    fields = read_fields(resolve(args.fields))
    description = read_description(resolve(args.description))
    if os.environ.get("SHORTS_FAKE_GEMINI") == "1":
        # 테스트 전용: 실제 Gemini 대신 tests/fake_gemini.py 를 쓴다 (키 필요 없음)
        import importlib.util
        spec = importlib.util.spec_from_file_location("fake_gemini", Path(__file__).resolve().parent.parent / "tests" / "fake_gemini.py")
        fake = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fake)
        print("※ 테스트 모드: 가짜 Gemini 응답을 사용합니다.")
        model = "테스트용 가짜 Gemini"
        data = extract(description, fields, fake.ask, model)
        save_json_atomic(data, resolve(args.output))
        print(f"저장: {resolve(args.output)}")
        return 0
    try:
        api_key = get_gemini_api_key()
    except MissingKeyError as e:
        raise ExtractError(str(e))
    model = get_env_value("GEMINI_MODEL") or DEFAULT_MODEL

    print(f"항목 {len(fields)}개: {', '.join(fields)}")
    print(f"Gemini({model})에 묻는 중…")
    try:
        data = extract(description, fields, lambda prompt: call_gemini(prompt, api_key, model), model)
    except ExtractError as e:
        # 키가 어떤 경로로든 메시지에 섞이지 않게 한 번 더 지운다
        raise ExtractError(str(e).replace(api_key, "[키 숨김]"))

    output = resolve(args.output)
    save_json_atomic(data, output)

    print()
    for field, fact in data["facts"].items():
        if fact["status"] == STATUS_OK:
            print(f"  [설명글에 있음] {field}: {fact['value']}")
        else:
            print(f"  [확인 필요]   {field}: (비움) - {fact['reason']}")
    print(f"\n저장: {output}")
    print("※ '설명글에 있음'은 설명글에 적혀 있다는 뜻일 뿐, 실제로 맞는지는 직접 확인하세요.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ExtractError as e:
        print(f"\n오류: {e}")
        print("(data/facts.json 은 바뀌지 않았습니다.)")
        sys.exit(1)
