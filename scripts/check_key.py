"""키가 .env 에 제대로 들어 있는지 확인한다. 키 내용은 보여 주지 않는다.

사용법: python scripts/check_key.py
"""
import sys

from config import ENV_PATH, MissingKeyError, get_gemini_api_key


def main():
    try:
        key = get_gemini_api_key()
    except MissingKeyError as e:
        print(f"키가 없음: {e}")
        return 1
    print(f"키가 들어 있음, 글자 수 {len(key)}개")
    if not key.startswith("AIza") or len(key) != 39:
        print("주의: 보통 Gemini 키는 AIza 로 시작하고 39자입니다. 복사가 잘렸거나 다른 값이 들어갔는지 확인하세요.")
    print(f"(읽은 파일: {ENV_PATH})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
