"""API 키를 프로젝트 맨 위의 .env 파일에서만 읽는다.

키 값은 절대 출력하거나 로그에 남기지 않는다. 오류 메시지에도 키를 넣지 않는다.
"""
import os
from pathlib import Path

# 코드가 있는 폴더 (scripts/, web/, config/ 원본)
CODE_ROOT = Path(__file__).resolve().parent.parent
# 데이터 폴더 (input/, output/, data/ …). 테스트할 때만 SHORTS_ROOT 로 다른 폴더를 쓴다.
PROJECT_ROOT = Path(os.environ.get("SHORTS_ROOT") or CODE_ROOT).resolve()
ENV_PATH = PROJECT_ROOT / ".env"
PLACEHOLDER = "여기에키를붙여넣기"


class MissingKeyError(RuntimeError):
    pass


def _read_env_file(path=ENV_PATH):
    values = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        values[name.strip()] = value.strip().strip('"').strip("'")
    return values


def get_env_value(name):
    """키가 아닌 일반 설정값(예: GEMINI_MODEL)을 .env 에서 읽는다. 없으면 빈 문자열."""
    return _read_env_file().get(name, "")


def get_gemini_api_key():
    """GEMINI_API_KEY 를 .env 에서 읽어 돌려준다. 없으면 키 없이 설명만 담은 오류를 낸다."""
    if not ENV_PATH.is_file():
        raise MissingKeyError(".env 파일이 없습니다. .env.example 을 복사해 .env 를 만드세요.")
    key = _read_env_file().get("GEMINI_API_KEY", "")
    if not key or key == PLACEHOLDER:
        raise MissingKeyError(".env 에 GEMINI_API_KEY 가 비어 있거나 예시 문구 그대로입니다.")
    return key
